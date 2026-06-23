"""기능 2 — Source Pack. POST /v1/source-pack :
질의 → 관련 법령/판례/해석례를 LLM 인용용 마크다운 번들로 생성.
"""
from fastapi import APIRouter, Depends

from app.auth import require_api_key
from app.rag import hybrid_search
from app.schemas import Citation, SourcePackRequest, SourcePackResponse

router = APIRouter(prefix="/v1", tags=["Source Pack"])

_TYPE_LABEL = {"statute": "법령·조문", "case": "판례", "interpretation": "법령해석례"}


@router.post("/source-pack", response_model=SourcePackResponse, dependencies=[Depends(require_api_key)])
def source_pack(req: SourcePackRequest):
    """검색 결과를 출처·인용라벨이 달린 마크다운으로 패키징 (LLM이 그대로 인용 가능)."""
    hits, _ = hybrid_search(
        req.query, req.source_types, top_k=req.max_items, as_of=req.as_of
    )

    lines = [f"# 근거 자료 (Source Pack)", f"> 질의: {req.query}"]
    if req.as_of:
        lines.append(f"> 기준시점(as_of): {req.as_of}")
    lines.append("")

    citations: list[Citation] = []
    for i, h in enumerate(hits, 1):
        cid = f"[{i}]"
        lines.append(f"## {cid} {h.label}")
        meta = [_TYPE_LABEL.get(h.source_type, h.source_type)]
        if h.trust_grade:
            meta.append(f"신뢰등급: {h.trust_grade}")
        if h.effective_from:
            meta.append(f"시행/선고: {h.effective_from}")
        lines.append(f"- {' · '.join(meta)}")
        if h.source_url:
            lines.append(f"- 출처: {h.source_url}")
        lines.append("")
        lines.append(h.snippet.strip())
        lines.append("")
        citations.append(
            Citation(
                label=h.label, source_type=h.source_type, source_id=h.source_id,
                source_url=h.source_url, trust_grade=h.trust_grade,
            )
        )

    if not hits:
        lines.append("_관련 근거를 찾지 못했습니다. 추측하지 말고 자료 없음을 알리세요._")

    lines.append("---")
    lines.append(
        "위 번호 인용(예: [1])만 근거로 사용하고, 목록에 없는 조문·판례는 인용하지 마세요."
    )

    return SourcePackResponse(
        output="\n".join(lines), citations=citations, as_of=req.as_of
    )
