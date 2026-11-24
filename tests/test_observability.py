"""Error tracking that leaks nothing, and metrics that identify no one."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import MutableMapping
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.metrics import JOB_LAST_SUCCESS, JOBS, UNMATCHED_ROUTE, route_template
from app.core.observability import init_sentry, scrub_event
from app.workers.tasks import heartbeat


def _event() -> dict[str, Any]:
    return {
        "message": "Failed for +254712345678 at -0.4201, 36.9476",
        "request": {
            "method": "GET",
            "url": "https://api.example.com/v1/feed?lat=-0.42&lng=36.94",
            "headers": {"Authorization": "Bearer eyJhbGciOi.secret.token"},
            "cookies": {"session": "abc"},
            "query_string": "lat=-0.42&lng=36.94",
            "data": {"code": "123456"},
        },
        "user": {"id": "user-1", "ip_address": "197.0.0.1", "username": "Wanjiku"},
        "server_name": "api-1",
        "extra": {"phone_number": "+254712345678", "nested": {"latitude": -0.42}},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "bad +254712345678",
                    "stacktrace": {"frames": [{"function": "f", "vars": {"lat": -0.42}}]},
                }
            ]
        },
    }


def test_the_request_is_reduced_to_method_and_route() -> None:
    event = scrub_event(_event())
    assert event["request"] == {"method": "GET", "url": "https://api.example.com/v1/feed"}


def test_no_locals_no_ip_no_server_name() -> None:
    event = scrub_event(_event())
    frame = event["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert "vars" not in frame
    assert event["user"] == {"id": "user-1"}
    assert "server_name" not in event


def test_text_and_keys_are_redacted_like_the_logs() -> None:
    event = scrub_event(_event())
    text = repr(event)
    assert "+254712345678" not in text
    assert "36.9476" not in text
    assert event["extra"]["phone_number"] == "[redacted]"
    assert event["extra"]["nested"]["latitude"] == "[redacted]"


def test_sentry_is_off_without_a_dsn(settings: Settings) -> None:
    assert init_sentry(settings, service="api") is False


def test_routes_are_labelled_by_template_not_path() -> None:
    post_id = "6f1c2b7e-0000-4000-8000-000000000001"
    scope = {
        "route": object(),
        "path": f"/v1/posts/{post_id}/comments",
        "path_params": {"post_id": post_id},
    }
    assert route_template(scope) == "/v1/posts/{post_id}/comments"
    assert route_template({"path": "/wp-admin/setup.php"}) == UNMATCHED_ROUTE


async def test_metrics_do_not_exist_without_a_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/metrics")).status_code == 404


async def test_metrics_need_the_token(
    client: httpx.AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_token", SecretStr("scrape-me"))
    await client.get("/health")
    await client.get(f"/v1/users/{'0' * 8}-0000-0000-0000-{'0' * 12}")

    assert (await client.get("/metrics")).status_code == 404
    wrong = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 404
    response = await client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})
    assert response.status_code == 200
    body = response.text
    assert "myradius_http_requests_total" in body
    assert 'route="/v1/users/{user_id}"' in body
    # The concrete ID never becomes a label.
    assert "00000000-0000-0000-0000-000000000000" not in body


async def test_worker_jobs_are_counted_and_their_last_success_recorded() -> None:
    before = JOBS.labels("heartbeat", "success")._value.get()
    await heartbeat({})
    assert JOBS.labels("heartbeat", "success")._value.get() == before + 1
    assert JOB_LAST_SUCCESS.labels("heartbeat")._value.get() > 0


# ---------------------------------------------------------------------------
# WebSockets in the access log
# ---------------------------------------------------------------------------
async def _ws_status(settings: Settings, caplog: pytest.LogCaptureFixture, app: Any) -> object:
    """Run `app` as a WebSocket behind the access-log middleware; the logged status."""
    from app.core.middleware import RequestContextMiddleware

    incoming: list[dict[str, Any]] = [
        {"type": "websocket.connect"},
        {"type": "websocket.disconnect", "code": 1000},
    ]

    async def receive() -> dict[str, Any]:
        return incoming.pop(0) if incoming else {"type": "websocket.disconnect", "code": 1000}

    async def send(message: MutableMapping[str, Any]) -> None:
        return None

    scope = {"type": "websocket", "path": "/v1/ws", "headers": [], "client": ("10.0.0.1", 1)}
    access = logging.getLogger("app.access")
    access.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="app.access")
    try:
        middleware = RequestContextMiddleware(app, settings.model_copy(update={"log_access": True}))
        with contextlib.suppress(RuntimeError):
            await middleware(scope, receive, send)
    finally:
        access.removeHandler(caplog.handler)
    record = next(r for r in caplog.records if r.getMessage() == "http_request")
    return getattr(record, "status_code", None)


async def test_a_websocket_that_closes_normally_is_not_logged_as_an_error(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "websocket.accept"})
        await receive()  # the phone goes away

    assert await _ws_status(settings, caplog, app) == 101


async def test_a_websocket_refused_before_accepting_is_logged_as_refused(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "websocket.close", "code": 4401})

    assert await _ws_status(settings, caplog, app) == 403


async def test_a_websocket_that_crashes_is_still_logged_as_an_error(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "websocket.accept"})
        raise RuntimeError("boom")

    assert await _ws_status(settings, caplog, app) == 500
