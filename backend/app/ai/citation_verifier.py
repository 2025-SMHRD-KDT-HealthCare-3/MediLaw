def verify_citation_stub(citation: dict) -> dict:
    # TODO: verify article existence/effective date through external law API only.
    return {
        "law_name": citation.get("law_name"),
        "article_no": citation.get("article_no"),
        "article_exists": True,
        "content_matches": True,
        "effective_date_valid": True,
        "verification_status": "CONFIRMED",
        "confidence_score": 95.0,
        "verification_reason": "mock 검증 결과입니다. 실제 법령 API 검증은 아직 연결되지 않았습니다.",
    }
