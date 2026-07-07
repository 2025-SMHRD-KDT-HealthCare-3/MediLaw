import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.main import app
from app.models import AiAdCopy, Chat, Evidence, Room, Summary, User, Verification  # noqa: F401
from app.services import hms_client

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def reset_rate_limiter() -> None:
    storage = getattr(getattr(limiter, "limiter", None), "storage", None)
    reset = getattr(storage, "reset", None)
    if callable(reset):
        reset()
        return

    bucket = getattr(storage, "storage", None)
    if hasattr(bucket, "clear"):
        bucket.clear()


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def reset_database():
    reset_rate_limiter()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mock_hms(monkeypatch):
    def fake_post_json(path: str, payload: dict, *, timeout: int = 120) -> dict:
        if path == "/chat":
            return {
                "answer": "의료법 제27조에 따른 답변입니다.",
                "sources": [
                    {
                        "label": "의료법 제27조",
                        "snippet": "의료인이 아니면 의료행위를 할 수 없습니다.",
                        "source_url": "https://example.test/law",
                    }
                ],
                "citation_check": {
                    "output": [
                        {
                            "raw": "의료법 제27조",
                            "matched_label": "의료법 제27조",
                            "exists": True,
                            "clause_accurate": True,
                            "valid_as_of": True,
                            "verified": True,
                            "trust_score": 82,
                            "status": "확인",
                            "note": "테스트 검증",
                        }
                    ],
                    "summary": {"total": 1, "verified": 1, "failed": 0, "avg_score": 82},
                },
            }
        if path == "/v1/verify":
            return {
                "output": [
                    {
                        "raw": "의료법 제27조",
                        "matched_label": "의료법 제27조",
                        "exists": True,
                        "clause_accurate": True,
                        "valid_as_of": True,
                        "verified": True,
                        "trust_score": 91,
                        "status": "확인",
                        "note": "재검증 완료",
                    }
                ],
                "summary": {"total": 1, "verified": 1, "failed": 0, "avg_score": 91},
            }
        if path == "/chat/checklist":
            return {
                "checklist": [
                    {
                        "id": "item-1",
                        "title": "면허 범위 확인",
                        "reason": "무면허 의료행위 여부 확인",
                        "status": "todo",
                        "citations": [],
                    }
                ],
                "checklist_summary": {"total": 1, "todo": 1, "ok": 0, "risk": 0, "na": 0},
                "search_queries": ["의료법 무면허 의료행위"],
                "citation_check": {
                    "output": [],
                    "summary": {"total": 0, "verified": 0, "failed": 0, "avg_score": 0},
                },
            }
        raise AssertionError(f"unexpected HMS JSON path: {path}")

    def fake_post_multipart(
        path: str,
        *,
        data: dict | None = None,
        files: dict | None = None,
        timeout: int = 180,
    ) -> dict:
        assert path in {"/documents/review", "/documents/review/en"}
        original_text = (data or {}).get("text") or "uploaded.pdf"
        return {
            "original_text": original_text,
            "revised_text": "의료광고 수정 권고 문구입니다.",
            "findings": [
                {
                    "segment_text": original_text,
                    "risk_level": "high",
                    "issue": "과장 표현",
                    "suggestion": "객관적 표현으로 수정",
                    "citations": [
                        {
                            "label": "의료법 제56조",
                            "snippet": "거짓 또는 과장된 의료광고 금지",
                            "source_url": "https://example.test/ad",
                        }
                    ],
                }
            ],
            "checklist": [],
            "checklist_summary": {"total": 0},
            "citation_check": {
                "output": [
                    {
                        "raw": "의료법 제56조",
                        "matched_label": "의료법 제56조",
                        "exists": True,
                        "clause_accurate": True,
                        "valid_as_of": True,
                        "verified": True,
                        "trust_score": 88,
                        "status": "확인",
                    }
                ],
                "summary": {"total": 1, "verified": 1, "failed": 0, "avg_score": 88},
            },
        }

    monkeypatch.setattr(hms_client, "post_json", fake_post_json)
    monkeypatch.setattr(hms_client, "post_multipart", fake_post_multipart)


def signup_and_login(client: TestClient, login_id: str = "user1", role: str = "USER") -> str:
    payload = {
        "login_id": login_id,
        "password": "password123",
        "name": "Test User",
        "email": f"{login_id}@example.com",
    }
    response = client.post("/api/auth/signup", json=payload)
    assert response.status_code == 200

    if role == "ADMIN":
        db = TestingSessionLocal()
        try:
            user = db.query(User).filter(User.login_id == login_id).one()
            user.role = "ADMIN"
            db.commit()
        finally:
            db.close()

    login_response = client.post(
        "/api/auth/login",
        json={"login_id": login_id, "password": "password123"},
    )
    assert login_response.status_code == 200
    return login_response.json()["data"]["access_token"]
