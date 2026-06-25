"""하이브리드 검색 레이어 — FTS5(BM25) + 벡터(코사인) RRF 융합.

임베딩/키가 없으면 자동으로 FTS 전용으로 동작(graceful degradation).
- statute 히트: 조문(article) 단위 (clause-level retrieval)
- case 히트: 판례 단위
- interpretation(해석례)·decision(결정문)·guideline(가이드라인): documents 테이블에 적재되어 검색됨
"""
import re
import threading
from collections import OrderedDict
from functools import lru_cache

from app.config import (
    DEFAULT_TOP_K,
    EMBED_DIM,
    EMBED_MODEL,
    OPENAI_API_KEY,
    RRF_K,
)
from app.db import db, has_embeddings, vec_loaded
from app.schemas import Hit

_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}|\d+")
_ARTNO_RE = re.compile(r"\d+(?:의\d+)?")


def fmt_article_label(law_name: str, article_no: str, article_title: str = "") -> str:
    """행정규칙('제9조')·법령('57') 혼재 article_no를 '법령 제N조(제목)'로 정규화."""
    m = _ARTNO_RE.search(article_no or "")
    no = m.group(0) if m else (article_no or "")
    label = f"{law_name} 제{no}조"
    title = (article_title or "").strip()
    if title:
        label += f"({title})"
    return label


def _fts_match_expr(query: str) -> str:
    """사용자 자유질의를 안전한 FTS5 MATCH 식으로 변환 (토큰 OR)."""
    terms = _TOKEN_RE.findall(query)
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))  # 중복 제거, 순서 유지


# ---------- 임베딩 ----------
def embed_query(text: str) -> list[float] | None:
    """OpenAI 임베딩. 키 없으면 None → 벡터검색 건너뜀."""
    if not OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.embeddings.create(
            model=EMBED_MODEL, input=text, dimensions=EMBED_DIM
        )
        return resp.data[0].embedding
    except Exception:
        return None


# ---------- 임베딩 캐시 ----------
# 같은 질의 문구의 재임베딩(API 왕복)을 피하기 위한 모듈 레벨 bounded LRU 캐시.
# 키 = (EMBED_MODEL, EMBED_DIM, text) — 모델/차원이 바뀌면 캐시가 섞이지 않게.
# None(실패·키없음)은 캐시하지 않는다(일시 실패가 영구 캐시되지 않도록).
_EMBED_CACHE_MAX = 4096
_embed_cache: "OrderedDict[tuple, list[float]]" = OrderedDict()
_embed_cache_lock = threading.Lock()


def _embed_cache_get(text: str) -> list[float] | None:
    """캐시 조회. 적중 시 LRU 갱신(최근 사용으로 이동)."""
    key = (EMBED_MODEL, EMBED_DIM, text)
    with _embed_cache_lock:
        vec = _embed_cache.get(key)
        if vec is not None:
            _embed_cache.move_to_end(key)
        return vec


def _embed_cache_put(text: str, vec: list[float]) -> None:
    """캐시 적재 + 상한 초과 시 가장 오래된 항목 제거(LRU). None은 호출 전에 걸러진다."""
    key = (EMBED_MODEL, EMBED_DIM, text)
    with _embed_cache_lock:
        _embed_cache[key] = vec
        _embed_cache.move_to_end(key)
        while len(_embed_cache) > _EMBED_CACHE_MAX:
            _embed_cache.popitem(last=False)  # 가장 오래된 것 제거


def embed_queries(texts: list[str]) -> list[list[float] | None]:
    """여러 질의를 OpenAI 임베딩 1회 호출로 배치 임베딩(런타임 N→1 단축).

    반환은 입력과 같은 순서·길이. 키 없음/실패 시 [None]*len(texts)(graceful → FTS 전용).
    캐시: 같은 문구는 재임베딩하지 않고, 미캐시 유니크 텍스트만 1회 배치 호출.
    """
    if not texts:
        return []

    # 1) 캐시 적중분을 먼저 채우고, 미적중 유니크 텍스트만 모은다(순서·길이 보존).
    out: list[list[float] | None] = [None] * len(texts)
    miss_positions: dict[str, list[int]] = {}  # 텍스트 → 그 텍스트가 등장한 입력 인덱스들
    for i, t in enumerate(texts):
        cached = _embed_cache_get(t)
        if cached is not None:
            out[i] = cached
        else:
            miss_positions.setdefault(t, []).append(i)

    if not miss_positions:
        return out  # 전부 캐시 적중 → API 미호출

    if not OPENAI_API_KEY:
        return out  # 미적중분은 None(graceful → FTS 전용)

    # 2) 미캐시 유니크 텍스트만 1회 배치 임베딩.
    uniq_texts = list(miss_positions.keys())
    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.embeddings.create(
            model=EMBED_MODEL, input=uniq_texts, dimensions=EMBED_DIM
        )
        # data 순서는 input 순서와 같지만 방어적으로 index 기준 정렬.
        by_idx = {d.index: d.embedding for d in resp.data}
    except Exception:
        return out  # 실패분은 None 유지(예외 전파·캐시 금지)

    # 3) 결과를 원래 위치들에 매핑하고, None 이 아닌 것만 캐시에 적재.
    for j, t in enumerate(uniq_texts):
        vec = by_idx.get(j)
        if vec is None:
            continue  # 부분 실패분은 None 유지·캐시 금지
        _embed_cache_put(t, vec)
        for pos in miss_positions[t]:
            out[pos] = vec
    return out


# hybrid_search 의 qvec 인자 기본값 — "미지정(내부 임베딩)"과 "None(벡터검색 생략)"을 구분.
_UNSET = object()


# ---------- 시점(as_of) 정규화 ----------
def _compact(date_str: str) -> str:
    """'YYYY-MM-DD' 또는 'YYYYMMDD' → 'YYYYMMDD'."""
    return re.sub(r"\D", "", date_str or "")


# ---------- Hit 빌더 ----------
def _statute_hit(article_id: int, score: float, snippet: str = "") -> Hit | None:
    row = db().execute(
        """SELECT a.id, a.article_no, a.article_title, a.content,
                  s.name AS law_name, s.trust_grade, s.effective_from, s.source_url
           FROM articles a JOIN statutes s ON s.id = a.statute_id
           WHERE a.id = ?""",
        (article_id,),
    ).fetchone()
    if not row:
        return None
    title = (row["article_title"] or "").strip()
    label = fmt_article_label(row["law_name"], row["article_no"], title)
    return Hit(
        source_type="statute",
        source_id=row["id"],
        label=label,
        title=title,
        snippet=snippet or (row["content"] or "")[:300],
        score=score,
        trust_grade=row["trust_grade"] or "",
        effective_from=row["effective_from"],
        source_url=row["source_url"] or "",
    )


def _case_hit(case_id: int, score: float, snippet: str = "") -> Hit | None:
    row = db().execute(
        """SELECT id, case_no, case_name, court, date, summary, source_url
           FROM cases WHERE id = ?""",
        (case_id,),
    ).fetchone()
    if not row:
        return None
    label = " ".join(filter(None, [row["court"], row["case_no"]])) or row["case_name"]
    return Hit(
        source_type="case",
        source_id=row["id"],
        label=label,
        title=row["case_name"] or "",
        snippet=snippet or (row["summary"] or "")[:300],
        score=score,
        trust_grade="판례",
        effective_from=_compact(row["date"]) if row["date"] else None,
        source_url=row["source_url"] or "",
    )


_DOC_LABEL = {"interpretation": "법령해석례", "decision": "개인정보위 결정문", "guideline": "가이드라인"}
_DOC_TYPES = ("interpretation", "decision", "guideline")


def _doc_table_ready() -> bool:
    return db().execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
    ).fetchone() is not None


def _doc_hit(doc_id: int, score: float, snippet: str = "") -> Hit | None:
    row = db().execute(
        "SELECT id, doc_type, title, agency, date, body, source_url FROM documents WHERE id=?",
        (doc_id,),
    ).fetchone()
    if not row:
        return None
    kind = _DOC_LABEL.get(row["doc_type"], row["doc_type"])
    return Hit(
        source_type=row["doc_type"],
        source_id=row["id"],
        label=f"[{kind}] {row['title']}".strip(),
        title=row["title"] or "",
        snippet=snippet or (row["body"] or "")[:300],
        score=score,
        trust_grade=kind,
        effective_from=_compact(row["date"]) if row["date"] else None,
        source_url=row["source_url"] or "",
    )


# ---------- FTS 검색 ----------
def fts_search(query: str, source_types: set[str], limit: int) -> list[tuple[str, int]]:
    """(source_type, source_id) 를 BM25 순으로 반환."""
    expr = _fts_match_expr(query)
    if not expr:
        return []
    conn = db()
    out: list[tuple[str, int]] = []
    if "statute" in source_types:
        rows = conn.execute(
            """SELECT a.id FROM articles_fts f JOIN articles a ON a.id = f.rowid
               WHERE articles_fts MATCH ? ORDER BY bm25(articles_fts) LIMIT ?""",
            (expr, limit),
        ).fetchall()
        out += [("statute", r["id"]) for r in rows]
    if "case" in source_types:
        rows = conn.execute(
            """SELECT c.id FROM cases_fts f JOIN cases c ON c.id = f.rowid
               WHERE cases_fts MATCH ? ORDER BY bm25(cases_fts) LIMIT ?""",
            (expr, limit),
        ).fetchall()
        out += [("case", r["id"]) for r in rows]
    doc_types = [t for t in _DOC_TYPES if t in source_types]
    if doc_types and _doc_table_ready():
        ph = ",".join("?" * len(doc_types))
        rows = conn.execute(
            f"""SELECT d.id, d.doc_type FROM documents_fts f JOIN documents d ON d.id = f.rowid
                WHERE documents_fts MATCH ? AND d.doc_type IN ({ph})
                ORDER BY bm25(documents_fts) LIMIT ?""",
            (expr, *doc_types, limit),
        ).fetchall()
        out += [(r["doc_type"], r["id"]) for r in rows]
    return out


# ---------- 벡터 검색 ----------
@lru_cache(maxsize=1)
def _numpy_matrix():
    """numpy 폴백용 임베딩 행렬 로드 (sqlite-vec 없을 때). content 포함(스니펫용).

    배포용 슬림 DB는 chunks.embedding BLOB을 제거(sqlite-vec만 사용)하므로,
    컬럼이 없으면 폴백 불가 → None 반환(검색은 sqlite-vec 또는 FTS로 동작).
    """
    import numpy as np

    conn = db()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
    if "embedding" not in cols:
        return None
    ids, types, conts, vecs = [], [], [], []
    for r in conn.execute("SELECT source_type, source_id, content, embedding FROM chunks"):
        if r["embedding"] is None:
            continue
        ids.append(r["source_id"])
        types.append(r["source_type"])
        conts.append(r["content"] or "")
        vecs.append(np.frombuffer(r["embedding"], dtype=np.float32))
    if not vecs:
        return None
    mat = np.vstack(vecs)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return ids, types, conts, mat / norms


def vector_search(qvec: list[float], source_types: set[str], limit: int) -> list[tuple[str, int, str]]:
    """(source_type, source_id, 매칭 sub-chunk 스니펫). 한 문서가 여러 sub-chunk면 중복 가능(상위에서 dedup)."""
    if not has_embeddings():
        return []
    conn = db()
    if vec_loaded():
        try:
            import sqlite_vec

            rows = conn.execute(
                """SELECT c.source_type, c.source_id, c.content
                   FROM chunk_vec v JOIN chunks c ON c.id = v.rowid
                   WHERE v.embedding MATCH ? AND k = ?
                   ORDER BY v.distance""",
                (sqlite_vec.serialize_float32(qvec), limit * 5),
            ).fetchall()
            return [
                (r["source_type"], r["source_id"], (r["content"] or "")[:300])
                for r in rows
                if r["source_type"] in source_types
            ][: limit * 3]
        except Exception:
            pass
    # numpy 폴백
    import numpy as np

    loaded = _numpy_matrix()
    if not loaded:
        return []
    ids, types, conts, mat = loaded
    q = np.asarray(qvec, dtype=np.float32)
    q = q / (np.linalg.norm(q) or 1.0)
    order = np.argsort(-(mat @ q))
    out: list[tuple[str, int, str]] = []
    for i in order:
        if types[i] in source_types:
            out.append((types[i], ids[i], (conts[i] or "")[:300]))
        if len(out) >= limit * 3:
            break
    return out


# ---------- RRF 융합 ----------
def hybrid_search(
    query: str,
    source_types: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    as_of: str | None = None,
    qvec=_UNSET,
) -> tuple[list[Hit], str]:
    """RRF로 FTS+벡터 융합. (hits, method) 반환.

    qvec: 미지정(_UNSET)이면 내부에서 query를 임베딩. 미리 구한 벡터를 넘기면
        재임베딩을 건너뛴다(런타임 배치 임베딩용). None을 명시하면 벡터검색 생략(FTS 전용).
    """
    types = set(source_types) if source_types else {"statute", "case", *_DOC_TYPES}
    pool = max(top_k * 3, 30)

    fts = fts_search(query, types, pool)
    if qvec is _UNSET:
        qvec = embed_query(query) if has_embeddings() else None
    vraw = vector_search(qvec, types, pool) if qvec else []
    method = "hybrid" if vraw else "fts"

    # sub-chunk → 문서별 dedup(최상위 rank 유지) + 매칭 sub-chunk 스니펫 보존
    snippet_map: dict[tuple[str, int], str] = {}
    vec: list[tuple[str, int]] = []
    for st, sid, snip in vraw:
        key = (st, sid)
        if key not in snippet_map:
            snippet_map[key] = snip
        vec.append(key)

    def _dedup(seq):
        seen, out = set(), []
        for k in seq:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out

    fts, vec = _dedup(fts), _dedup(vec)

    # RRF: score = Σ 1/(K + rank)
    scores: dict[tuple[str, int], float] = {}
    for ranklist in (fts, vec):
        for rank, key in enumerate(ranklist):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)

    ordered = sorted(scores.items(), key=lambda x: -x[1])

    hits: list[Hit] = []
    as_of_c = _compact(as_of) if as_of else None
    for (stype, sid), score in ordered:
        snip = snippet_map.get((stype, sid), "")
        if stype == "statute":
            hit = _statute_hit(sid, score, snip)
        elif stype == "case":
            hit = _case_hit(sid, score, snip)
        else:  # interpretation / decision / guideline
            hit = _doc_hit(sid, score, snip)
        if not hit:
            continue
        if as_of_c and hit.effective_from and hit.effective_from > as_of_c:
            continue  # 시점 필터: as_of 이후 발효/선고 자료 제외
        hits.append(hit)
        if len(hits) >= top_k:
            break
    return hits, method


def search_statutes(q: str = "", kind: str = "", trust_grade: str = "",
                    as_of: str = "", limit: int = 20) -> list[dict]:
    """법령/행정규칙 검색 (조문 FTS → 법령 단위). 라우터·MCP 공용."""
    conn = db()
    params: list = []
    if q:
        sql = """SELECT DISTINCT s.id, s.law_id, s.name, s.kind, s.trust_grade,
                        s.effective_from, s.source_url
                 FROM articles_fts f JOIN articles a ON a.id = f.rowid
                 JOIN statutes s ON s.id = a.statute_id
                 WHERE articles_fts MATCH ?"""
        params.append(_fts_match_expr(q))
        alias = "s."
    else:
        sql = """SELECT id, law_id, name, kind, trust_grade, effective_from, source_url
                 FROM statutes WHERE 1=1"""
        alias = ""
    if kind:
        sql += f" AND {alias}kind = ?"
        params.append(kind)
    if trust_grade:
        sql += f" AND {alias}trust_grade = ?"
        params.append(trust_grade)
    if as_of:
        sql += f" AND {alias}effective_from <= ?"
        params.append(_compact(as_of))
    sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
