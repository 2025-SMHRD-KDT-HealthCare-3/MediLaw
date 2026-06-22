from conftest import signup_and_login


def _create_room(client, token: str) -> int:
    response = client.post(
        "/api/rooms",
        json={"room_title": "상담방", "room_desc": "테스트 방"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return response.json()["data"]["room_id"]


def test_closed_room_rejects_new_chat(client):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    room_id = _create_room(client, token)

    close_response = client.patch(
        f"/api/rooms/{room_id}",
        json={"room_status": "CLOSED"},
        headers=headers,
    )
    assert close_response.status_code == 200

    chat_response = client.post(
        f"/api/rooms/{room_id}/chats",
        json={"chat_text": "닫힌 방에는 저장되면 안 됩니다."},
        headers=headers,
    )
    assert chat_response.status_code == 400


def test_leave_room_does_not_close_room(client):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    room_id = _create_room(client, token)

    leave_response = client.post(f"/api/rooms/{room_id}/leave", headers=headers)
    assert leave_response.status_code == 200
    assert leave_response.json()["message"] == "room left"
    assert leave_response.json()["data"]["room_status"] == "ACTIVE"

    chat_response = client.post(
        f"/api/rooms/{room_id}/chats",
        json={"chat_text": "continue after leaving"},
        headers=headers,
    )
    assert chat_response.status_code == 200


def test_close_room_endpoint_rejects_new_chat(client):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    room_id = _create_room(client, token)

    close_response = client.post(f"/api/rooms/{room_id}/close", headers=headers)
    assert close_response.status_code == 200
    assert close_response.json()["message"] == "room closed"
    assert close_response.json()["data"]["room_status"] == "CLOSED"

    chat_response = client.post(
        f"/api/rooms/{room_id}/chats",
        json={"chat_text": "closed room should reject this"},
        headers=headers,
    )
    assert chat_response.status_code == 400


def test_delete_room_removes_history(client):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    room_id = _create_room(client, token)

    chat_response = client.post(
        f"/api/rooms/{room_id}/chats",
        json={"chat_text": "delete this room"},
        headers=headers,
    )
    assert chat_response.status_code == 200

    delete_response = client.delete(f"/api/rooms/{room_id}", headers=headers)
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "room deleted"
    assert delete_response.json()["data"] == {"room_id": room_id, "deleted": True}

    list_response = client.get("/api/rooms", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["data"] == []

    room_response = client.get(f"/api/rooms/{room_id}", headers=headers)
    assert room_response.status_code == 404

    chats_response = client.get(f"/api/rooms/{room_id}/chats", headers=headers)
    assert chats_response.status_code == 404


def test_delete_room_removes_ai_answer_children(client, mock_hms):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    room_id = _create_room(client, token)

    ai_response = client.post(
        f"/api/rooms/{room_id}/ai-answer",
        json={"question": "medical law question"},
        headers=headers,
    )
    assert ai_response.status_code == 200
    answer_chat_id = ai_response.json()["data"]["answer_chat"]["chat_id"]

    delete_response = client.delete(f"/api/rooms/{room_id}", headers=headers)
    assert delete_response.status_code == 200

    evidence_response = client.get(f"/api/answers/{answer_chat_id}/evidences", headers=headers)
    assert evidence_response.status_code == 404

    verification_response = client.get(
        f"/api/answers/{answer_chat_id}/verifications",
        headers=headers,
    )
    assert verification_response.status_code == 404


def test_summary_create_requires_admin(client, mock_hms):
    user_token = signup_and_login(client)
    room_id = _create_room(client, user_token)
    user_headers = {"Authorization": f"Bearer {user_token}"}

    user_response = client.post(
        f"/api/rooms/{room_id}/summaries",
        json={},
        headers=user_headers,
    )
    assert user_response.status_code == 403

    chat_response = client.post(
        f"/api/rooms/{room_id}/chats",
        json={"chat_text": "무면허 의료행위 상담이 필요합니다."},
        headers=user_headers,
    )
    assert chat_response.status_code == 200

    admin_token = signup_and_login(client, login_id="admin1", role="ADMIN")
    admin_response = client.post(
        f"/api/rooms/{room_id}/summaries",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_response.status_code == 200
    assert admin_response.json()["data"]["admin_id"] != 0
    assert "checklist_summary" in admin_response.json()["data"]["summary"]


def test_invalid_file_reference_rejected(client):
    token = signup_and_login(client)
    room_id = _create_room(client, token)

    response = client.post(
        f"/api/rooms/{room_id}/chats",
        json={"chat_file": "../secret.txt"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_list_limit_is_capped(client):
    token = signup_and_login(client)
    response = client.get(
        "/api/rooms?limit=1000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
