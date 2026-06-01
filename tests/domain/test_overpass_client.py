from modules.road import overpass


def test_fetch_overpass_elements_sends_user_agent(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = '{"elements": []}'

        def json(self):
            return {"elements": []}

    def fake_post(endpoint, data, headers, timeout):
        captured["endpoint"] = endpoint
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(overpass.requests, "post", fake_post)
    monkeypatch.setattr(overpass, "get_overpass_cache", lambda query, ttl_s: None)
    monkeypatch.setattr(overpass, "set_overpass_cache", lambda *args, **kwargs: None)

    assert overpass.fetch_overpass_elements("[out:json];") == []
    assert captured["headers"]["User-Agent"] == overpass.OVERPASS_USER_AGENT
