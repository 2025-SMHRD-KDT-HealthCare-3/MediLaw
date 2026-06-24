import httpx
import pytest

from app.services import hms_client


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True}


def test_post_json_sends_hms_api_key(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _FakeResponse()

    monkeypatch.setattr(hms_client.settings, "HMS_API_KEY", "secret-key")
    monkeypatch.setattr(hms_client.httpx, "post", fake_post)

    assert hms_client.post_json("/chat", {"question": "test"}) == {"ok": True}
    assert captured["headers"] == {"x-api-key": "secret-key"}


def test_post_multipart_omits_empty_hms_api_key(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return _FakeResponse()

    monkeypatch.setattr(hms_client.settings, "HMS_API_KEY", None)
    monkeypatch.setattr(hms_client.httpx, "post", fake_post)

    assert hms_client.post_multipart("/documents/review", data={"text": "test"}) == {"ok": True}
    assert captured["headers"] == {}


def test_post_json_maps_hms_rate_limit(monkeypatch):
    request = httpx.Request("POST", "http://hms.test/chat")
    response = httpx.Response(429, request=request, text="too many requests")

    def fake_post(*args, **kwargs):
        return response

    monkeypatch.setattr(hms_client.httpx, "post", fake_post)

    with pytest.raises(hms_client.HTTPException) as exc_info:
        hms_client.post_json("/chat", {"question": "test"})

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "HMS rate limit exceeded"


def test_post_json_maps_hms_server_error(monkeypatch):
    request = httpx.Request("POST", "http://hms.test/chat")
    response = httpx.Response(500, request=request, text="internal error")

    def fake_post(*args, **kwargs):
        return response

    monkeypatch.setattr(hms_client.httpx, "post", fake_post)

    with pytest.raises(hms_client.HTTPException) as exc_info:
        hms_client.post_json("/chat", {"question": "test"})

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "HMS server returned an error"
