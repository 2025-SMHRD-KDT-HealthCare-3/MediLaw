from conftest import signup_and_login

from app.services import hms_client


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

    verification_list_response = client.get(
        f"/api/answers/{ans_id}/verifications",
        headers=headers,
    )
    assert verification_list_response.status_code == 200
    assert len(verification_list_response.json()["data"]) == 1
    assert verification_list_response.json()["data"][0]["confidence_score"] == "91.00"


def test_ai_answer_uses_citation_summary_score_when_output_empty(client, monkeypatch):
    seen_timeouts = []

    def fake_post_json(path: str, payload: dict, *, timeout: int = 120) -> dict:
        seen_timeouts.append(timeout)
        assert timeout == hms_client.DEFAULT_TIMEOUT
        if path == "/chat":
            return {
                "answer": "의료법 근거에 따른 답변입니다.",
                "sources": [
                    {
                        "label": "의료법 제56조",
                        "snippet": "거짓 또는 과장된 의료광고를 하지 말아야 합니다.",
                        "source_url": "https://example.test/law",
                    }
                ],
                "citation_check": {
                    "output": [],
                    "summary": {
                        "total": 1,
                        "verified": 1,
                        "failed": 0,
                        "avg_score": 76,
                        "min_score": 76,
                    },
                },
            }
        raise AssertionError(f"unexpected HMS JSON path: {path}")

    monkeypatch.setattr(hms_client, "post_json", fake_post_json)

    token = signup_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    room_id = client.post(
        "/api/rooms",
        json={"room_title": "AI 상담방"},
        headers=headers,
    ).json()["data"]["room_id"]

    response = client.post(
        f"/api/rooms/{room_id}/ai-answer",
        json={"question": "의료광고 문구가 가능한가요?"},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["evidences"][0]["ans_id"] == data["answer_chat"]["chat_id"]
    assert data["verifications"][0]["confidence_score"] == "76.00"
    assert seen_timeouts == [hms_client.DEFAULT_TIMEOUT]


def test_ai_answer_uses_source_score_when_citation_summary_has_no_items(client, monkeypatch):
    def fake_post_json(path: str, payload: dict, *, timeout: int = 120) -> dict:
        assert timeout == hms_client.DEFAULT_TIMEOUT
        if path == "/chat":
            return {
                "answer": "동의서만으로 손해배상청구가 당연히 불가능해지지는 않습니다.[1][2]",
                "sources": [
                    {
                        "label": "대법원 94다35671",
                        "source_type": "case",
                        "trust_grade": "A",
                        "snippet": "설명의무와 승낙권 침해에 관한 판례입니다.",
                        "source_url": "https://example.test/case-a",
                    },
                    {
                        "label": "대법원 98다32045",
                        "source_type": "case",
                        "trust_grade": "B",
                        "snippet": "의료과실 및 인과관계에 관한 판례입니다.",
                        "source_url": "https://example.test/case-b",
                    },
                ],
                "citation_check": {
                    "output": [],
                    "summary": {
                        "total": 0,
                        "verified": 0,
                        "failed": 0,
                        "avg_score": 0,
                        "min_score": 100,
                    },
                },
            }
        raise AssertionError(f"unexpected HMS JSON path: {path}")

    monkeypatch.setattr(hms_client, "post_json", fake_post_json)

    token = signup_and_login(client, login_id="source-score-user")
    headers = {"Authorization": f"Bearer {token}"}
    room_id = client.post(
        "/api/rooms",
        json={"room_title": "AI 상담방"},
        headers=headers,
    ).json()["data"]["room_id"]

    response = client.post(
        f"/api/rooms/{room_id}/ai-answer",
        json={"question": "동의서에 서명하면 손해배상청구가 불가능한가요?"},
        headers=headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["evidences"]) == 2
    assert data["verifications"][0]["confidence_score"] == "86.00"
    assert data["verifications"][0]["verification_status"] == "CONFIRMED"
