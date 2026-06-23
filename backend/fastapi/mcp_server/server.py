"""기능 4 — MCP Server.

Claude / Cursor / ChatGPT 에 MediLaw 검색·검증을 에이전트 도구로 노출.
앱 내부 함수를 직접 호출(HTTP 왕복 없음). 같은 `mcp` 인스턴스를 두 방식으로 제공:

[A] 마운트(권장) — uvicorn 한 서버에 포함. app/main.py 가 `mcp.sse_app()` 를 /mcp 로 마운트.
    LLM은 별도 프로세스 없이 URL(.../mcp/sse)로 바로 연결. 로컬·배포 동일.
    Cursor / Claude 원격 MCP 등록 예시:
        { "mcpServers": { "medilaw": { "url": "http://localhost:8077/mcp/sse" } } }

[B] stdio(로컬 단독) — Claude Desktop 이 자식 프로세스로 실행:
    DB_PATH=data/medilaw.db python3 -m mcp_server.server
        { "mcpServers": { "medilaw": {
            "command": "python3", "args": ["-m", "mcp_server.server"],
            "cwd": "/home/user1/MediLaw/backend/fastapi",
            "env": {"DB_PATH": "data/medilaw.db", "OPENAI_API_KEY": "..."} } } }
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app.citations import extract_and_verify  # noqa: E402
from app.rag import hybrid_search, search_statutes  # noqa: E402
from app.routers.source_pack import _TYPE_LABEL  # noqa: E402

mcp = FastMCP("medilaw")


@mcp.tool()
def retrieve(query: str, top_k: int = 8, as_of: str = "") -> list[dict]:
    """의료 4법령 조문·판례를 하이브리드 검색해 관련 근거를 반환.

    query: 자연어 질의. as_of: 'YYYY-MM-DD' 시점 조회(선택).
    """
    hits, _ = hybrid_search(query, top_k=top_k, as_of=as_of or None)
    return [h.model_dump() for h in hits]


@mcp.tool()
def source_pack(query: str, max_items: int = 8, as_of: str = "") -> str:
    """질의에 대한 LLM 인용용 근거 마크다운 번들을 생성해 반환."""
    hits, _ = hybrid_search(query, top_k=max_items, as_of=as_of or None)
    lines = [f"# 근거 자료\n> 질의: {query}\n"]
    for i, h in enumerate(hits, 1):
        lines.append(f"## [{i}] {h.label}")
        lines.append(f"- {_TYPE_LABEL.get(h.source_type, h.source_type)} · 신뢰등급 {h.trust_grade}")
        if h.source_url:
            lines.append(f"- 출처: {h.source_url}")
        lines.append(f"\n{h.snippet.strip()}\n")
    if not hits:
        lines.append("_관련 근거 없음 — 추측 금지._")
    return "\n".join(lines)


@mcp.tool()
def verify(text: str, as_of: str = "") -> dict:
    """LLM 답변 원문의 법령·판례 인용을 DB와 대조 검증(환각/시점오류 차단)."""
    results = extract_and_verify(text, as_of or None)
    verified = sum(1 for r in results if r.verified)
    return {
        "output": [r.model_dump() for r in results],
        "summary": {"total": len(results), "verified": verified, "failed": len(results) - verified},
    }


@mcp.tool()
def statutes_search(q: str = "", kind: str = "", trust_grade: str = "",
                    as_of: str = "", limit: int = 20) -> list[dict]:
    """법령·행정규칙을 법령 단위로 검색(조문 FTS 기반). kind=법률|대통령령|고시 등, as_of='YYYY-MM-DD' 시점."""
    return search_statutes(q=q, kind=kind, trust_grade=trust_grade, as_of=as_of, limit=limit)


if __name__ == "__main__":
    mcp.run()
