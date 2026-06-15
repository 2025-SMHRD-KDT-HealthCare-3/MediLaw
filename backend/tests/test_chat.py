from conftest import signup_and_login


def test_create_room_and_chat(client):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    room_response = client.post(
        "/api/rooms",
        json={"room_title": "상담방", "room_desc": "테스트"},
        headers=headers,
    )
    assert room_response.status_code == 200
    room_id = room_response.json()["data"]["room_id"]

    chat_response = client.post(
        f"/api/rooms/{room_id}/chats",
        json={"chat_text": "의료광고 문구를 검토해주세요."},
        headers=headers,
    )
    assert chat_response.status_code == 200
    assert chat_response.json()["data"]["speaker_type"] == "USER"

    list_response = client.get(f"/api/rooms/{room_id}/chats", headers=headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]) == 1
