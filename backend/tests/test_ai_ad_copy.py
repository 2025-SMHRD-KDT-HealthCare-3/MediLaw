from conftest import signup_and_login


def test_ai_ad_copy_create_and_list(client):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/api/ai-ad-copies",
        json={"input_language": "en", "input_text": "Best hospital cure guaranteed"},
        headers=headers,
    )
    assert create_response.status_code == 200
    data = create_response.json()["data"]
    assert data["english_text"] == "Best hospital cure guaranteed"
    assert data["translated_text"] == "Best hospital cure guaranteed"

    list_response = client.get("/api/ai-ad-copies", headers=headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]) == 1
