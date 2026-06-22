from conftest import signup_and_login


def test_server_check(client):
    response = client.get("/server-check")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_signup_login_and_me(client):
    token = signup_and_login(client)

    me_response = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["data"]["login_id"] == "user1"


def test_signup_rejects_duplicate_email(client):
    token = signup_and_login(client)
    assert token
    response = client.post(
        "/api/auth/signup",
        json={
            "login_id": "user2",
            "password": "password123",
            "name": "User Two",
            "email": "user1@example.com",
        },
    )
    assert response.status_code == 400


def test_login_rejects_repeated_failed_attempts(client):
    client.post(
        "/api/auth/signup",
        json={
            "login_id": "limited-user",
            "password": "password123",
            "name": "Limited User",
            "email": "limited@example.com",
        },
    )

    for _ in range(11):
        response = client.post(
            "/api/auth/login",
            json={"login_id": "limited-user", "password": "wrong-password"},
        )

    assert response.status_code == 429


def test_logout_requires_authentication(client):
    response = client.post("/api/auth/logout")
    assert response.status_code == 401
