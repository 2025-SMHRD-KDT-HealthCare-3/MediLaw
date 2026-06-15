def search_law_basis_stub(query: str) -> list[dict]:
    # TODO: replace with external law API call. Do not persist raw API responses to MySQL.
    return [
        {
            "law_name": "의료법",
            "article_no": "제56조",
            "core_basis": f"'{query}' 관련 의료광고 제한 여부를 검토해야 합니다.",
            "source_url": "https://www.law.go.kr/",
        }
    ]
