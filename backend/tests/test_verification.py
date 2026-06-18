from conftest import signup_and_login


def test_ai_answer_creates_evidence_and_verification(client, mock_hms):
    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    room_id = client.post(
        "/api/rooms",
        json={"room_title": "AI 상담방"},
        headers=headers,
    ).json()["data"]["room_id"]

    response = client.post(
        f"/api/rooms/{room_id}/ai-answer",
        json={"question": "비급여 광고 문구가 가능한가요?"},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    ans_id = data["answer_chat"]["chat_id"]
    assert data["answer_chat"]["speaker_type"] == "AI"
    assert data["evidences"][0]["ans_id"] == ans_id
    assert data["verifications"][0]["ans_id"] == ans_id
    assert data["verifications"][0]["confidence_score"] == "82.00"

    assert client.get(f"/api/answers/{ans_id}/evidences").status_code == 401
    evidence_response = client.get(f"/api/answers/{ans_id}/evidences", headers=headers)
    assert evidence_response.status_code == 200
    assert evidence_response.json()["data"][0]["ans_id"] == ans_id

    verification_list_response = client.get(
        f"/api/answers/{ans_id}/verifications",
        headers=headers,
    )
    assert verification_list_response.status_code == 200
    assert verification_list_response.json()["data"][0]["ans_id"] == ans_id

    verify_response = client.post(f"/api/answers/{ans_id}/verify", json={}, headers=headers)
    assert verify_response.status_code == 200
    verify_data = verify_response.json()["data"]
    assert isinstance(verify_data, list)
    assert verify_data[0]["verification_status"] in {
        "CONFIRMED",
        "WARNING",
        "ERROR",
    }
    assert verify_data[0]["confidence_score"] == "91.00"
