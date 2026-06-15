import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import AiAdCopy, Chat, Evidence, Room, Summary, User, Verification  # noqa: F401

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


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
