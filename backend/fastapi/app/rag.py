"""하이브리드 검색 레이어 — FTS5(BM25) + 벡터(코사인) RRF 융합.

임베딩/키가 없으면 자동으로 FTS 전용으로 동작(graceful degradation).
- statute 히트: 조문(article) 단위 (clause-level retrieval)
- case 히트: 판례 단위
- interpretation(해석례)·decision(결정문)·guideline(가이드라인): documents 테이블에 적재되어 검색됨
"""
import os
import re
import threading
from collections import OrderedDict
from functools import lru_cache

from app.config import (
    CORE_TRUST_GRADE,
    DEFAULT_TOP_K,
    EMBED_DIM,
    EMBED_MODEL,
    OPENAI_API_KEY,
    RAG_POOL,
    RRF_K,
    STATUTE_BOOST,
    STATUTE_CORE_ONLY,
    STATUTE_PENALTY,
    STATUTE_PENALTY_KINDS,
    STATUTE_TITLE_CAP,
)
from app.db import db, has_embeddings, vec_loaded
from app.schemas import Hit

_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}|\d+")
_ARTNO_RE = re.compile(r"\d+(?:의\d+)?")


def fmt_article_label(law_name: str, article_no: str, article_title: str = "") -> str:
    """행정규칙('제9조')·법령('57')·가지조문('28의5') 혼재 article_no를
    '법령 제N조(제목)' / '법령 제N조의M(제목)'로 정규화."""
    m = _ARTNO_RE.search(article_no or "")
    no = m.group(0) if m else (article_no or "")
    if "의" in no:
        base, branch = no.split("의", 1)
        art = f"제{base}조의{branch}"
    else:
        art = f"제{no}조"
    label = f"{law_name} {art}"
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


# ---------- 법률용어 동의어 확장 (FTS 전용) ----------
# 일상어 질의 ↔ 법령 용어의 어휘 불일치 보정(예: "CCTV" ↔ 개보법 제25조 "고정형 영상정보처리기기").
# FTS(BM25)는 토큰 정확일치라 표제어가 다르거나 조사가 붙으면("민감정보는"≠"민감정보") 매칭 실패.
# 질의에 해당 법령 표제어 토큰을 덧붙여 FTS 검색에만 사용한다 — 임베딩 질의에는 적용하지
# 않는다(용어 추가가 질의 의미를 흐려 벡터 랭킹이 오히려 악화됨을 골든셋으로 실측).
_FTS_SYNONYMS: dict[str, str] = {
    "cctv": "고정형 영상정보처리기기 영상정보",       # 개보법 제25조·제25조의2
    "씨씨티비": "고정형 영상정보처리기기 영상정보",
    "폐쇄회로": "고정형 영상정보처리기기 영상정보",
    "민감정보": "민감정보의 처리 제한",               # 개보법 제23조(민감정보의 처리 제한) — 표제 토큰 그대로
    "가명처리": "가명정보 처리",                      # 개보법 제28조의2(가명정보의 처리 등)
}

# ---------- 법제처 용어관계 term_map (scripts/ingest_terms.py 수집) ----------
# 하드코딩 _FTS_SYNONYMS 를 "보충"하는 대규모 일상어→법령용어 사전. 코퍼스 조문에
# 연계된 법령용어만 역수집한 것이라 도메인 밖 노이즈가 적다. FTS 채널 전용(위와 동일 근거).
_TERM_MAP_MAX_ADD = 6                 # 질의당 덧붙일 법령용어 상한(FTS 질의 비대화 방지)
# 채택 관계·우선순위(동의어 → 연관어 → 상·하위어 순으로 슬롯 배분).
# 확장은 "코퍼스 조문에 없는 일상어"(진짜 어휘 불일치: 스팸·해킹·CCTV·3차병원)에만 적용 —
# 질의 단어가 이미 조문에 있으면 FTS 직접 매칭이 되므로 확장이 불필요하고, 오히려
# 동음이의 동의어(의사→의견)·준-무관 연관어(진료기록→진료기록전송지원시스템)가
# BM25 를 희석해 골든/블라인드 순위가 회귀함을 실측. 조문에 없는 단어는 어차피
# FTS 기여가 0이라, 방향이 다소 어긋난 관계(상·하위어: 해킹→침해사고)라도 득이 크다.
_TERM_MAP_RELATIONS = ("동의어", "연관어", "상위어", "하위어")


@lru_cache(maxsize=1)
def _term_map() -> tuple[dict[str, list[str]], tuple[str, ...]]:
    """term_map 테이블 → ({일상용어(소문자): 우선순위 정렬된 법령용어들}, 길이 내림차순 키).

    - 관계는 _TERM_MAP_RELATIONS 만 채택(상위어·하위어 등은 노이즈로 배제), 1글자 용어 제외.
    - 테이블 없음/빈 테이블/환경변수 TERM_MAP_OFF=1(효과 측정용)이면 빈 맵
      → 기존 하드코딩 _FTS_SYNONYMS 만으로 동작(graceful fallback).
    """
    empty: tuple[dict[str, list[str]], tuple[str, ...]] = ({}, ())
    if os.environ.get("TERM_MAP_OFF"):
        return empty
    try:
        rows = db().execute(
            "SELECT daily_term, legal_term, relation FROM term_map"
        ).fetchall()
    except Exception:
        return empty  # 테이블 없음 등 → 기존 동작 유지
    prio = {rel: i for i, rel in enumerate(_TERM_MAP_RELATIONS)}

    @lru_cache(maxsize=None)
    def _in_corpus(term: str) -> bool:
        """일상어가 조문 텍스트에 (접두 토큰으로라도) 이미 존재하는지 FTS 프로브.
        존재하면 FTS 직접 매칭이 되므로 확장 대상에서 제외한다."""
        try:
            return db().execute(
                "SELECT 1 FROM articles_fts WHERE articles_fts MATCH ? LIMIT 1",
                (f'"{term}"*',),
            ).fetchone() is not None
        except Exception:
            return True  # 프로브 실패 시 보수적으로 '있음' 취급(확장 억제)

    grouped: dict[str, list[tuple[int, str]]] = {}
    for r in rows:
        daily, legal, rel = r["daily_term"], r["legal_term"], r["relation"]
        if rel not in prio or len(daily) < 2 or len(legal) < 2 or daily == legal:
            continue
        # 숫자뿐인 일상용어('112'→신고 등)는 질의 속 아무 숫자에나 부분일치해 오발화 → 제외.
        if not re.search(r"[가-힣a-z]", daily):
            continue
        # 코퍼스에 없는 일상어(진짜 어휘 불일치)만 확장 대상으로 채택.
        if _in_corpus(daily):
            continue
        grouped.setdefault(daily, []).append((prio[rel], legal))
    mapping: dict[str, list[str]] = {}
    for daily, pairs in grouped.items():
        seen: set[str] = set()
        ordered: list[str] = []
        for _, legal in sorted(pairs):  # 동의어 → 연관어 순
            if legal not in seen:
                seen.add(legal)
                ordered.append(legal)
        mapping[daily] = ordered
    # 긴(=더 구체적인) 일상용어가 확장 슬롯을 먼저 가져가도록 길이 내림차순 키 목록을 함께 캐시.
    keys = tuple(sorted(mapping, key=len, reverse=True))
    return mapping, keys


def _expand_query_for_fts(query: str) -> str:
    """질의에 포함된 일상어 키워드에 대응하는 법령 표제어를 덧붙인 FTS용 질의 반환."""
    q_lower = query.lower()
    extra = [terms for key, terms in _FTS_SYNONYMS.items() if key in q_lower]
    # term_map 보충: 질의에 등장한 일상용어의 법령용어를 최대 _TERM_MAP_MAX_ADD 개 추가.
    # 하드코딩 확장으로 이미 질의에 들어간 토큰·질의 원문에 있는 용어는 중복 추가하지 않는다.
    mapping, keys = _term_map()
    if mapping:
        present = q_lower + " " + " ".join(extra).lower()
        added = 0
        matched: list[str] = []  # 이미 매칭된(더 긴) 일상용어 — 그 부분문자열 키는 중복 발화로 보고 스킵
        for daily in keys:  # 길이 긴(구체적) 일상용어부터
            if added >= _TERM_MAP_MAX_ADD:
                break
            if daily not in q_lower:
                continue
            # 예: '진료기록부'가 이미 매칭됐으면 그 안의 '진료'는 별도 매칭으로 치지 않는다(노이즈 가드).
            if any(daily in m for m in matched):
                continue
            matched.append(daily)
            for legal in mapping[daily]:
                if added >= _TERM_MAP_MAX_ADD:
                    break
                if legal in present:
                    continue
                extra.append(legal)
                present += " " + legal
                added += 1
    return f"{query} {' '.join(extra)}" if extra else query


# ---------- 임베딩 ----------
def embed_query(text: str) -> list[float] | None:
    """OpenAI 임베딩. 키 없으면 None → 벡터검색 건너뜀."""
    if not OPENAI_API_KEY:
        return None
    try:
        from app.llm import openai_client  # 공유 클라이언트 재사용(매 호출 재생성 방지)

        resp = openai_client().embeddings.create(
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
        from app.llm import openai_client  # 공유 클라이언트 재사용(매 호출 재생성 방지)

        resp = openai_client().embeddings.create(
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
        if STATUTE_CORE_ONLY:
            # 핵심 법령만 BM25 순위에 올린다 — 최종 단계에서 어차피 걸러질 비핵심 조문
            # (부처 지침·훈령의 개보법 복제 조문 등)이 FTS 상위 랭크를 도배해 진짜 조문의
            # RRF 점수를 희석시키는 문제 보정(실측: 개보법 제23조가 지침 복제본 73건에
            # 밀려 rank 74 → 필터 후 최상위). 벡터 채널은 건드리지 않는다 — 벡터까지
            # 핵심 법령으로 채우면 statute가 top-k를 독식해 가이드라인·결정문이 밀려남(실측 회귀).
            rows = conn.execute(
                """SELECT a.id FROM articles_fts f JOIN articles a ON a.id = f.rowid
                   JOIN statutes s ON s.id = a.statute_id
                   WHERE articles_fts MATCH ? AND s.trust_grade = ?
                   ORDER BY bm25(articles_fts) LIMIT ?""",
                (expr, CORE_TRUST_GRADE, limit),
            ).fetchall()
        else:
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
    pool = max(top_k * 3, RAG_POOL)

    fts = fts_search(_expand_query_for_fts(query), types, pool)
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

    # 재랭킹: 핵심 법령(trust_grade='법령')을 제목 유사 행정규칙 위로 끌어올리고(가산),
    # 지역·특정기관용 자치법규(조례·의회규칙)는 무관 노이즈이므로 점수를 낮춘다(감점).
    # statute 키의 sid는 article id → articles JOIN statutes 로 등급·종류 1회 조회.
    if STATUTE_BOOST != 1.0 or (STATUTE_PENALTY != 1.0 and STATUTE_PENALTY_KINDS):
        art_ids = [sid for (st, sid) in scores if st == "statute"]
        if art_ids:
            ph = ",".join("?" * len(art_ids))
            meta = {
                r["id"]: (r["trust_grade"], r["kind"])
                for r in db().execute(
                    f"""SELECT a.id, s.trust_grade, s.kind
                        FROM articles a JOIN statutes s ON s.id = a.statute_id
                        WHERE a.id IN ({ph})""",
                    art_ids,
                )
            }
            for key in scores:
                if key[0] != "statute":
                    continue
                m = meta.get(key[1])
                if not m:
                    continue
                trust_grade, kind = m
                if trust_grade == "법령":
                    scores[key] *= STATUTE_BOOST
                elif kind in STATUTE_PENALTY_KINDS:
                    scores[key] *= STATUTE_PENALTY

    ordered = sorted(scores.items(), key=lambda x: -x[1])

    _cap = STATUTE_TITLE_CAP
    title_count: dict[str, int] = {}

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
        # 코퍼스 하드필터: statute 근거는 핵심 법령(4개 법+시행령/규칙)만 — 조례·행정규칙 배제.
        # 판례·가이드라인·해석례(case/doc)는 그대로 유지.
        if STATUTE_CORE_ONLY and stype == "statute" and hit.trust_grade != CORE_TRUST_GRADE:
            continue
        if as_of_c and hit.effective_from and hit.effective_from > as_of_c:
            continue  # 시점 필터: as_of 이후 발효/선고 자료 제외
        # 조문명 다양성 캡: 같은 제목 statute 히트가 후보를 독식하지 않게 제한
        # (제목 동일 행정규칙 다수가 핵심 법령을 밀어내는 문제 보정).
        if _cap and stype == "statute":
            t = re.sub(r"[^가-힣A-Za-z0-9]", "", hit.title or "")
            if t:
                if title_count.get(t, 0) >= _cap:
                    continue
                title_count[t] = title_count.get(t, 0) + 1
        hits.append(hit)
        if len(hits) >= top_k:
            break
    return hits, method


def search_statutes(q: str = "", kind: str = "", trust_grade: str = "",
                    as_of: str = "", limit: int = 20) -> list[dict]:
    """법령/행정규칙 검색 (조문 FTS → 법령 단위). 라우터·MCP 공용."""
    conn = db()
    params: list = []
    # q에 유효 토큰이 없으면(특수문자·1글자 등) FTS MATCH 빈식 → SQLite 오류(500).
    # fts_search와 동일하게 빈 식이면 FTS 분기를 타지 않고 전체(필터만) 검색으로 폴백.
    expr = _fts_match_expr(q) if q else ""
    if expr:
        sql = """SELECT DISTINCT s.id, s.law_id, s.name, s.kind, s.trust_grade,
                        s.effective_from, s.source_url
                 FROM articles_fts f JOIN articles a ON a.id = f.rowid
                 JOIN statutes s ON s.id = a.statute_id
                 WHERE articles_fts MATCH ?"""
        params.append(expr)
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
