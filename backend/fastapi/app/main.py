"""MediLaw API — lawbot.org 4대 기능 구현.

1) RAG API          POST /v1/retrieve        조문·판례·해석례 통합 하이브리드 검색
2) Source Pack      POST /v1/source-pack     LLM 인용용 근거 마크다운 번들
3) Citation Firewall POST /v1/verify         AI 인용 검증(존재·조문·판례·시점)
4) MCP Server       mcp/server.py            Claude/Cursor/ChatGPT 에이전트 도구
"""
import os

from fastapi import FastAPI

from app.config import API_KEYS, DB_PATH
from app.db import has_embeddings, vec_loaded
from app.routers import chat, documents, laws, retrieve, source_pack, verify

# 호출 구조: React(브라우저) → Node(메인 백엔드) → 이 FastAPI(AI). 프론트는 이 서버를 직접
# 호출하지 않고 Node가 서버-서버로 호출하므로 CORS(브라우저 전용 규칙)는 불필요.

app = FastAPI(
    title="MediLaw API — 의료법 RAG · Source Pack · Citation Firewall",
    version="1.0.0",
    description="lawbot.org 호환 의료법 컴플라이언스 API (의료법·개인정보보호법·생명윤리법·정보통신망법)",
)

app.include_router(retrieve.router)
app.include_router(source_pack.router)
app.include_router(verify.router)
app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(laws.router)

# 기능 4 — MCP Server 를 같은 uvicorn 위에 마운트(/mcp SSE).
# LLM(Claude/Cursor)이 별도 프로세스 없이 이 URL로 바로 도구를 사용.
# mcp 패키지 미설치 시 웹 API는 그대로 동작(MCP만 비활성).
MCP_MOUNTED = False
try:
    from mcp_server.server import mcp as _mcp

    app.mount("/mcp", _mcp.sse_app())
    MCP_MOUNTED = True
except Exception as _e:  # noqa: BLE001
    import logging

    logging.getLogger("uvicorn.error").warning(
        "MCP 마운트 생략(웹 API는 정상): %s", _e
    )


@app.get("/health")
def health():
    try:
        from app import lawapi
        from app.db import db

        revisions_ready = lawapi.has_revisions(db())
    except Exception:  # noqa: BLE001
        revisions_ready = False
    return {
        "status": "ok",
        "db_path": DB_PATH,
        "db_exists": os.path.exists(DB_PATH),
        "db_size_mb": round(os.path.getsize(DB_PATH) / 1024 / 1024, 1)
        if os.path.exists(DB_PATH)
        else 0,
        "embeddings_ready": has_embeddings(),
        "vec_extension": vec_loaded(),
        "revisions_ready": revisions_ready,
        "auth_enabled": bool(API_KEYS),
        "mcp_mounted": MCP_MOUNTED,
    }


@app.get("/", include_in_schema=False)
def index():
    return {
        "service": "MediLaw API",
        "features": {
            "chat": "POST /chat , POST /chat/stream(SSE)",
            "document_review": "POST /documents/review (PDF 업로드 위험 검토)",
            "chat_checklist": "POST /chat/checklist (대화 종료 후 법적 대응 체크리스트)",
            "rag": "POST /v1/retrieve",
            "source_pack": "POST /v1/source-pack",
            "citation_firewall": "POST /v1/verify",
            "statutes_search": "GET /v1/statutes/search",
            "law_revisions": "GET /v1/laws/revisions , GET /v1/laws/{law_id}/revisions , GET /v1/laws/diff",
            "mcp_server": "/mcp/sse (마운트됨)" if MCP_MOUNTED else "python -m mcp_server.server (stdio)",
        },
        "docs": "/docs",
    }
