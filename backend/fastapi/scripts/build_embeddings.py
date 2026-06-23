"""articles + cases 임베딩 빌드 → medilaw.db 의 chunks(+sqlite-vec) 적재.

idempotent: 재실행 시 기존 chunks/chunk_vec 삭제 후 재적재.
실행:
    OPENAI_API_KEY=... DB_PATH=data/medilaw.db python3 scripts/build_embeddings.py
옵션 환경변수:
    ONLY=statute|case   특정 출처만
    LIMIT=1000          테스트용 일부만
판례는 본문이 길어 case_name+issues+summary 만 1판례=1벡터로 임베딩(본문 중복 회피).
조문은 전문 임베딩.
"""
import os
import re
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import DB_PATH, EMBED_DIM, EMBED_MODEL, OPENAI_API_KEY  # noqa: E402

BATCH = 256
ONLY = os.environ.get("ONLY", "")
LIMIT = int(os.environ.get("LIMIT", "0"))
# incremental(기본): 아직 임베딩 안 된 행만 추가 (코퍼스 확장용)
# rebuild: chunks 전체 삭제 후 재생성
MODE = os.environ.get("MODE", "incremental")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn, True
    except Exception as e:
        print(f"[warn] sqlite-vec 로드 실패({e}) → BLOB 저장(numpy 폴백)")
        return conn, False


def setup(conn, vec_ok):
    if MODE == "rebuild":
        conn.execute("DROP TABLE IF EXISTS chunks")
        if vec_ok:
            conn.execute("DROP TABLE IF EXISTS chunk_vec")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chunks(
            id INTEGER PRIMARY KEY,
            source_type TEXT, source_id INTEGER,
            label TEXT, content TEXT, embedding BLOB)"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_src ON chunks(source_type, source_id)"
    )
    if vec_ok:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(embedding float[{EMBED_DIM}])"
        )
    conn.commit()


def _existing(conn) -> set:
    """incremental: 이미 임베딩된 (source_type, source_id) 집합."""
    if MODE == "rebuild":
        return set()
    return {(r["source_type"], r["source_id"]) for r in
            conn.execute("SELECT source_type, source_id FROM chunks")}


# sub-chunk: 긴 본문은 여러 조각으로 분할(각 조각=1벡터)해 대형 문서의 검색 희석 방지
SUB_MAX = int(os.environ.get("SUB_MAX", "1200"))   # 이 길이 초과면 분할
PIECE = int(os.environ.get("PIECE", "1000"))        # 조각 목표 길이
OVERLAP = int(os.environ.get("OVERLAP", "120"))     # 조각 간 겹침


def chunk_text(text: str):
    """문단/문장 경계를 가급적 살려 ~PIECE 길이로 분할(겹침 OVERLAP)."""
    text = text.strip()
    if len(text) <= SUB_MAX:
        return [text]
    pieces, i, n = [], 0, len(text)
    while i < n:
        end = min(i + PIECE, n)
        if end < n:  # 경계 보정: 가까운 줄바꿈/마침표/공백에서 끊기
            window = text[end : min(end + 200, n)]
            m = re.search(r"[\n。\.]\s|\n", window)
            if m:
                end += m.end()
        pieces.append(text[i:end].strip())
        if end >= n:
            break
        i = end - OVERLAP
    return [p for p in pieces if p]


def _emit(rows, done, st, sid, label, body):
    """긴 본문은 sub-chunk로 확장. 각 조각에 label을 붙여 문맥 유지."""
    if (st, sid) in done:
        return
    body = (body or "").strip()
    if not body:
        return
    for piece in chunk_text(body):
        rows.append((st, sid, label, f"{label}\n{piece}" if label else piece))


def gather(conn):
    """(source_type, source_id, label, content) 목록. 긴 본문은 sub-chunk로 분할."""
    done = _existing(conn)
    rows = []
    if ONLY in ("", "statute"):
        q = """SELECT a.id, s.name, a.article_no, a.article_title, a.content
               FROM articles a JOIN statutes s ON s.id = a.statute_id
               WHERE a.content IS NOT NULL AND a.content != ''"""
        from app.rag import fmt_article_label

        for r in conn.execute(q):
            label = fmt_article_label(r["name"], r["article_no"], r["article_title"])
            _emit(rows, done, "statute", r["id"], label, r["content"])
    if ONLY in ("", "case"):
        for r in conn.execute("SELECT id, case_no, court, case_name, issues, summary FROM cases"):
            label = " ".join(filter(None, [r["court"], r["case_no"]])) or (r["case_name"] or "")
            text = "\n".join(filter(None, [r["case_name"], r["issues"], r["summary"]]))
            _emit(rows, done, "case", r["id"], label, text)
    has_docs = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone()
    if has_docs and ONLY in ("", "interpretation", "decision", "guideline"):
        for r in conn.execute("SELECT id, doc_type, title, body FROM documents"):
            if ONLY and r["doc_type"] != ONLY:
                continue
            text = "\n".join(filter(None, [r["title"], r["body"]]))
            _emit(rows, done, r["doc_type"], r["id"], r["title"] or "", text)
    if LIMIT:
        rows = rows[:LIMIT]
    return rows


def main():
    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 필요합니다.")
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    conn, vec_ok = connect()
    setup(conn, vec_ok)

    rows = gather(conn)
    print(f"[{MODE}] 임베딩 대상 {len(rows):,}건 (모델={EMBED_MODEL}, dim={EMBED_DIM}, vec={vec_ok})")
    if not rows:
        print("추가할 새 행 없음 — 종료.")
        return

    import struct

    done = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        texts = [r[3][:8000] for r in batch]
        for attempt in range(5):
            try:
                resp = client.embeddings.create(
                    model=EMBED_MODEL, input=texts, dimensions=EMBED_DIM
                )
                break
            except Exception as e:
                wait = 2 ** attempt
                print(f"[retry {attempt+1}] {e} → {wait}s")
                time.sleep(wait)
        else:
            sys.exit("임베딩 호출 반복 실패")

        for (stype, sid, label, content), d in zip(batch, resp.data):
            blob = struct.pack(f"{EMBED_DIM}f", *d.embedding)
            cur = conn.execute(
                "INSERT INTO chunks(source_type, source_id, label, content, embedding) VALUES(?,?,?,?,?)",
                (stype, sid, label, content[:2000], blob),
            )
            if vec_ok:
                import sqlite_vec

                conn.execute(
                    "INSERT INTO chunk_vec(rowid, embedding) VALUES(?,?)",
                    (cur.lastrowid, sqlite_vec.serialize_float32(d.embedding)),
                )
        conn.commit()
        done += len(batch)
        print(f"  {done:,}/{len(rows):,}")

    print(f"완료. chunks={conn.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]:,}")


if __name__ == "__main__":
    main()
