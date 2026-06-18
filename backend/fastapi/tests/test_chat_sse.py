"""챗봇 /chat/stream SSE 이벤트 포맷·순서 회귀 테스트.

두 계층:
  (A) 결정론적 — 도메인 밖(Tier 3) 거절 스트림은 규칙으로 잡혀 LLM 불필요.
      gen_refuse()가 sources(빈)→token(거절메시지)→done 순으로 보낸다. 키 없이 항상 실행.
  (B) LLM 필요 — 정상 도메인 질문의 토큰 스트림. OPENAI_API_KEY 있을 때만(가드로 skip).

SSE 포맷: 각 이벤트는 'data: {json}\\n\\n'. 이벤트 순서:
  sources → token... → done   (정상/거절 공통)
  오류 시 token 자리에서 error.

실행:
  pytest tests/test_chat_sse.py
  python tests/test_chat_sse.py          # 단독 러너(요약 출력)
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers import chat  # noqa: E402
from app.schemas import ChatRequest  # noqa: E402


# ── SSE 수집/파싱 헬퍼 ────────────────────────────────────────────────────────
async def _collect(resp):
    """StreamingResponse.body_iterator 를 끝까지 모아 raw 문자열로."""
    out = []
    async for chunk in resp.body_iterator:
        out.append(chunk.decode() if isinstance(chunk, (bytes, bytearray)) else chunk)
    return "".join(out)


def _parse_sse(raw):
    """raw SSE 문자열 → 이벤트 dict 리스트.

    빈 줄 무시, 'data: ' 접두 제거 후 json.loads. (파싱 실패 시 예외 전파 — 테스트가 잡음)
    """
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        assert block.startswith("data: "), f"SSE 라인이 'data: '로 시작하지 않음: {block!r}"
        events.append(json.loads(block[len("data: "):]))
    return events


def _stream_events(req):
    """chat_stream(req) 스트림을 동기적으로 수집·파싱해 이벤트 리스트 반환."""
    raw = asyncio.run(_collect(chat.chat_stream(req)))
    return raw, _parse_sse(raw)


# ── (A) 결정론적 — 도메인 밖 거절 스트림 (LLM 불필요) ─────────────────────────
def test_refuse_stream_event_order_and_content():
    """'오늘 서울 날씨' → sources(빈)→token(거절)→done 순서·내용 검증."""
    raw, events = _stream_events(ChatRequest(question="오늘 서울 날씨 알려줘"))
    assert events, "이벤트가 하나도 없음"

    # 첫 이벤트: sources
    first = events[0]
    assert first["type"] == "sources", f"첫 이벤트 type={first['type']!r}, expected 'sources'"
    assert first["method"] == "none", f"method={first['method']!r}, expected 'none'"
    assert first["sources"] == [], f"sources={first['sources']!r}, expected []"
    assert first["lang"] == "ko", f"lang={first['lang']!r}, expected 'ko'"

    # 마지막 이벤트: done + citation_check.summary 존재
    last = events[-1]
    assert last["type"] == "done", f"마지막 이벤트 type={last['type']!r}, expected 'done'"
    assert "citation_check" in last, "done 이벤트에 citation_check 없음"
    assert "summary" in last["citation_check"], "citation_check 에 summary 없음"

    # 중간 token 이벤트들을 이으면 거절 메시지와 정확히 일치
    tokens = [e for e in events if e["type"] == "token"]
    assert tokens, "token 이벤트가 없음"
    assert "".join(t["text"] for t in tokens) == chat._OUT_OF_DOMAIN, "거절 메시지 불일치"

    # 타입 순서: sources 가 처음, done 이 마지막, 그 사이는 token
    types = [e["type"] for e in events]
    assert types[0] == "sources" and types[-1] == "done", f"순서 위반: {types}"
    assert all(t == "token" for t in types[1:-1]), f"중간 이벤트가 token 이 아님: {types}"


def test_refuse_stream_all_lines_valid_json():
    """모든 data: 라인이 유효한 JSON 인지(_parse_sse 가 실패 없이 통과)."""
    raw, events = _stream_events(ChatRequest(question="오늘 서울 날씨 알려줘"))
    # raw 의 각 비어있지 않은 블록이 'data: '로 시작하고 파싱 가능해야 함.
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        assert block.startswith("data: "), f"'data: ' 접두 없음: {block!r}"
        json.loads(block[len("data: "):])  # 실패 시 예외 → 테스트 실패
    assert len(events) >= 3, f"이벤트 수 {len(events)} < 3 (sources/token/done)"


# ── (B) LLM 필요 — 정상 도메인 질문 스트림 ───────────────────────────────────
def test_in_domain_stream():
    """정상 도메인 질문 → sources(method hybrid/fts)→token...→done.summary 키 검증."""
    if not os.environ.get("OPENAI_API_KEY"):
        import pytest

        pytest.skip("OPENAI_API_KEY 없음 — 도메인 스트림 LLM 검증 생략")

    raw, events = _stream_events(ChatRequest(question="무면허 의료행위 처벌은?"))
    assert events, "이벤트가 하나도 없음"

    first = events[0]
    assert first["type"] == "sources", f"첫 이벤트 type={first['type']!r}, expected 'sources'"
    assert first["method"] in ("hybrid", "fts"), f"method={first['method']!r}"

    # 에러 이벤트면(LLM 불안정 등) 단언 스킵.
    if any(e["type"] == "error" for e in events):
        import pytest

        pytest.skip("스트림에 error 이벤트 — LLM 불안정으로 skip")

    tokens = [e for e in events if e["type"] == "token"]
    assert tokens, "token 이벤트가 1개 이상이어야 함"

    last = events[-1]
    assert last["type"] == "done", f"마지막 이벤트 type={last['type']!r}, expected 'done'"
    summary = last["citation_check"]["summary"]
    for key in ("total", "avg_score", "worst_status", "min_score"):
        assert key in summary, f"citation_check.summary 에 {key!r} 키 없음"


# ── 단독 러너(요약 출력) ──────────────────────────────────────────────────────
def _run():
    passed = total = 0

    def _check(label, fn):
        nonlocal passed, total
        total += 1
        try:
            fn()
            passed += 1
            print(f"  [OK ] {label}")
        except AssertionError as e:
            print(f"  [FAIL] {label} :: {e}")

    print("── (A) 결정론적 거절 스트림(LLM 불필요) ──")
    _check("sources→token→done 순서·내용", test_refuse_stream_event_order_and_content)
    _check("모든 data: 라인 유효 JSON", test_refuse_stream_all_lines_valid_json)
    print(f"\n  결정론 {passed}/{total} passed")

    print("\n── (B) 도메인 스트림(LLM) ──")
    if not os.environ.get("OPENAI_API_KEY"):
        print("  (OPENAI_API_KEY 없음 — 도메인 스트림 검증 생략)")
        return
    try:
        test_in_domain_stream()
        print("  [OK ] 도메인 스트림 sources→token→done")
    except AssertionError as e:
        print(f"  [FAIL] 도메인 스트림 :: {e}")


if __name__ == "__main__":
    _run()
