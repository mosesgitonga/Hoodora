"""CORS, scoped by path (decision D.1).

The admin dashboard is a browser app on its own origin, so `/v1/admin` needs CORS
for it, and only for it. Everything else keeps `CORS_ORIGINS`, which is empty in
every deployment so far: the Flutter app is native and sends no Origin header.

Two policies, never merged: the dashboard's origin gets nothing outside
`/v1/admin`, and an origin in `CORS_ORIGINS` gets nothing inside it.
"""

from __future__ import annotations

from typing import Final

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

ADMIN_PREFIX: Final = "/v1/admin"

# What the dashboard sends: a bearer token and JSON, no cookies.
ADMIN_METHODS: Final = ["GET", "POST", "PATCH", "DELETE"]
ADMIN_HEADERS: Final = ["Authorization", "Content-Type", "X-Request-ID"]


def is_admin_path(path: str) -> bool:
    return path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/")


class ScopedCORSMiddleware:
    """The admin policy under `/v1/admin`, the general one everywhere else."""

    def __init__(
        self, app: ASGIApp, *, general_origins: list[str], admin_origins: list[str]
    ) -> None:
        self.app = app
        self._general = (
            CORSMiddleware(
                app,
                allow_origins=general_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
                expose_headers=["X-Request-ID"],
            )
            if general_origins
            else None
        )
        self._admin = (
            CORSMiddleware(
                app,
                allow_origins=admin_origins,
                # The staff token travels in the Authorization header. No cookie
                # is involved, so credentials stay off.
                allow_credentials=False,
                allow_methods=ADMIN_METHODS,
                allow_headers=ADMIN_HEADERS,
                expose_headers=["X-Request-ID"],
                max_age=600,
            )
            if admin_origins
            else None
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        policy = self._admin if is_admin_path(str(scope.get("path", ""))) else self._general
        await (policy or self.app)(scope, receive, send)
