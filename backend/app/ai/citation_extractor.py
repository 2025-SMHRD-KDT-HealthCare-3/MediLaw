def extract_citations_stub(answer_text: str) -> list[dict]:
    # TODO: parse law name, article number, and citation spans from generated answer.
    return [
        {
            "law_name": "의료법",
            "article_no": "제56조",
            "core_basis": "AI 답변에서 추출한 mock 핵심 근거입니다.",
            "source_url": "https://www.law.go.kr/",
        }
    ]
