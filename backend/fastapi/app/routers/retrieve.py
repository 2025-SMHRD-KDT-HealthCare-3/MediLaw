"""기능 1 — RAG API. POST /v1/retrieve : 조문·판례·해석례 통합(하이브리드) 검색.

추가로 lawbot 호환 GET /v1/statutes/search 제공.
"""
from fastapi import APIRouter, Depends, Query

from app.auth import require_api_key
from app.rag import hybrid_search
from app.schemas import RetrieveRequest, RetrieveResponse

router = APIRouter(prefix="/v1", tags=["RAG API"])


@router.post("/retrieve", response_model=RetrieveResponse, dependencies=[Depends(require_api_key)])
def retrieve(req: RetrieveRequest):
    """질의 → 하이브리드(FTS+벡터) 융합 → clause-level 통합 결과. as_of 시점 조회 지원."""
    hits, method = hybrid_search(
        req.query, req.source_types, top_k=req.top_k, as_of=req.as_of
    )
    return RetrieveResponse(output=hits, as_of=req.as_of, method=method)


@router.get("/statutes/search", dependencies=[Depends(require_api_key)])
def statutes_search(
    q: str = Query("", description="법령명/조문 내용"),
    kind: str = Query("", description="종류: 법률|대통령령|고시|예규 ..."),
    trust_grade: str = Query("", description="신뢰등급: 법령|A|B"),
    as_of: str = Query("", description="시점 조회 YYYY-MM-DD"),
    limit: int = Query(20, ge=1, le=100),
):
    """lawbot 호환 법령 검색 (조문 FTS → 법령 단위)."""
    from app.rag import search_statutes

    items = search_statutes(q=q, kind=kind, trust_grade=trust_grade, as_of=as_of, limit=limit)
    return {"output": items, "as_of": as_of or None, "source": "medilaw.db"}
