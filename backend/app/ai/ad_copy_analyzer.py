def analyze_ad_copy_stub(input_text: str, input_language: str | None = None) -> dict[str, str | None]:
    # TODO: replace with policy-aware AI analysis and law citation verification.
    return {
        "english_text": None if input_language != "en" else input_text,
        "translated_text": None,
        "risky_expression": "최고, 완치 등 과장 표현 여부를 확인해야 합니다.",
        "legal_basis": '{"law_name":"의료법","article_no":"제56조","summary":"의료광고 금지 표현 검토"}',
        "revision_recomm": "단정적 치료 효과 표현을 완화하세요.",
        "alternative_text": "환자 상태에 따라 치료 결과가 달라질 수 있으며, 전문의 상담 후 결정하세요.",
    }
