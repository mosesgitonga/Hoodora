"""Google's tokens: signing in with Google, and phone numbers proved by Firebase.

**Sign-in.** The app signs in with Google on the phone and sends the server the ID
token Google issued.

The app signs in with Google on the phone and sends the server the ID token
Google issued. That token is a signed JWT; checking it here is what makes
"this is Google account X" true rather than a claim the client made. The check
covers the signature (against Google's published keys), the audience (our own
client ID, so a token issued to some other app is refused), the issuer and the
expiry.

Only the account's subject ID (`sub`) is taken from the token. Google also puts
the email, name and photo in it; none of them is kept (decision A.1).

**Phone numbers.** Firebase texts the code and checks it on the phone (decision
A.2). What the server receives is the Firebase ID token that sign-in produced: a
JWT signed with Firebase's keys, for our project, saying which number was just
proved. The server checks it like Google's, then reads only the number.

Neither token is ever logged: each is a bearer credential for as long as it
lives.
"""

from __future__ import annotations

import asyncio
import logging
import time
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


# ---------------------------------------------------------------------------
# Phone numbers proved with Firebase (decision A.2)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProvedPhone:
    phone_number: str
    """As Firebase gives it: E.164, such as +254712345678."""


@runtime_checkable
class PhoneTokenVerifier(Protocol):
    async def verify(
        self, id_token: str, *, project_id: str, max_age_seconds: int
    ) -> ProvedPhone | None:
        """The number a Firebase phone sign-in proved, or `None` for a token that is
        invalid, expired, for another project, not from a phone sign-in, or proved
        longer than `max_age_seconds` ago. Raises `ServiceUnavailableError` when the
        keys can't be fetched."""
        ...


class FirebasePhoneVerifier:
    """Checks Firebase ID tokens with google-auth, as `GoogleAuthVerifier` does
    Google's: the signature against Firebase's published keys, the audience and
    issuer (our project), and the expiry. Then that the sign-in was by phone, and
    recent, so a token kept from an old sign-in proves nothing today."""

    def __init__(self, settings: Settings) -> None:
        session = cachecontrol.CacheControl(requests.Session())
        self._request = _TimedRequest(session, settings.google_timeout_seconds)

    async def verify(
        self, id_token: str, *, project_id: str, max_age_seconds: int
    ) -> ProvedPhone | None:
        try:
            claims = await asyncio.to_thread(
                google_id_token.verify_firebase_token,
                id_token,
                self._request,
                project_id,
                clock_skew_in_seconds=CLOCK_SKEW_SECONDS,
            )
        except google_exceptions.TransportError as exc:
            logger.warning("firebase_keys_unavailable", extra={"error": type(exc).__name__})
            raise ServiceUnavailableError("Phone verification is unavailable right now") from exc
        except (ValueError, google_exceptions.GoogleAuthError) as exc:
            logger.info("firebase_token_refused", extra={"error": type(exc).__name__})
            return None
        return proved_phone_from(
            claims, project_id=project_id, max_age_seconds=max_age_seconds, now=time.time()
        )


def proved_phone_from(
    claims: Any, *, project_id: str, max_age_seconds: int, now: float
) -> ProvedPhone | None:
    """The number in a verified token's claims, if they are what a fresh phone
    sign-in to our project says. Separate from the signature check so it can be
    tested without Firebase's keys."""
    if not isinstance(claims, dict):
        return None
    firebase = claims.get("firebase")
    provider = firebase.get("sign_in_provider") if isinstance(firebase, dict) else None
    phone = claims.get("phone_number")
    auth_time = claims.get("auth_time")
    reason = None
    if claims.get("iss") != f"https://securetoken.google.com/{project_id}":
        reason = "issuer"
    elif provider != "phone":
        reason = "not_phone"
    elif not isinstance(phone, str) or not phone:
        reason = "no_number"
    elif not isinstance(auth_time, int | float) or now - auth_time > max_age_seconds:
        reason = "stale"
    if reason is not None:
        logger.info("firebase_token_refused", extra={"error": reason})
        return None
    return ProvedPhone(phone_number=str(phone))


_phone_verifier: PhoneTokenVerifier | None = None


def get_phone_verifier() -> PhoneTokenVerifier:
    """The process-wide verifier, so its key cache is shared by every request."""
    global _phone_verifier
    if _phone_verifier is None:
        from app.core.config import get_settings

        _phone_verifier = FirebasePhoneVerifier(get_settings())
    return _phone_verifier


def set_phone_verifier(verifier: PhoneTokenVerifier | None) -> None:
    """Override the verifier. Used by tests; `None` restores the default."""
    global _phone_verifier
    _phone_verifier = verifier
