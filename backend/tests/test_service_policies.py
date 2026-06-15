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


def test_summary_create_requires_admin(client):
    user_token = signup_and_login(client)
    room_id = _create_room(client, user_token)

    user_response = client.post(
        f"/api/rooms/{room_id}/summaries",
        json={},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert user_response.status_code == 403

    admin_token = signup_and_login(client, login_id="admin1", role="ADMIN")
    admin_response = client.post(
        f"/api/rooms/{room_id}/summaries",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_response.status_code == 200
    assert admin_response.json()["data"]["admin_id"] != 0


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
