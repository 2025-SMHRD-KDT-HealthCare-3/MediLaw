def generate_mock_answer(question: str, sources: list[dict]) -> str:
    # TODO: replace with OpenAI client call after prompt and safety policy are finalized.
    source_hint = sources[0]["law_name"] if sources else "관련 법령"
    return f"[MOCK AI ANSWER] '{question}'에 대해 {source_hint} 기준으로 검토한 예시 답변입니다."
