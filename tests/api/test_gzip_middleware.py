import asyncio
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

sys.path.append(str(Path(__file__).resolve().parents[2]))

from core.middleware import SelectiveGZipMiddleware


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        SelectiveGZipMiddleware,
        minimum_size=100,
        excluded_paths={"/api/v1/analysis/agent/conversations/turns/stream"},
    )

    @app.get("/json")
    async def json_route():
        return JSONResponse({"content": "x" * 200})

    @app.get("/api/v1/analysis/agent/conversations/turns/stream")
    async def excluded_path_route():
        return PlainTextResponse("x" * 200, media_type="text/plain")

    @app.get("/event-stream")
    async def event_stream_route():
        async def event_stream():
            yield "event: status\ndata: {\"stage\":\"gating\"}\n\n"
            yield "event: thinking\ndata: {\"title\":\"门卫判断\"}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


def _request(path: str) -> httpx.Response:
    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=_build_test_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path, headers={"Accept-Encoding": "gzip"})

    return asyncio.run(_run())


def test_regular_json_response_keeps_gzip():
    response = _request("/json")
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
    assert response.headers.get("vary") == "Accept-Encoding"


def test_excluded_path_bypasses_gzip_even_when_large():
    response = _request("/api/v1/analysis/agent/conversations/turns/stream")
    assert response.status_code == 200
    assert response.headers.get("content-encoding") is None
    assert response.text == "x" * 200


def test_event_stream_response_bypasses_gzip():
    response = _request("/event-stream")
    assert response.status_code == 200
    assert response.headers.get("content-encoding") is None
    assert response.headers.get("content-type", "").startswith("text/event-stream")
    assert "event: status" in response.text


def test_main_app_excludes_only_current_conversation_stream():
    from main import app

    middleware = next(
        item for item in app.user_middleware if item.cls is SelectiveGZipMiddleware
    )
    assert middleware.kwargs["excluded_paths"] == {
        "/api/v1/analysis/agent/conversations/turns/stream"
    }
