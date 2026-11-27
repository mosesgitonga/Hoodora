"""Stand-ins for Google and Firebase in tests (decisions A.1, A.2).

Neither is ever called: a fake verifier maps test tokens to a Google account, or
to a phone number Firebase proved. The real verifiers' handling of google-auth's
answers is tested in `test_google_sign_in.py`, with google-auth stubbed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.providers.google import GoogleIdentity, ProvedPhone
from app.modules.users.models import User
from tests.factories import NYERI_TOWN, make_user

CLIENT_ID = "1234567890-web.apps.googleusercontent.com"
FIREBASE_PROJECT = "hoodora-test"

SIGNUP_CONSENTS = {
    "is_adult": True,
    "accept_terms": True,
    "accept_privacy_policy": True,
    "accept_location_use": True,
}


@dataclass
class FakeGoogleVerifier:
    """Tokens it knows map to a Google account ID; anything else is invalid."""

    accounts: dict[str, str] = field(default_factory=dict)
    audiences: list[str] = field(default_factory=list)

    def token_for(self, sub: str) -> str:
        token = f"google-id-token-for-{sub}"
        self.accounts[token] = sub
        return token

    async def verify(self, id_token: str, *, audience: str) -> GoogleIdentity | None:
        self.audiences.append(audience)
        sub = self.accounts.get(id_token)
        return GoogleIdentity(sub=sub) if sub else None


@dataclass
class FakePhoneVerifier:
    """Tokens it knows prove a number, as a Firebase phone sign-in would."""

    proofs: dict[str, str] = field(default_factory=dict)
    asked: list[tuple[str, int]] = field(default_factory=list)

    def token_for(self, phone_number: str) -> str:
        token = f"firebase-id-token-for-{phone_number}"
        self.proofs[token] = phone_number
        return token

    async def verify(
        self, id_token: str, *, project_id: str, max_age_seconds: int
    ) -> ProvedPhone | None:
        self.asked.append((project_id, max_age_seconds))
        phone = self.proofs.get(id_token)
        return ProvedPhone(phone_number=phone) if phone else None


async def google_user(db_session: AsyncSession, sub: str, **kwargs: Any) -> User:
    """Someone who signed up with Google and has no phone number."""
    user = await make_user(db_session, at=NYERI_TOWN, created_days_ago=60, **kwargs)
    user.phone_number = None
    user.phone_verified_at = None
    user.google_sub = sub
    await db_session.flush()
    return user


async def sign_in(client: httpx.AsyncClient, token: str, **device: str) -> httpx.Response:
    return await client.post("/v1/auth/google", json={"id_token": token, **device})


async def sign_up(
    client: httpx.AsyncClient, signup_token: str, **overrides: object
) -> httpx.Response:
    return await client.post(
        "/v1/auth/signup",
        json={
            "signup_token": signup_token,
            "display_name": "Njeri W.",
            **SIGNUP_CONSENTS,
            **overrides,
        },
    )
