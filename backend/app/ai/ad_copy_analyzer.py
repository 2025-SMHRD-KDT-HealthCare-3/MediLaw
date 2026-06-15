def analyze_ad_copy_stub(input_text: str, input_language: str | None = None) -> dict[str, str | None]:
    """Return a deterministic mock analysis for ad-copy review."""
    normalized_language = (input_language or "ko").lower()
    return {
        "english_text": input_text if normalized_language == "en" else None,
        "translated_text": input_text if normalized_language == "en" else None,
        "risky_expression": "최고, 완치, 보장 등 단정적이거나 과장된 표현 여부를 확인해야 합니다.",
        "legal_basis": (
            '{"law_name":"의료법","article_no":"제56조",'
            '"summary":"의료광고에서 소비자를 오인하게 할 수 있는 표현은 제한될 수 있습니다."}'
        ),
        "revision_recomm": "치료 효과를 단정하지 말고 개인별 차이와 상담 필요성을 함께 표현하세요.",
        "alternative_text": "환자 상태에 따라 치료 결과가 달라질 수 있으므로 전문의 상담 후 결정하세요.",
    }
