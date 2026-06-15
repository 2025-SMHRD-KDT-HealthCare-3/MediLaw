def generate_summary_stub(chats: list[dict]) -> dict[str, str]:
    # TODO: replace with summarization model and checklist template.
    return {
        "summary": f"총 {len(chats)}개 메시지를 기반으로 생성한 mock 요약입니다.",
        "checklist_item": '["주요 질문 확인", "AI 답변 근거 확인", "관리자 검토 필요 여부 확인"]',
    }
