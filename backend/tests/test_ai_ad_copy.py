from conftest import signup_and_login
from app.services import hms_client


def test_ai_ad_copy_create_and_list(client, mock_hms):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/api/ai-ad-copies",
        json={"input_language": "en", "input_text": "Best hospital cure guaranteed"},
        headers=headers,
    )
    assert create_response.status_code == 200
    data = create_response.json()["data"]
    assert data["input_text"] == "Best hospital cure guaranteed"
    assert data["revision_recomm"] == "의료광고 수정 권고 문구입니다."
    assert "과장 표현" in data["risky_expression"]
    assert data["findings"][0]["issue"] == "과장 표현"
    assert data["checklist"] == []
    assert data["checklist_summary"] == {"total": 0}

    list_response = client.get("/api/ai-ad-copies", headers=headers)
    assert list_response.status_code == 200
    list_data = list_response.json()["data"]
    assert len(list_data) == 1
    assert list_data[0]["findings"][0]["issue"] == "과장 표현"


def test_ad_review_returns_structured_ai_copy(client, mock_hms):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/ai-ad-copies/ad-review",
        data={"text": "Best hospital cure guaranteed"},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    ai_copy = data["ai_copy"]
    assert ai_copy["input_text"] == "Best hospital cure guaranteed"
    assert ai_copy["findings"][0]["issue"] == "과장 표현"
    assert ai_copy["checklist"] == []
    assert ai_copy["checklist_summary"] == {"total": 0}


def test_ad_review_checks_room_before_hms_call(client, monkeypatch):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    def fail_post_multipart(*args, **kwargs):
        raise AssertionError("HMS should not be called for an invalid room")

    monkeypatch.setattr(hms_client, "post_multipart", fail_post_multipart)

    response = client.post(
        "/api/ai-ad-copies/ad-review",
        data={"text": "ad text", "room_id": "999"},
        headers=headers,
    )

    assert response.status_code == 404


def test_ad_review_rejects_invalid_filename(client):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/ai-ad-copies/ad-review",
        files={"file": ("../secret.txt", b"bad", "text/plain")},
        headers=headers,
    )

    assert response.status_code == 422
