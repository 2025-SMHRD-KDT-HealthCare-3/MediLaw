"""신 PDF 파이프라인(app/pdf/*) → 기존 `/documents/review` 응답 계약 어댑터.

구 엔드포인트를 신 파이프라인(A→B/C→D→E→F)으로 갈아끼우되, 응답 형태는
기존 `ReviewResponse` 그대로 유지하기 위한 매핑 계층이다.

- PDF 입력: `process_pdf` 로 라우팅·추출·세그먼트·위험판정·치환을 한 번에.
- 텍스트 입력: 단일 블록 Document 를 만들어 segment→review→revise 직접 호출.
- 출력: ReviewResponse(original/revised/segments/findings/citation_check…).

매핑 주의:
- 파이프라인 RiskResult.level 은 "none"|"low"|"med"|"high".
  ReviewFinding.risk_level 은 "high"|"medium"|"low" → "med"→"medium" 으로 정규화.
- level "none" 이거나 risk 없으면 finding 제외(위험만 보고).
- Citation Firewall 유지: findings 텍스트에서 인용을 추출·검증해 citation_check 채움.
- 체크리스트는 신 파이프라인 미생성 → 빈 채로(별도 /chat/checklist 담당).
- LLM 없으면 risk 미채움 → findings 빈 채로라도 정상 반환(graceful).
"""
from __future__ import annotations

from typing import Optional

from app.citations import extract_and_verify, summarize
from app.pdf import classify, revise, review, segment
from app.pdf.pipeline import process_pdf
from app.pdf.schema import Block, Document, Segment
from app.schemas import (
    ChecklistSummary,
    ReviewFinding,
    ReviewResponse,
    VerifyResponse,
)

# 위험으로 간주(=finding 으로 보고)하는 파이프라인 level.
_RISKY_LEVELS = {"low", "med", "high"}
# 파이프라인 level → ReviewResponse risk_level 매핑("med"→"medium").
_LEVEL_MAP = {"high": "high", "med": "medium", "low": "low"}


def _join_text(block_dumps: list[dict]) -> str:
    """blocks_before/after dump 의 text 를 줄바꿈으로 합친다(원문/수정본 복원)."""
    return "\n".join((b.get("text") or "") for b in block_dumps)


def _run_text_pipeline(
    text: str, as_of: Optional[str], top_k: int
) -> tuple[Document, list[Segment], dict]:
    """텍스트 입력 경로 — 단일 블록 Document 로 segment→review→revise 직접 수행."""
    blocks = [Block(id="b1", type="para", text=text, page=1, source="digital")]
    doc_type = classify.classify_doctype(text)
    segs = segment.to_segments(blocks, doc_type)
    segs = review.review_segments(segs, as_of=as_of, top_k=top_k)
    doc = Document(doc_id="text", doc_type=doc_type, page_count=1, blocks=blocks)
    rev = revise.apply_revisions(doc, segs)
    return doc, segs, rev


def _build_findings(segs: list[Segment]) -> list[ReviewFinding]:
    """위험(risk.level in low/med/high) 세그먼트만 ReviewFinding 으로 변환.

    근거 법령명(risk.law)은 issue 뒤에 덧붙인다(citations 는 빈 배열로 — 별도 검증은
    citation_check 가 담당).
    """
    findings: list[ReviewFinding] = []
    for idx, seg in enumerate(segs):
        risk = seg.risk
        if risk is None or risk.level not in _RISKY_LEVELS:
            continue
        issue = risk.reason or ""
        if risk.law:
            laws = ", ".join(risk.law)
            issue = f"{issue} (근거: {laws})" if issue else f"근거: {laws}"
        findings.append(
            ReviewFinding(
                segment_index=idx,
                segment_text=seg.text,
                risk_level=_LEVEL_MAP.get(risk.level, "low"),
                issue=issue,
                suggestion=risk.after or "",
                citations=[],
            )
        )
    return findings


def review_to_response(
    pdf_bytes: bytes | None = None,
    text: str | None = None,
    as_of: Optional[str] = None,
    top_k: int = 4,
    lang: str = "auto",
) -> ReviewResponse:
    """신 PDF 파이프라인 결과를 기존 `ReviewResponse` 계약으로 매핑한다.

    pdf_bytes 또는 text 중 하나는 반드시 주어져야 한다(둘 다 없으면 ValueError).
    """
    # ── 1. 입력 분기 ──────────────────────────────────────────────────────
    if pdf_bytes is not None:
        r = process_pdf(pdf_bytes, as_of=as_of, top_k=top_k)
        doc = r["document"]
        segs = r["segments"]
        rev = r["revisions"]
    elif text is not None:
        doc, segs, rev = _run_text_pipeline(text, as_of, top_k)
    else:
        raise ValueError("pdf_bytes 또는 text 중 하나는 반드시 필요합니다.")

    # ── 2. 매핑 ───────────────────────────────────────────────────────────
    original_text = _join_text(rev["blocks_before"])
    revised_text = _join_text(rev["blocks_after"])
    segments = [s.text for s in segs]
    findings = _build_findings(segs)
    extracted_by = "ocr" if any(b.source == "ocr" for b in doc.blocks) else "text"

    # Citation Firewall — findings 의 issue+suggestion 텍스트에서 인용 추출·검증.
    cite_source = "\n".join(f"{f.issue}\n{f.suggestion}" for f in findings)
    results = extract_and_verify(cite_source, as_of)
    citation_check = VerifyResponse(
        output=results, summary=summarize(results), as_of=as_of
    )

    resp_lang = lang if lang in ("ko", "en") else "ko"

    return ReviewResponse(
        original_text=original_text,
        revised_text=revised_text,
        segments=segments,
        findings=findings,
        checklist=[],
        checklist_summary=ChecklistSummary(),
        extracted_by=extracted_by,
        citation_check=citation_check,
        method="hybrid",
        lang=resp_lang,
        as_of=as_of,
    )


# ──────────────────────────────────────────────────────────────────────────
# 자체 검증 — pytest 함수 + __main__ 러너.
#   텍스트 경로는 LLM(OPENAI_API_KEY) 필요 → 가드. 키 없으면 구조/계약만 확인.
# ──────────────────────────────────────────────────────────────────────────
def test_no_input_raises():
    """pdf_bytes·text 둘 다 없으면 ValueError."""
    try:
        review_to_response()
    except ValueError:
        return
    raise AssertionError("입력 없을 때 ValueError 를 던져야 함")


def test_level_mapping():
    """med→medium 매핑 및 none/risk-없음 제외 검증(LLM 불필요 — risk 직접 주입)."""
    from app.pdf.schema import RiskResult

    segs = [
        Segment(seg_id="s0", block_ids=["b1"], text="위험 high 문구",
                risk=RiskResult(level="high", law=["의료법 제56조"],
                                reason="과장", before="x", after="대안1")),
        Segment(seg_id="s1", block_ids=["b2"], text="위험 med 문구",
                risk=RiskResult(level="med", law=[], reason="주의",
                                before="y", after="대안2")),
        Segment(seg_id="s2", block_ids=["b3"], text="위험 low 문구",
                risk=RiskResult(level="low", reason="경미", before="z", after="대안3")),
        Segment(seg_id="s3", block_ids=["b4"], text="안전 문구",
                risk=RiskResult(level="none")),
        Segment(seg_id="s4", block_ids=["b5"], text="risk 없음", risk=None),
    ]
    findings = _build_findings(segs)
    levels = [f.risk_level for f in findings]
    assert levels == ["high", "medium", "low"], levels
    assert all(f.risk_level in ("high", "medium", "low") for f in findings)
    # none / risk=None 세그먼트는 제외, 인덱스는 원본 위치 유지.
    assert [f.segment_index for f in findings] == [0, 1, 2]
    # 근거 법령명이 issue 에 녹아드는지.
    assert "의료법 제56조" in findings[0].issue


def test_join_text():
    """blocks dump → 줄바꿈 join 으로 원문 복원."""
    dumps = [{"text": "첫줄"}, {"text": "둘째줄"}, {"text": ""}]
    assert _join_text(dumps) == "첫줄\n둘째줄\n"


if __name__ == "__main__":
    import os

    print("=== app.pdf.review_adapter 셀프체크 ===")
    test_no_input_raises()
    test_level_mapping()
    test_join_text()
    print("구조/계약 테스트 PASS (no_input / level_mapping / join_text)")

    if os.environ.get("OPENAI_API_KEY"):
        r = review_to_response(
            text="부작용이 전혀 없는 100% 안전한 시술입니다. 국내 최초 무통증 치료.",
            top_k=4,
        )
        print("original_text:", r.original_text[:40])
        print("revised != original:", r.revised_text != r.original_text)
        print("findings:", len(r.findings),
              "| risk_levels:", [f.risk_level for f in r.findings])
        assert all(f.risk_level in ("high", "medium", "low") for f in r.findings), \
            "risk_level 매핑(med→medium)"
        print("citation_check summary:", r.citation_check.summary.model_dump())
        print("extracted_by:", r.extracted_by)
    else:
        print("OPENAI_API_KEY 없음 — 라이브 텍스트 경로 skip(구조만 검증)")
    print("OK")
