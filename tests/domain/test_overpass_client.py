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


def test_fetch_overpass_elements_switches_endpoint_after_connection_failure(monkeypatch):
    calls = []

    class Response:
        status_code = 200
        text = '{"elements": [{"type": "way", "id": 1}]}'

        def json(self):
            return {"elements": [{"type": "way", "id": 1}]}

    def fake_post(endpoint, **kwargs):
        calls.append(endpoint)
        if endpoint == "http://local-overpass/api/interpreter":
            raise overpass.requests.ConnectionError("connection refused")
        return Response()

    monkeypatch.setattr(overpass.settings, "overpass_endpoint", "http://local-overpass/api/interpreter")
    monkeypatch.setattr(
        overpass.settings,
        "overpass_fallback_endpoints",
        "https://backup-overpass/api/interpreter",
    )
    monkeypatch.setattr(overpass.settings, "overpass_retry_count", 1)
    monkeypatch.setattr(overpass.requests, "post", fake_post)
    monkeypatch.setattr(overpass.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(overpass, "get_overpass_cache", lambda query, ttl_s: None)
    monkeypatch.setattr(overpass, "set_overpass_cache", lambda *args, **kwargs: None)

    elements = overpass.fetch_overpass_elements("[out:json];")

    assert elements == [{"type": "way", "id": 1}]
    assert calls == [
        "http://local-overpass/api/interpreter",
        "https://backup-overpass/api/interpreter",
    ]


def test_fetch_overpass_elements_does_not_fail_over_invalid_query(monkeypatch):
    calls = []

    class Response:
        status_code = 400
        text = "parse error"

    def fake_post(endpoint, **kwargs):
        calls.append(endpoint)
        return Response()

    monkeypatch.setattr(overpass.settings, "overpass_endpoint", "http://primary/api/interpreter")
    monkeypatch.setattr(overpass.settings, "overpass_fallback_endpoints", "https://backup/api/interpreter")
    monkeypatch.setattr(overpass.requests, "post", fake_post)
    monkeypatch.setattr(overpass, "get_overpass_cache", lambda query, ttl_s: None)

    try:
        overpass.fetch_overpass_elements("invalid query")
    except RuntimeError as exc:
        assert "HTTP 400" in str(exc)
    else:
        raise AssertionError("invalid Overpass query must fail")

    assert calls == ["http://primary/api/interpreter"]
