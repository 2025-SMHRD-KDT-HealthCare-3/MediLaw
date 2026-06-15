from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app = FastAPI(title="MediLaw AI Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
def api_health_check() -> dict:
    return {"success": True, "message": "success", "data": {"status": "ok"}}
