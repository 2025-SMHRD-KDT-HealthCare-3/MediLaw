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


def test_ai_ad_copy_delete_removes_user_history(client, mock_hms):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/api/ai-ad-copies",
        json={"input_language": "ko", "input_text": "부작용 없는 시술입니다"},
        headers=headers,
    )
    assert create_response.status_code == 200
    ai_copy_id = create_response.json()["data"]["ai_copy_id"]

    delete_response = client.delete(f"/api/ai-ad-copies/{ai_copy_id}", headers=headers)
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "ai ad copy deleted"
    assert delete_response.json()["data"] == {"ai_copy_id": ai_copy_id, "deleted": True}

    get_response = client.get(f"/api/ai-ad-copies/{ai_copy_id}", headers=headers)
    assert get_response.status_code == 404

    list_response = client.get("/api/ai-ad-copies", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["data"] == []


def test_ai_ad_copy_delete_rejects_other_user(client, mock_hms):
    owner_token = signup_and_login(client, login_id="owner")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    create_response = client.post(
        "/api/ai-ad-copies",
        json={"input_language": "ko", "input_text": "부작용 없는 시술입니다"},
        headers=owner_headers,
    )
    assert create_response.status_code == 200
    ai_copy_id = create_response.json()["data"]["ai_copy_id"]

    other_token = signup_and_login(client, login_id="other")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    delete_response = client.delete(f"/api/ai-ad-copies/{ai_copy_id}", headers=other_headers)
    assert delete_response.status_code == 403

    owner_get_response = client.get(f"/api/ai-ad-copies/{ai_copy_id}", headers=owner_headers)
    assert owner_get_response.status_code == 200


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
