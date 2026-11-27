"""Signing in with Google, and adding a phone number proved by Firebase
(decisions A.1, A.2).

Neither Google nor Firebase is called: the fakes in `tests/auth_fakes.py` map
test tokens to a Google account or a proved number. The real verifiers'
handling of google-auth's answers is tested at the end, with google-auth stubbed.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from google.auth import exceptions as google_exceptions
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.core.providers import google as google_provider
from app.core.providers.google import GoogleIdentity, ProvedPhone
from app.modules.moderation import banlist, console
from app.modules.moderation.models import (
    AuditAction,
    AuditEvent,
    BannedDevice,
    BannedGoogleAccount,
    BannedPhone,
)
from app.modules.staff.models import StaffRole
from app.modules.users import service as users_service
from app.modules.users.models import User
from tests.auth_fakes import (
    CLIENT_ID,
    FIREBASE_PROJECT,
    FakeGoogleVerifier,
    FakePhoneVerifier,
    google_user,
    sign_in,
    sign_up,
)
from tests.factories import NYERI_TOWN, give_zone_days, make_staff, make_user, unique_phone

Authenticate = Callable[[User], Awaitable[httpx.AsyncClient]]


# ---------------------------------------------------------------------------
# Whether Google sign-in is on
# ---------------------------------------------------------------------------
async def test_google_is_off_until_a_client_id_is_set(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/auth/methods")

    assert response.status_code == 200
    # With Google off nobody can sign in, which production refuses to start with.
    assert response.json() == {"phone": False, "google": False, "google_client_id": None}


async def test_when_on_the_app_is_given_the_client_id(
    client: httpx.AsyncClient, google_on: Settings
) -> None:
    body = (await client.get("/v1/auth/methods")).json()

    assert body["google"] is True
    assert body["google_client_id"] == CLIENT_ID


async def test_signing_in_with_google_while_it_is_off_is_refused(
    client: httpx.AsyncClient, google: FakeGoogleVerifier
) -> None:
    response = await sign_in(client, google.token_for("g-1"))

    assert response.status_code == 503
    assert google.audiences == [], "Google was asked about a token while sign-in was off"


# ---------------------------------------------------------------------------
# Signing up and signing in
# ---------------------------------------------------------------------------
async def test_a_new_google_account_signs_up_without_a_phone(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    started = await sign_in(client, google.token_for("g-new"))

    assert started.status_code == 200
    assert started.json()["status"] == "signup_required"
    assert google.audiences == [CLIENT_ID]

    created = await sign_up(client, started.json()["signup_token"])
    assert created.status_code == 201, created.text

    user = (await db_session.execute(select(User).where(User.google_sub == "g-new"))).scalar_one()
    assert user.phone_number is None
    assert user.phone_verified_at is None

    client.headers["Authorization"] = f"Bearer {created.json()['tokens']['access_token']}"
    me = (await client.get("/v1/me")).json()
    assert me["phone_number"] is None
    assert me["has_google_account"] is True


async def test_signing_up_with_google_is_audited_as_such(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    started = await sign_in(client, google.token_for("g-audited"))
    user_id = uuid.UUID((await sign_up(client, started.json()["signup_token"])).json()["user_id"])

    event = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == AuditAction.account_created, AuditEvent.target_id == user_id
            )
        )
    ).scalar_one()
    assert event.context["signed_up_with"] == "google"


async def test_a_returning_google_account_is_signed_in(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    user = await google_user(db_session, "g-back")

    response = await sign_in(client, google.token_for("g-back"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "signed_in"
    client.headers["Authorization"] = f"Bearer {body['tokens']['access_token']}"
    assert (await client.get("/v1/me")).json()["id"] == str(user.id)


async def test_an_invalid_token_is_refused(
    client: httpx.AsyncClient, google: FakeGoogleVerifier, google_on: Settings
) -> None:
    response = await sign_in(client, "not-a-google-token-at-all")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_a_banned_google_account_fails_like_an_invalid_token(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    await google_user(db_session, "g-banned")
    db_session.add(BannedGoogleAccount(google_hash=banlist.google_hash("g-banned", google_on)))
    await db_session.flush()

    banned = await sign_in(client, google.token_for("g-banned"))
    invalid = await sign_in(client, "not-a-google-token-at-all")

    assert banned.status_code == invalid.status_code == 401
    assert banned.json()["error"]["message"] == invalid.json()["error"]["message"]


async def test_a_banned_device_cannot_sign_up_with_google(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    db_session.add(BannedDevice(device_hash=banlist.device_hash("install-0001", google_on)))
    await db_session.flush()

    response = await sign_in(client, google.token_for("g-device"), device_id="install-0001")

    assert response.status_code == 401


async def test_a_google_signup_token_works_once(
    client: httpx.AsyncClient, google: FakeGoogleVerifier, google_on: Settings
) -> None:
    started = await sign_in(client, google.token_for("g-once"))
    token = started.json()["signup_token"]

    assert (await sign_up(client, token)).status_code == 201
    assert (await sign_up(client, token)).status_code == 401


async def test_a_google_account_that_signed_up_meanwhile_is_not_doubled(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    started = await sign_in(client, google.token_for("g-race"))
    await google_user(db_session, "g-race")

    response = await sign_up(client, started.json()["signup_token"])

    assert response.status_code == 409


async def test_a_live_account_needs_a_phone_or_a_google_account(
    db_session: AsyncSession,
) -> None:
    user = await make_user(db_session)
    user.phone_number = None

    with pytest.raises(IntegrityError, match="user_can_sign_in"):
        async with db_session.begin_nested():
            await db_session.flush()


# ---------------------------------------------------------------------------
# Adding a phone number later
# ---------------------------------------------------------------------------
async def add_phone(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post("/v1/me/phone", json={"firebase_id_token": token})


async def test_a_google_account_adds_a_phone_firebase_proved(
    db_session: AsyncSession,
    authenticate: Authenticate,
    phone_proofs: FakePhoneVerifier,
    google_on: Settings,
) -> None:
    user = await google_user(db_session, "g-adds")
    user_id = user.id
    phone = unique_phone()
    client = await authenticate(user)

    response = await add_phone(client, phone_proofs.token_for(phone))

    assert response.status_code == 200, response.text
    assert response.json()["phone_number"] == phone
    assert phone_proofs.asked == [(FIREBASE_PROJECT, google_on.phone_proof_max_age_seconds)]
    await db_session.refresh(user)
    assert user.phone_verified_at is not None
    added = await db_session.scalar(
        select(AuditEvent.id).where(
            AuditEvent.action == AuditAction.phone_added, AuditEvent.target_id == user_id
        )
    )
    assert added is not None


async def test_a_proof_firebase_did_not_give_adds_nothing(
    db_session: AsyncSession,
    authenticate: Authenticate,
    phone_proofs: FakePhoneVerifier,
    google_on: Settings,
) -> None:
    user = await google_user(db_session, "g-forged")
    client = await authenticate(user)

    response = await add_phone(client, "a-token-firebase-never-issued")

    assert response.status_code == 401
    await db_session.refresh(user)
    assert user.phone_number is None


async def test_adding_a_phone_is_off_without_a_firebase_project(
    db_session: AsyncSession, authenticate: Authenticate, phone_proofs: FakePhoneVerifier
) -> None:
    client = await authenticate(await google_user(db_session, "g-no-firebase"))

    response = await add_phone(client, phone_proofs.token_for(unique_phone()))

    assert response.status_code == 503
    assert phone_proofs.asked == []


async def test_an_account_with_a_number_cannot_add_another(
    db_session: AsyncSession,
    authenticate: Authenticate,
    phone_proofs: FakePhoneVerifier,
    google_on: Settings,
) -> None:
    client = await authenticate(await make_user(db_session))

    response = await add_phone(client, phone_proofs.token_for(unique_phone()))

    assert response.status_code == 409
    assert response.json()["error"]["details"]["reason"] == "phone_already_set"


async def test_a_number_held_by_another_account_is_refused(
    db_session: AsyncSession,
    authenticate: Authenticate,
    phone_proofs: FakePhoneVerifier,
    google_on: Settings,
) -> None:
    taken = (await make_user(db_session)).phone_number
    assert taken is not None
    client = await authenticate(await google_user(db_session, "g-taken"))

    response = await add_phone(client, phone_proofs.token_for(taken))

    assert response.status_code == 409
    assert response.json()["error"]["details"]["reason"] == "phone_in_use"


async def test_a_banned_number_reads_as_a_failed_proof(
    db_session: AsyncSession,
    authenticate: Authenticate,
    phone_proofs: FakePhoneVerifier,
    google_on: Settings,
) -> None:
    client = await authenticate(await google_user(db_session, "g-banned-number"))
    phone = unique_phone()
    db_session.add(BannedPhone(phone_hash=banlist.phone_hash(phone, google_on)))
    await db_session.flush()

    response = await add_phone(client, phone_proofs.token_for(phone))

    assert response.status_code == 401
    assert (
        response.json()["error"]["message"] == "That number couldn't be verified. Please try again."
    )


async def test_a_landline_firebase_proved_is_still_refused(
    db_session: AsyncSession,
    authenticate: Authenticate,
    phone_proofs: FakePhoneVerifier,
    google_on: Settings,
) -> None:
    client = await authenticate(await google_user(db_session, "g-landline"))

    response = await add_phone(client, phone_proofs.token_for("+254202222222"))

    assert response.status_code == 400


async def test_adding_a_phone_needs_a_signed_in_account(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/me/phone", json={"firebase_id_token": "x" * 40})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# What a phone is still needed for
# ---------------------------------------------------------------------------
JOB = {"kind": "hiring", "category": "other", "title": "Shop assistant, weekends"}


async def test_posting_a_job_without_a_phone_asks_for_one(
    db_session: AsyncSession,
    authenticate: Authenticate,
    phone_proofs: FakePhoneVerifier,
    google_on: Settings,
) -> None:
    user = await google_user(db_session, "g-hires")
    # Around long enough to post here (decision L.2): only the phone is missing.
    await give_zone_days(db_session, user, NYERI_TOWN)
    client = await authenticate(user)

    refused = await client.post("/v1/services", json=JOB)
    offering = await client.post(
        "/v1/services", json={"kind": "offering", "category": "plumbing", "title": "Plumber"}
    )

    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "phone_required"
    assert offering.status_code == 201, "offering a service needs no phone"

    assert (await add_phone(client, phone_proofs.token_for(unique_phone()))).status_code == 200
    assert (await client.post("/v1/services", json=JOB)).status_code == 201


# ---------------------------------------------------------------------------
# Bans, and the data rights
# ---------------------------------------------------------------------------
async def test_banning_an_account_bans_its_google_account_until_unbanned(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    user = await google_user(db_session, "g-moderated")
    admin = (await make_staff(db_session, role=StaffRole.admin)).account

    await console.ban(
        db_session,
        staff=admin,
        user_id=user.id,
        reason="Scam job posts",
        ban_phone=True,
        ban_devices=True,
        remove_content=False,
        settings=google_on,
    )
    held = await db_session.scalar(
        select(BannedGoogleAccount.id).where(BannedGoogleAccount.user_id == user.id)
    )
    assert held is not None
    assert (await sign_in(client, google.token_for("g-moderated"))).status_code == 401

    await console.unban(db_session, staff=admin, user_id=user.id)
    assert not await banlist.is_google_banned(db_session, "g-moderated", google_on)


async def test_the_export_names_the_google_account(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await google_user(db_session, "g-export"))

    account = (await client.get("/v1/me/export")).json()["account"]

    assert account["google_account_id"] == "g-export"
    assert account["phone_number"] is None


async def test_the_purge_forgets_the_google_account(db_session: AsyncSession) -> None:
    user = await google_user(db_session, "g-purged")

    await users_service.purge_user(db_session, user=user)
    await db_session.flush()

    await db_session.refresh(user)
    assert user.google_sub is None
    assert await users_service.get_user_by_google_sub(db_session, "g-purged") is None


# ---------------------------------------------------------------------------
# The real verifier's handling of google-auth's answers
# ---------------------------------------------------------------------------
@pytest.fixture
def real_verifier(settings: Settings) -> google_provider.GoogleAuthVerifier:
    return google_provider.GoogleAuthVerifier(settings)


async def test_a_token_google_auth_accepts_gives_its_subject(
    real_verifier: google_provider.GoogleAuthVerifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def accept(token: str, request: Any, audience: str, **kwargs: Any) -> dict[str, Any]:
        seen.update(token=token, audience=audience, **kwargs)
        return {"sub": "g-real", "email": "someone@example.com"}

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", accept)

    identity = await real_verifier.verify("a-google-id-token", audience=CLIENT_ID)

    assert identity == GoogleIdentity(sub="g-real")
    assert seen["audience"] == CLIENT_ID
    assert seen["clock_skew_in_seconds"] == google_provider.CLOCK_SKEW_SECONDS


async def test_a_token_google_auth_refuses_is_none(
    real_verifier: google_provider.GoogleAuthVerifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("Token expired")

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", refuse)

    assert await real_verifier.verify("an-expired-token", audience=CLIENT_ID) is None


async def test_unreachable_google_keys_are_a_503_not_a_refusal(
    real_verifier: google_provider.GoogleAuthVerifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise google_exceptions.TransportError("Could not fetch certificates")  # type: ignore[no-untyped-call]

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", unreachable)

    with pytest.raises(ServiceUnavailableError):
        await real_verifier.verify("a-google-id-token", audience=CLIENT_ID)


# ---------------------------------------------------------------------------
# The real Firebase verifier: what a fresh phone sign-in to our project says
# ---------------------------------------------------------------------------
def _phone_claims(**overrides: Any) -> dict[str, Any]:
    now = time.time()
    return {
        "iss": f"https://securetoken.google.com/{FIREBASE_PROJECT}",
        "aud": FIREBASE_PROJECT,
        "auth_time": int(now) - 30,
        "phone_number": "+254712345678",
        "firebase": {"sign_in_provider": "phone", "identities": {}},
        **overrides,
    }


def _proved(claims: dict[str, Any]) -> ProvedPhone | None:
    return google_provider.proved_phone_from(
        claims, project_id=FIREBASE_PROJECT, max_age_seconds=600, now=time.time()
    )


def test_a_fresh_phone_sign_in_proves_its_number() -> None:
    assert _proved(_phone_claims()) == ProvedPhone(phone_number="+254712345678")


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://securetoken.google.com/someone-elses-project"},
        {"firebase": {"sign_in_provider": "google.com"}},
        {"firebase": {"sign_in_provider": "anonymous"}},
        {"phone_number": None},
        {"auth_time": int(time.time()) - 3600},
        {"auth_time": None},
    ],
    ids=["other project", "google sign-in", "anonymous", "no number", "stale", "no time"],
)
def test_anything_but_a_fresh_phone_sign_in_proves_nothing(overrides: dict[str, Any]) -> None:
    assert _proved(_phone_claims(**overrides)) is None


async def test_the_real_phone_verifier_checks_the_token_for_our_project(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def accept(token: str, request: Any, audience: str, **kwargs: Any) -> dict[str, Any]:
        seen.update(token=token, audience=audience, **kwargs)
        return _phone_claims()

    monkeypatch.setattr(google_id_token, "verify_firebase_token", accept)
    verifier = google_provider.FirebasePhoneVerifier(settings)

    proved = await verifier.verify(
        "a-firebase-token", project_id=FIREBASE_PROJECT, max_age_seconds=600
    )

    assert proved == ProvedPhone(phone_number="+254712345678")
    assert seen["audience"] == FIREBASE_PROJECT
    assert seen["clock_skew_in_seconds"] == google_provider.CLOCK_SKEW_SECONDS


async def test_a_token_firebase_keys_refuse_proves_nothing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ValueError("Token used too late")

    monkeypatch.setattr(google_id_token, "verify_firebase_token", refuse)
    verifier = google_provider.FirebasePhoneVerifier(settings)

    assert await verifier.verify("old", project_id=FIREBASE_PROJECT, max_age_seconds=600) is None


async def test_unreachable_firebase_keys_are_a_503_not_a_refusal(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise google_exceptions.TransportError("Could not fetch certificates")  # type: ignore[no-untyped-call]

    monkeypatch.setattr(google_id_token, "verify_firebase_token", unreachable)
    verifier = google_provider.FirebasePhoneVerifier(settings)

    with pytest.raises(ServiceUnavailableError):
        await verifier.verify("a-token", project_id=FIREBASE_PROJECT, max_age_seconds=600)
