def retrieve_sources_stub(query: str) -> list[dict]:
    # TODO: connect vector store or temporary retrieval layer. Do not store law full text in MySQL.
    return [
        {
            "law_name": "의료법",
            "article_no": "제56조",
            "core_basis": f"'{query}'에 대한 mock RAG 핵심 근거입니다.",
            "source_url": "https://www.law.go.kr/",
        }
    ]
