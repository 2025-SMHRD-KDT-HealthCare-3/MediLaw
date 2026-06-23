"""기능 3 — Citation Firewall. POST /v1/verify :
LLM 답변의 법령·판례 인용을 DB와 대조해 환각/폐기/시점오류 차단.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_api_key
from app.citations import extract_and_verify, summarize, verify_inputs
from app.schemas import VerifyRequest, VerifyResponse

router = APIRouter(prefix="/v1", tags=["Citation Firewall"])


@router.post("/verify", response_model=VerifyResponse, dependencies=[Depends(require_api_key)])
def verify(req: VerifyRequest):
    """text(자유서술) 또는 citations(구조화) 중 하나 이상으로 검증."""
    results = []
    if req.text:
        results += extract_and_verify(req.text, req.as_of)
    if req.citations:
        results += verify_inputs(req.citations, req.as_of)
    if not req.text and not req.citations:
        raise HTTPException(400, "text 또는 citations 중 하나는 필요합니다")

    return VerifyResponse(output=results, summary=summarize(results), as_of=req.as_of)
