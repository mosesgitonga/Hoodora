"""The authentication endpoints, end to end over HTTP.

Signing in is with Google only (decision A.2); Google is faked, as in
`tests/auth_fakes.py`. The refresh-rotation section is the one to read
carefully: reuse detection is the subtlest behaviour in Phase 1, and the tests
state the behaviour the design chose rather than just checking status codes.
"""

from __future__ import annotations

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.auth import service as auth_service
from app.modules.auth.models import DeviceSession, SessionRevocationReason
from app.modules.users.models import ConsentType, User, UserStatus
from app.modules.users.service import current_consents
from tests.auth_fakes import SIGNUP_CONSENTS, FakeGoogleVerifier, sign_in, sign_up
from tests.factories import NYERI_TOWN, make_user


# ---------------------------------------------------------------------------
# Phone sign-in is gone (decision A.2)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/v1/auth/otp/request", "/v1/auth/otp/verify"])
async def test_there_is_no_phone_sign_in(client: httpx.AsyncClient, path: str) -> None:
    response = await client.post(path, json={"phone_number": "0712345678", "code": "123456"})

    assert response.status_code == 404


async def test_the_methods_say_google_only(client: httpx.AsyncClient, google_on: Settings) -> None:
    methods = (await client.get("/v1/auth/methods")).json()

    assert methods["phone"] is False
    assert methods["google"] is True


# ---------------------------------------------------------------------------
# Signing up
# ---------------------------------------------------------------------------
async def complete_signup(
    client: httpx.AsyncClient, google: FakeGoogleVerifier, sub: str, **overrides: object
) -> httpx.Response:
    started = await sign_in(client, google.token_for(sub))
    assert started.json()["status"] == "signup_required", started.text
    return await sign_up(
        client, started.json()["signup_token"], **{"display_name": "New Neighbour", **overrides}
    )


async def created_by(db_session: AsyncSession, sub: str) -> User:
    return (await db_session.execute(select(User).where(User.google_sub == sub))).scalar_one()


async def test_signup_creates_an_account_and_signs_in(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    response = await complete_signup(client, google, "g-new")

    assert response.status_code == 201
    assert response.json()["tokens"]["access_token"]
    created = await created_by(db_session, "g-new")
    assert created.display_name == "New Neighbour"
    assert created.status == UserStatus.active
    # A number comes later, proved by Firebase, when it is needed (decision A.2).
    assert created.phone_number is None


async def test_signup_records_the_adult_confirmation_as_a_timestamp(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    """The Act wants evidence of *when* a declaration was made; a bare `true`
    records nothing worth having."""
    await complete_signup(client, google, "g-adult")

    assert (await created_by(db_session, "g-adult")).adult_confirmed_at is not None


async def test_signup_records_each_consent_with_its_document_version(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    await complete_signup(client, google, "g-consents")

    consents = await current_consents(db_session, (await created_by(db_session, "g-consents")).id)

    assert consents[ConsentType.terms].granted is True
    assert consents[ConsentType.terms].document_version == google_on.terms_version
    assert consents[ConsentType.privacy_policy].granted is True
    assert consents[ConsentType.location_use].granted is True
    # Optional and not requested, so no record at all.
    assert ConsentType.marketing not in consents


async def test_marketing_consent_is_recorded_when_given(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google: FakeGoogleVerifier,
    google_on: Settings,
) -> None:
    await complete_signup(client, google, "g-marketing", accept_marketing=True)

    consents = await current_consents(db_session, (await created_by(db_session, "g-marketing")).id)

    assert consents[ConsentType.marketing].granted is True


@pytest.mark.parametrize(
    "withheld",
    ["is_adult", "accept_terms", "accept_privacy_policy", "accept_location_use"],
)
async def test_signup_requires_every_mandatory_confirmation(
    client: httpx.AsyncClient, google: FakeGoogleVerifier, google_on: Settings, withheld: str
) -> None:
    """Enforced by the schema, so there is no code path that creates an account
    without them."""
    response = await complete_signup(client, google, f"g-no-{withheld}", **{withheld: False})

    assert response.status_code == 422


async def test_a_signup_token_is_single_use(
    client: httpx.AsyncClient, google: FakeGoogleVerifier, google_on: Settings
) -> None:
    """So a replayed token cannot create a second account."""
    started = await sign_in(client, google.token_for("g-once"))
    token = started.json()["signup_token"]

    first = await sign_up(client, token, display_name="First")
    second = await sign_up(client, token, display_name="Second")

    assert first.status_code == 201
    assert second.status_code == 401


async def test_an_invalid_signup_token_is_refused(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/auth/signup",
        json={"signup_token": "nonsense", "display_name": "Nobody", **SIGNUP_CONSENTS},
    )

    assert response.status_code == 401


async def test_a_phone_signup_token_from_before_google_only_is_refused(
    client: httpx.AsyncClient, redis_client: Redis, settings: Settings
) -> None:
    """A phone signup started before decision A.2 cannot finish: sign in again."""
    from app.core.security import hash_secret

    await redis_client.set(
        f"{auth_service.SIGNUP_TOKEN_PREFIX}:{hash_secret('old-phone-token', settings)}",
        "+254712345678",
        ex=60,
    )

    response = await sign_up(client, "old-phone-token")

    assert response.status_code == 401


async def test_a_short_display_name_is_refused(
    client: httpx.AsyncClient, google: FakeGoogleVerifier, google_on: Settings
) -> None:
    response = await complete_signup(client, google, "g-short", display_name="A")

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Refresh rotation and reuse detection
# ---------------------------------------------------------------------------
async def test_refreshing_returns_a_new_pair(
    client: httpx.AsyncClient, tokens: auth_service.TokenPair
) -> None:
    response = await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})

    assert response.status_code == 200
    body = response.json()
    assert body["refresh_token"] != tokens.refresh_token
    assert body["access_token"] != tokens.access_token


async def test_the_rotated_token_works_and_the_old_one_does_not(
    client: httpx.AsyncClient, tokens: auth_service.TokenPair
) -> None:
    rotated = (
        await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})
    ).json()

    reuse_old = await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})

    assert reuse_old.status_code == 401
    assert "sign in again" in reuse_old.json()["error"]["message"]
    # The new one is dead too: the whole family went.
    assert (
        await client.post("/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    ).status_code == 401


async def test_reusing_a_token_revokes_the_whole_family(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    tokens: auth_service.TokenPair,
) -> None:
    """The design decision, stated as a test.

    A replay of a stolen token and an honest client that lost the response are
    indistinguishable, so both revoke everything descended from that sign-in. A
    thief cannot keep using what they stole; the honest user signs in once more
    rather than being quietly shadowed by somebody holding a live token.
    """
    await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})
    await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})

    family = (
        (
            await db_session.execute(
                select(DeviceSession).where(DeviceSession.family_id.is_not(None))
            )
        )
        .scalars()
        .all()
    )

    assert family
    assert all(session.revoked_at is not None for session in family)
    assert any(
        session.revoked_reason == SessionRevocationReason.reuse_detected for session in family
    )


async def test_rotation_records_what_replaced_what(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    tokens: auth_service.TokenPair,
) -> None:
    """So a reuse event can be traced through the chain afterwards."""
    await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})

    original = await db_session.get(DeviceSession, tokens.session_id)

    assert original is not None
    assert original.revoked_reason == SessionRevocationReason.rotated
    assert original.replaced_by_id is not None


async def test_rotation_keeps_the_family_id(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    tokens: auth_service.TokenPair,
) -> None:
    await client.post("/v1/auth/refresh", json={"refresh_token": tokens.refresh_token})

    original = await db_session.get(DeviceSession, tokens.session_id)
    assert original is not None
    successor = await db_session.get(DeviceSession, original.replaced_by_id)

    assert successor is not None
    assert successor.family_id == original.family_id


async def test_an_unknown_refresh_token_is_refused(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/auth/refresh", json={"refresh_token": "nope"})

    assert response.status_code == 401


async def test_refresh_fails_for_a_banned_account(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    banned = await make_user(db_session, at=NYERI_TOWN, status=UserStatus.banned)
    pair = await auth_service.issue_tokens(db_session, user=banned, settings=settings)
    await db_session.flush()

    response = await client.post("/v1/auth/refresh", json={"refresh_token": pair.refresh_token})

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Sessions and logout
# ---------------------------------------------------------------------------
async def test_logging_out_kills_the_session(
    auth_client: httpx.AsyncClient, tokens: auth_service.TokenPair
) -> None:
    logout = await auth_client.post("/v1/auth/logout", json={"refresh_token": tokens.refresh_token})

    assert logout.status_code == 204
    # The access token stops working immediately, not in fifteen minutes.
    assert (await auth_client.get("/v1/me")).status_code == 401


async def test_logging_out_twice_still_succeeds(
    auth_client: httpx.AsyncClient, tokens: auth_service.TokenPair
) -> None:
    """Signing out is an outcome, not an operation: failing a retry would only
    make clients paper over it."""
    await auth_client.post("/v1/auth/logout", json={"refresh_token": tokens.refresh_token})
    second = await auth_client.post("/v1/auth/logout", json={"refresh_token": tokens.refresh_token})

    assert second.status_code == 204


async def test_logout_all_keeps_the_current_device_by_default(
    auth_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    user: User,
) -> None:
    """ "Sign out my other devices" must not sign out the phone in your hand."""
    for _ in range(3):
        await auth_service.issue_tokens(db_session, user=user, settings=settings)
    await db_session.flush()

    response = await auth_client.post("/v1/auth/logout-all", json={"keep_current_session": True})

    assert response.status_code == 200
    assert response.json()["sessions_revoked"] == 3
    assert (await auth_client.get("/v1/me")).status_code == 200


async def test_logout_all_can_include_the_current_device(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await auth_client.post("/v1/auth/logout-all", json={"keep_current_session": False})

    assert response.status_code == 200
    assert (await auth_client.get("/v1/me")).status_code == 401


async def test_sessions_list_marks_the_current_device(
    auth_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    tokens: auth_service.TokenPair,
    user: User,
) -> None:
    await auth_service.issue_tokens(
        db_session, user=user, settings=settings, device_name="Old Phone"
    )
    await db_session.flush()

    response = await auth_client.get("/v1/auth/sessions")

    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    current = [s for s in sessions if s["is_current"]]
    assert len(current) == 1
    assert current[0]["id"] == str(tokens.session_id)


async def test_a_session_never_carries_its_token(
    auth_client: httpx.AsyncClient,
) -> None:
    response = await auth_client.get("/v1/auth/sessions")

    rendered = response.text
    assert "refresh_token" not in rendered
    assert "access_token" not in rendered


async def test_old_sessions_are_evicted_past_the_limit(
    db_session: AsyncSession, settings: Settings, user: User
) -> None:
    """Otherwise every reinstall leaves a usable refresh token behind for a month."""
    for index in range(settings.max_sessions_per_user + 3):
        await auth_service.issue_tokens(
            db_session, user=user, settings=settings, device_name=f"Device {index}"
        )
    await db_session.flush()

    live = await db_session.scalar(
        select(func.count(DeviceSession.id)).where(
            DeviceSession.user_id == user.id, DeviceSession.revoked_at.is_(None)
        )
    )

    assert live is not None
    assert live <= settings.max_sessions_per_user


async def test_sessions_require_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/auth/sessions")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
