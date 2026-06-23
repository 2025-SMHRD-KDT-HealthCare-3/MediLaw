from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from app.core.response import error_response
from app.routers import (
    admin_router,
    ai_ad_copy_router,
    ai_router,
    auth_router,
    chat_router,
    evidence_router,
    room_router,
    summary_router,
    user_router,
    verification_router,
)

setup_logging()
settings.validate_runtime_settings()

app = FastAPI(title="MediLaw AI Backend", version="0.1.0")
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/api")
app.include_router(user_router.router, prefix="/api")
app.include_router(room_router.router, prefix="/api")
app.include_router(chat_router.router, prefix="/api")
app.include_router(ai_router.router, prefix="/api")
app.include_router(evidence_router.router, prefix="/api")
app.include_router(verification_router.router, prefix="/api")
app.include_router(ai_ad_copy_router.router, prefix="/api")
app.include_router(summary_router.router, prefix="/api")
app.include_router(admin_router.router, prefix="/api")


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(str(exc.detail), code=str(exc.status_code)),
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=error_response(str(exc.detail), code="429"),
    )


@app.get("/server-check")
def server_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/server-check")
def api_server_check() -> dict:
    return {"success": True, "message": "success", "data": {"status": "ok"}}
