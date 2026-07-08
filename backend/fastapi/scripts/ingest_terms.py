"""법제처 법령용어 관계 Open API → 일상용어↔법령용어 매핑(term_map) 수집.

전체 용어사전(21만+) 덤프가 아니라, "우리 코퍼스(4법+시행령/규칙)" 조문에 실제로
연계된 법령용어만 역방향으로 좁혀 수집한다:
  1) statutes(trust_grade='법령') × articles → 법령ID/조번호 열거
  2) 조문→법령용어:  lawService.do?target=joRltLstrm&ID=<법령ID>&JO=<조번호6자리>
  3) 법령용어→일상용어: lawService.do?target=lstrmRlt&query=<법령용어명>
     (관계유형: 동의어/유의어/상위어/하위어/연관어 …) → 방향을 뒤집어
     (일상용어 → 법령용어) 행으로 저장 — 검색시 일상어 질의를 법령 표제어로 확장하는 용도.
  4) data/medilaw.db 의 term_map 테이블에 idempotent upsert.

인증: 환경변수 LAW_OC (기본 'H-Lab'). 관계 API는 lawService.do 전용, display 최대 100.
정중한 호출: ingest_api.py 와 동일하게 호출 간 0.2s sleep. 시간예산(--budget) 초과 시
정중히 중단하고 커버리지를 보고한다(재실행하면 이어서 수집 — upsert 덕에 안전).

사용법:
  python scripts/ingest_terms.py                 # 기본 (data/medilaw.db)
  python scripts/ingest_terms.py --db data/medilaw.db --budget 1680
"""
import argparse
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request

OC = os.environ.get("LAW_OC", "H-Lab")
BASE = "http://www.law.go.kr/DRF"
SLEEP = 0.2  # 호출 간 대기(정중한 호출 — ingest_api.py 와 동일)

_ARTNO_RE = re.compile(r"^(\d+)(?:의(\d+))?$")


def as_list(x):
    """API는 항목 1개면 list 대신 dict → 항상 list로 정규화."""
    if x is None or x == "":
        return []
    return x if isinstance(x, list) else [x]


def call(path, **params):
    """DRF JSON 호출 (URL 인코딩 + 재시도). HTML 응답(OC 미등록/오류)은 예외."""
    params.setdefault("OC", OC)
    params.setdefault("type", "JSON")
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                raw = r.read().decode("utf-8", "ignore")
            if raw.lstrip().startswith("<"):
                raise RuntimeError("HTML 응답(OC 미등록/미신청 또는 오류)")
            return json.loads(raw) if raw.strip() else {}
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.5)


def norm_term(s: str) -> str:
    """용어 정규화: 양끝 공백 제거 + 라틴문자 소문자화(CCTV→cctv).
    한글은 lower()에 불변이라 전체 lower로 충분. 내부 연속공백은 1칸으로."""
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def jo_code(article_no: str) -> str | None:
    """articles.article_no('27', '28의5') → JO 6자리('002700', '002805')."""
    m = _ARTNO_RE.match((article_no or "").strip())
    if not m:
        return None
    base, branch = int(m.group(1)), int(m.group(2) or 0)
    return f"{base:04d}{branch:02d}"


def ensure_table(conn: sqlite3.Connection):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS term_map (
            daily_term TEXT NOT NULL,
            legal_term TEXT NOT NULL,
            relation TEXT NOT NULL,
            source_law TEXT,
            source_article TEXT)"""
    )
    # (일상용어, 법령용어, 관계) 조합으로 유일 — 재실행 시 upsert(idempotent).
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_term_map_uniq
           ON term_map(daily_term, legal_term, relation)"""
    )
    # 1단계(조문→법령용어) 결과 캐시 — 중단 후 재실행 시 조문 API 1,105회를 다시 돌지 않게.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS term_src (
            legal_term TEXT PRIMARY KEY,
            source_law TEXT,
            source_article TEXT)"""
    )
    conn.commit()


# ---------- 1·2단계: 코퍼스 조문 → 법령용어 ----------
def collect_legal_terms(conn: sqlite3.Connection, deadline: float):
    """코퍼스 전 조문에 joRltLstrm 호출 → {법령용어명: (source_law, source_article)}.
    같은 용어가 여러 조문에 나오면 최초 출처만 기록(출처는 참고용).
    결과는 term_src 에 영속화 — 이미 캐시가 있으면 API 재호출 없이 그대로 사용."""
    cached = conn.execute(
        "SELECT legal_term, source_law, source_article FROM term_src"
    ).fetchall()
    if cached:
        print(f"[1/2 캐시] term_src {len(cached):,}개 용어 재사용(조문 API 생략)")
        return {l: (sl, sa) for l, sl, sa in cached}, 0, 0, False
    rows = conn.execute(
        """SELECT s.law_id, s.name, a.article_no
           FROM articles a JOIN statutes s ON s.id = a.statute_id
           WHERE s.trust_grade = '법령'
           ORDER BY s.id, a.id"""
    ).fetchall()
    terms: dict[str, tuple[str, str]] = {}
    done = fail = 0
    truncated = False
    for law_id, law_name, art_no in rows:
        if time.time() > deadline:
            truncated = True
            break
        jo = jo_code(art_no)
        if not jo:
            continue
        try:
            d = call("lawService.do", target="joRltLstrm", ID=law_id, JO=jo)
        except Exception:
            fail += 1
            continue
        svc = d.get("joRltLstrmService", {}) if isinstance(d, dict) else {}
        unit = svc.get("법령조문", {})
        for u in as_list(unit if not isinstance(unit, dict) or "연계용어" in unit else []):
            for t in as_list(u.get("연계용어") if isinstance(u, dict) else None):
                if not isinstance(t, dict):
                    continue
                name = (t.get("법령용어명") or "").strip()
                if len(name) >= 2 and name not in terms:
                    terms[name] = (law_name, art_no)
        done += 1
        if done % 100 == 0:
            print(f"  [1/2 조문→용어] {done}/{len(rows)}조 처리, 유니크 용어 {len(terms)}개")
        time.sleep(SLEEP)
    print(f"[1/2 완료] 조문 {done}/{len(rows)}개 조회(실패 {fail}), 유니크 법령용어 {len(terms)}개"
          + (" ※ 시간예산으로 조기 중단" if truncated else ""))
    # 완주했을 때만 캐시 영속화(부분 캐시가 이후 실행의 전체로 오인되지 않게).
    if not truncated:
        conn.executemany(
            "INSERT OR IGNORE INTO term_src (legal_term, source_law, source_article) VALUES (?,?,?)",
            [(l, sl, sa) for l, (sl, sa) in terms.items()],
        )
        conn.commit()
    return terms, done, len(rows), truncated


# ---------- 3·4단계: 법령용어 → 일상용어 관계 → term_map ----------
def collect_relations(conn: sqlite3.Connection, terms: dict, deadline: float):
    """각 법령용어에 lstrmRlt 호출 → (일상용어→법령용어) 행 upsert."""
    inserted = queried = with_rel = 0
    truncated = False
    # 재실행(resume) 지원: 이미 term_map 에 legal_term 으로 들어간 용어는 조회를 건너뛴다.
    # (실측상 연계 API로 수집된 법령용어는 사실상 전부 1개 이상의 관계를 반환 → 존재 여부로 충분)
    already = {r[0] for r in conn.execute("SELECT DISTINCT legal_term FROM term_map")}
    items = [(l, s) for l, s in terms.items() if norm_term(l) not in already]
    skipped = len(terms) - len(items)
    if skipped:
        print(f"  [2/2] 기수집 용어 {skipped}개 스킵(재실행 이어받기)")
    for i, (legal, (src_law, src_art)) in enumerate(items):
        if time.time() > deadline:
            truncated = True
            break
        try:
            d = call("lawService.do", target="lstrmRlt", query=legal, display=100)
        except Exception:
            continue
        queried += 1
        svc = d.get("lstrmRltService", {}) if isinstance(d, dict) else {}
        node = svc.get("법령용어", {})
        rels = []
        for u in as_list(node):
            if isinstance(u, dict):
                rels += as_list(u.get("연계용어"))
        legal_n = norm_term(legal)
        got = False
        for r in rels:
            if not isinstance(r, dict):
                continue
            daily = norm_term(r.get("일상용어명") or "")
            relation = (r.get("용어관계") or "").strip()
            # 노이즈 가드: 1글자 용어·자기자신 매핑·관계 미상은 제외.
            if len(daily) < 2 or not relation or daily == legal_n:
                continue
            cur = conn.execute(
                """INSERT INTO term_map (daily_term, legal_term, relation, source_law, source_article)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(daily_term, legal_term, relation) DO NOTHING""",
                (daily, legal_n, relation, src_law, src_art),
            )
            inserted += cur.rowcount if cur.rowcount > 0 else 0
            got = True
        if got:
            with_rel += 1
        if (i + 1) % 100 == 0:
            conn.commit()
            print(f"  [2/2 용어→관계] {i + 1}/{len(items)}개 용어 조회, 신규 {inserted}행")
        time.sleep(SLEEP)
    conn.commit()
    print(f"[2/2 완료] 법령용어 {queried}/{len(items)}개 조회(관계 보유 {with_rel}개), 신규 {inserted}행"
          + (" ※ 시간예산으로 조기 중단" if truncated else ""))
    return inserted, queried, truncated


def summary(conn: sqlite3.Connection):
    n = conn.execute("SELECT COUNT(*) FROM term_map").fetchone()[0]
    nd = conn.execute("SELECT COUNT(DISTINCT daily_term) FROM term_map").fetchone()[0]
    nl = conn.execute("SELECT COUNT(DISTINCT legal_term) FROM term_map").fetchone()[0]
    print(f"\n=== term_map 총 {n:,}행 (일상용어 {nd:,} / 법령용어 {nl:,}) ===")
    for rel, c in conn.execute(
        "SELECT relation, COUNT(*) FROM term_map GROUP BY relation ORDER BY 2 DESC"
    ):
        print(f"  {rel}: {c:,}")
    print("\n--- 검증 샘플 ---")
    for probe in ("cctv", "스팸", "환자", "의사"):
        rows = conn.execute(
            """SELECT legal_term, relation FROM term_map WHERE daily_term = ?
               ORDER BY CASE relation WHEN '동의어' THEN 0 WHEN '유의어' THEN 1 ELSE 2 END
               LIMIT 5""",
            (probe,),
        ).fetchall()
        print(f"  {probe} → " + (", ".join(f"{l}({r})" for l, r in rows) if rows else "(없음)"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/medilaw.db")
    ap.add_argument("--budget", type=int, default=1680, help="총 시간예산(초), 기본 28분")
    args = ap.parse_args()

    start = time.time()
    deadline = start + args.budget
    conn = sqlite3.connect(args.db)
    ensure_table(conn)

    terms, done, total, t1 = collect_legal_terms(conn, deadline)
    inserted, queried, t2 = collect_relations(conn, terms, deadline)
    summary(conn)
    print(f"\n소요 {time.time() - start:,.0f}s | 조문 커버리지 {done}/{total} | "
          f"용어 커버리지 {queried}/{len(terms)} | 신규 {inserted}행"
          + (" | ⚠️ 예산 초과로 부분 수집 — 재실행 시 이어서 채워짐" if (t1 or t2) else ""))
    conn.close()


if __name__ == "__main__":
    main()
