"""연관 판례 그래프 API. POST /v1/related-graph : '더보기' 시각화용 노드 그래프.

기존 연관 판례(텍스트 리스트)를 더보기로 펼칠 때 호출 → 입력 문구를 위반 쟁점별
판례·제재 그래프로 구조화해 반환(챗봇 답변·PDF 검토 finding 공용).
"""
from fastapi import APIRouter, Depends

from app.auth import require_api_key
from app.related_graph import build_related_graph
from app.schemas import RelatedGraphRequest, RelatedGraphResponse

router = APIRouter(prefix="/v1", tags=["RAG API"])


@router.post(
    "/related-graph",
    response_model=RelatedGraphResponse,
    dependencies=[Depends(require_api_key)],
)
def related_graph(req: RelatedGraphRequest):
    """입력 문구 → 연관 판례 그래프(root → 쟁점 → 판례·제재). gpt-5.5 가공 + Citation Firewall."""
    return build_related_graph(
        req.text, lang=req.lang, as_of=req.as_of, top_k=req.top_k, seeds=req.seeds
    )
