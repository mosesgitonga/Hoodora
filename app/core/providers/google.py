"""Google sign-in: checking the ID token the app gets from Google.

The app signs in with Google on the phone and sends the server the ID token
Google issued. That token is a signed JWT; checking it here is what makes
"this is Google account X" true rather than a claim the client made. The check
covers the signature (against Google's published keys), the audience (our own
client ID, so a token issued to some other app is refused), the issuer and the
expiry.

Only the account's subject ID (`sub`) is taken from the token. Google also puts
the email, name and photo in it; none of them is kept (decision A.1).

The token is never logged: it is a bearer credential for as long as it lives.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import cachecontrol
import google.auth.transport.requests
import requests
from google.auth import exceptions as google_exceptions
from google.oauth2 import id_token as google_id_token

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError

logger = logging.getLogger(__name__)

# Small allowance for the phone's and the server's clocks disagreeing about a
# token that was issued a moment ago.
CLOCK_SKEW_SECONDS = 10


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    sub: str
    """Google's stable ID for the account. Never reused, and unchanged when the
    person changes their email address."""


@runtime_checkable
class GoogleTokenVerifier(Protocol):
    async def verify(self, id_token: str, *, audience: str) -> GoogleIdentity | None:
        """The account the token proves, or `None` for a token that is invalid,
        expired, or issued to another app. Raises `ServiceUnavailableError` when
        Google's keys can't be fetched, which is not the caller's fault."""
        ...


class _TimedRequest(google.auth.transport.requests.Request):
    """google-auth's transport, with a timeout on every call. Its own default is
    two minutes, far longer than anyone waits on a sign-in screen."""

    def __init__(self, session: requests.Session, timeout: float) -> None:
        super().__init__(session=session)
        self._timeout = timeout

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: Any = None,
        headers: Any = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        return super().__call__(  # type: ignore[no-untyped-call]
            url,
            method=method,
            body=body,
            headers=headers,
            timeout=timeout or self._timeout,
            **kwargs,
        )


class GoogleAuthVerifier:
    """Checks tokens with google-auth, in a thread because it is synchronous.

    The keys are fetched over HTTP through a caching session: Google serves them
    with a cache lifetime of several hours, so most sign-ins make no request.
    """

    def __init__(self, settings: Settings) -> None:
        session = cachecontrol.CacheControl(requests.Session())
        self._request = _TimedRequest(session, settings.google_timeout_seconds)

    async def verify(self, id_token: str, *, audience: str) -> GoogleIdentity | None:
        try:
            claims = await asyncio.to_thread(
                google_id_token.verify_oauth2_token,
                id_token,
                self._request,
                audience,
                clock_skew_in_seconds=CLOCK_SKEW_SECONDS,
            )
        except google_exceptions.TransportError as exc:
            logger.warning("google_keys_unavailable", extra={"error": type(exc).__name__})
            raise ServiceUnavailableError("Google sign-in is unavailable right now") from exc
        except (ValueError, google_exceptions.GoogleAuthError) as exc:
            # Expired, wrong audience, wrong issuer, bad signature or not a JWT.
            logger.info("google_token_refused", extra={"error": type(exc).__name__})
            return None

        subject = claims.get("sub") if isinstance(claims, dict) else None
        if not isinstance(subject, str) or not subject:
            return None
        return GoogleIdentity(sub=subject)


_verifier: GoogleTokenVerifier | None = None


def get_google_verifier() -> GoogleTokenVerifier:
    """The process-wide verifier, so its key cache is shared by every request."""
    global _verifier
    if _verifier is None:
        from app.core.config import get_settings

        _verifier = GoogleAuthVerifier(get_settings())
    return _verifier


def set_google_verifier(verifier: GoogleTokenVerifier | None) -> None:
    """Override the verifier. Used by tests; `None` restores the default."""
    global _verifier
    _verifier = verifier
