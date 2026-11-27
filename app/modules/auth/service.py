"""Authentication: Google sign-in, phone numbers proved by Firebase, tokens, and
device sessions.

**Google is the only way in** (decision A.2). A known Google account is signed
in; a new one gets a single-use signup token for `POST /v1/auth/signup`.

**A phone number is proved by Firebase, never by a code we send.** Firebase texts
the code and checks it on the phone; `add_phone` checks the token that proves it
and keeps only the number.

**Refresh tokens rotate, and reuse revokes the family.** See the docstring on
`DeviceSession` for why the family exists; `rotate_refresh_token` is where it is
enforced.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import execute_dml, run_after_commit
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    ServiceUnavailableError,
    UnauthenticatedError,
)
from app.core.providers.google import GoogleTokenVerifier, PhoneTokenVerifier
from app.core.realtime import SESSION_REVOKED, publish_after_commit
from app.core.security import (
    create_access_token,
    expires_in_seconds,
    generate_opaque_token,
    hash_secret,
    refresh_token_expiry,
)
from app.modules.auth.models import DeviceSession, SessionRevocationReason
from app.modules.auth.phone import normalise_phone_number
from app.modules.moderation import banlist
from app.modules.moderation.audit import record_audit_event
from app.modules.moderation.models import AuditAction
from app.modules.users.models import User, UserStatus
from app.modules.users.service import get_user_by_google_sub, touch_last_active

logger = logging.getLogger(__name__)

SIGNUP_TOKEN_PREFIX: Final = "signup"  # noqa: S105 — a key prefix, not a secret

# What a signup token's Redis value starts with: the Google account it proved.
_GOOGLE_SIGNUP_PREFIX: Final = "google:"

GOOGLE_REFUSED_MESSAGE: Final = "Google sign-in didn't work. Please try again."
PHONE_REFUSED_MESSAGE: Final = "That number couldn't be verified. Please try again."


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_in_seconds: int
    session_id: uuid.UUID


# ---------------------------------------------------------------------------
# Signup tokens
# ---------------------------------------------------------------------------
def _signup_key(token: str, settings: Settings) -> str:
    return f"{SIGNUP_TOKEN_PREFIX}:{hash_secret(token, settings)}"


async def _start_signup(redis: Redis, value: str, settings: Settings) -> str:
    """Issue a signup token for a Google account (`google:<sub>`)."""
    signup_token = generate_opaque_token()
    await redis.set(
        _signup_key(signup_token, settings), value, ex=settings.signup_token_ttl_seconds
    )
    return signup_token


async def consume_signup_token(redis: Redis, *, token: str, settings: Settings) -> str:
    """Exchange a signup token for the Google account (`sub`) it proved.

    Single-use and deleted on read, so a replayed token cannot create a second
    account. The identity lives in Redis rather than inside the token because a
    JWT is readable by anyone holding it.
    """
    expired = UnauthenticatedError("That signup session has expired. Please sign in again.")
    value = await redis.getdel(_signup_key(token, settings))
    if not value or not str(value).startswith(_GOOGLE_SIGNUP_PREFIX):
        # Nothing, or a phone signup started before decision A.2: sign in again.
        raise expired
    return str(value).removeprefix(_GOOGLE_SIGNUP_PREFIX)


# ---------------------------------------------------------------------------
# Google sign-in
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class GoogleSignIn:
    """Exactly one of `tokens` and `signup_token` is set: a known account is
    signed in, a new one gets a short-lived ticket to finish signing up."""

    tokens: TokenPair | None
    signup_token: str | None


async def sign_in_with_google(
    session: AsyncSession,
    redis: Redis,
    verifier: GoogleTokenVerifier,
    *,
    id_token: str,
    settings: Settings,
    device_name: str | None = None,
    device_platform: str | None = None,
    device_id: str | None = None,
) -> GoogleSignIn:
    """Sign in with the ID token Google gave the app, or start a signup.

    The answer is either tokens or a signup token, and a ban is refused with the
    answer an invalid token gets. Telling the caller whether
    the Google account has a Hoodora account is safe here: only the account's
    owner holds a valid token for it.
    """
    if not settings.google_client_id:
        raise ServiceUnavailableError("Google sign-in is not available")

    identity = await verifier.verify(id_token, audience=settings.google_client_id)
    if identity is None:
        raise UnauthenticatedError(GOOGLE_REFUSED_MESSAGE)

    device_id_hash = banlist.device_hash(device_id, settings) if device_id else None
    if await banlist.is_device_banned(session, device_id_hash) or await banlist.is_google_banned(
        session, identity.sub, settings
    ):
        logger.info("google_sign_in_refused", extra={"reason": "banned"})
        raise UnauthenticatedError(GOOGLE_REFUSED_MESSAGE)

    user = await get_user_by_google_sub(session, identity.sub)
    if user is None:
        signup_token = await _start_signup(
            redis, f"{_GOOGLE_SIGNUP_PREFIX}{identity.sub}", settings
        )
        return GoogleSignIn(tokens=None, signup_token=signup_token)

    _assert_can_sign_in(user)
    tokens = await issue_tokens(
        session,
        user=user,
        settings=settings,
        device_name=device_name,
        device_platform=device_platform,
        device_id_hash=device_id_hash,
    )
    await touch_last_active(session, user.id)
    return GoogleSignIn(tokens=tokens, signup_token=None)


# ---------------------------------------------------------------------------
# Adding a phone number, proved by Firebase (decision A.2)
# ---------------------------------------------------------------------------
async def add_phone(
    session: AsyncSession,
    verifier: PhoneTokenVerifier,
    *,
    user: User,
    firebase_id_token: str,
    settings: Settings,
) -> User:
    """Attach the number a Firebase phone sign-in just proved to the account.

    Jobs and the verified-neighbour badge need a proved number (decision A.1).
    Firebase sent the code and checked it on the phone; this checks the token
    that says so, and keeps only the number. Changing a number already held is
    not offered here.

    Saying that a number belongs to another account is safe once it is proved:
    the caller has just shown the number is theirs. A banned number is refused
    as an invalid proof would be.
    """
    if not settings.firebase_project_id:
        raise ServiceUnavailableError("Adding a phone number is not available")
    if user.phone_number is not None:
        raise ConflictError(
            "Your account already has a phone number",
            details={"reason": "phone_already_set"},
        )
    proved = await verifier.verify(
        firebase_id_token,
        project_id=settings.firebase_project_id,
        max_age_seconds=settings.phone_proof_max_age_seconds,
    )
    if proved is None:
        raise UnauthenticatedError(PHONE_REFUSED_MESSAGE)
    # Firebase gives E.164 already; this applies our own rules (a mobile number)
    # and the same stored form as every other number.
    phone_number = normalise_phone_number(proved.phone_number)
    if await banlist.is_phone_banned(session, phone_number, settings):
        logger.info("add_phone_refused", extra={"reason": "banned"})
        raise UnauthenticatedError(PHONE_REFUSED_MESSAGE)
    if await _find_active_user(session, phone_number) is not None:
        raise ConflictError(
            "That number belongs to another Hoodora account",
            details={"reason": "phone_in_use"},
        )

    user.phone_number = phone_number
    user.phone_verified_at = datetime.now(UTC)
    await session.flush()
    await record_audit_event(
        session,
        action=AuditAction.phone_added,
        actor_id=user.id,
        target_type="user",
        target_id=user.id,
    )
    logger.info("phone_added", extra={"user_id": str(user.id)})
    return user


async def _find_active_user(session: AsyncSession, phone_number: str) -> User | None:
    statement = select(User).where(User.phone_number == phone_number, User.deleted_at.is_(None))
    return (await session.execute(statement)).scalar_one_or_none()


def _assert_can_sign_in(user: User) -> None:
    """A banned account cannot sign in; a suspended one still can.

    Suspension restricts what a user may do, not whether they may look. Blocking
    sign-in entirely would also stop them reading why they were suspended or
    exporting their data, both of which they are entitled to.
    """
    if user.status == UserStatus.banned:
        raise ForbiddenError("This account has been banned")


# ---------------------------------------------------------------------------
# Sessions and tokens
# ---------------------------------------------------------------------------
async def issue_tokens(
    session: AsyncSession,
    *,
    user: User,
    settings: Settings,
    device_name: str | None = None,
    device_platform: str | None = None,
    family_id: uuid.UUID | None = None,
    device_id_hash: str | None = None,
) -> TokenPair:
    """Create a device session and its token pair.

    `family_id` is supplied when rotating, so the new session stays part of the
    chain that began at sign-in; omitted, a fresh family starts.
    """
    await _evict_oldest_sessions(session, user_id=user.id, settings=settings)

    now = datetime.now(UTC)
    refresh_token = generate_opaque_token()
    device_session = DeviceSession(
        user_id=user.id,
        refresh_token_hash=hash_secret(refresh_token, settings),
        family_id=family_id or uuid.uuid4(),
        device_name=device_name,
        device_platform=device_platform,
        device_id_hash=device_id_hash,
        expires_at=refresh_token_expiry(settings, now),
        last_used_at=now,
    )
    session.add(device_session)
    await session.flush()

    access_token, access_expires_at = create_access_token(
        user_id=user.id,
        session_id=device_session.id,
        settings=settings,
        now=now,
    )
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_in_seconds=expires_in_seconds(access_expires_at, now),
        session_id=device_session.id,
    )


async def rotate_refresh_token(
    session: AsyncSession,
    *,
    refresh_token: str,
    settings: Settings,
    device_name: str | None = None,
    device_platform: str | None = None,
) -> TokenPair:
    """Exchange a refresh token for a new pair.

    The three failure cases are deliberately different:

    * **Unknown token** — never existed or the signing key rotated. Refused.
    * **Already consumed** — the token was rotated away. This is either a replay
      of a stolen token or an honest client that lost the response, and the two
      are indistinguishable, so the whole family is revoked. A thief loses the
      session they stole; the honest user signs in again once, instead of being
      quietly shadowed by someone else holding a valid token.
    * **Expired or revoked** — refused without touching the family.
    """
    token_hash = hash_secret(refresh_token, settings)
    statement = select(DeviceSession).where(DeviceSession.refresh_token_hash == token_hash)
    device_session = (await session.execute(statement)).scalar_one_or_none()

    if device_session is None:
        raise UnauthenticatedError("That refresh token is not valid")

    now = datetime.now(UTC)

    if device_session.revoked_reason == SessionRevocationReason.rotated:
        await _revoke_family(
            session,
            family_id=device_session.family_id,
            reason=SessionRevocationReason.reuse_detected,
            now=now,
        )
        logger.warning(
            "refresh_token_reuse_detected",
            extra={"user_id": str(device_session.user_id)},
        )
        await record_audit_event(
            session,
            action=AuditAction.refresh_token_reuse_detected,
            actor_id=device_session.user_id,
            target_type="session_family",
            target_id=device_session.family_id,
        )
        # Committed before raising, and this is the whole point of the branch.
        # The request session is a unit of work that rolls back on an exception,
        # so without this commit the revocation would be discarded by the very
        # error that reports it: the reused token would be refused while every
        # other token in the family kept working — which is precisely the
        # situation reuse detection exists to prevent. Verified by
        # `test_reusing_a_token_revokes_the_whole_family`.
        await session.commit()
        # The explicit commit bypasses the request's own after-commit step, so
        # the socket-closing announcement is sent here.
        await run_after_commit(session)
        raise UnauthenticatedError(
            "This session has been ended for your security. Please sign in again."
        )

    if not device_session.is_usable(now):
        raise UnauthenticatedError("That session has expired. Please sign in again.")

    user = await session.get(User, device_session.user_id)
    if user is None or user.deleted_at is not None:
        raise UnauthenticatedError("That session is no longer valid")
    _assert_can_sign_in(user)

    device_session.revoked_at = now
    device_session.revoked_reason = SessionRevocationReason.rotated

    tokens = await issue_tokens(
        session,
        user=user,
        settings=settings,
        device_name=device_name or device_session.device_name,
        device_platform=device_platform or device_session.device_platform,
        family_id=device_session.family_id,
        device_id_hash=device_session.device_id_hash,
    )
    device_session.replaced_by_id = tokens.session_id
    await touch_last_active(session, user.id)
    return tokens


def _announce_revoked(
    session: AsyncSession, *, user_id: uuid.UUID, session_ids: list[uuid.UUID]
) -> None:
    """Close open sockets for these sessions once the revocation commits.

    An HTTP request with a revoked session is refused on its next call, but a
    WebSocket authenticated before the revocation has no next call — it would
    keep receiving messages until its access token expired. Rotation is not
    announced: it is routine, and the client re-authenticates its socket in-band.
    """
    if session_ids:
        publish_after_commit(
            session,
            [user_id],
            SESSION_REVOKED,
            {"session_ids": [str(session_id) for session_id in session_ids]},
        )


async def _revoke_family(
    session: AsyncSession,
    *,
    family_id: uuid.UUID,
    reason: SessionRevocationReason,
    now: datetime,
) -> int:
    statement = select(DeviceSession).where(
        DeviceSession.family_id == family_id, DeviceSession.revoked_at.is_(None)
    )
    revoked: list[DeviceSession] = list((await session.execute(statement)).scalars())
    for device_session in revoked:
        device_session.revoked_at = now
        device_session.revoked_reason = reason
    if revoked:
        _announce_revoked(
            session,
            user_id=revoked[0].user_id,
            session_ids=[device_session.id for device_session in revoked],
        )
    return len(revoked)


async def _evict_oldest_sessions(
    session: AsyncSession, *, user_id: uuid.UUID, settings: Settings
) -> None:
    """Keep a user's live session count under the configured limit.

    Oldest first, so the device being signed in right now survives. Without this,
    every reinstall leaves a usable refresh token behind for thirty days.
    """
    live = (
        (
            await session.execute(
                select(DeviceSession)
                .where(
                    DeviceSession.user_id == user_id,
                    DeviceSession.revoked_at.is_(None),
                    DeviceSession.expires_at > datetime.now(UTC),
                )
                .order_by(DeviceSession.last_used_at.asc())
            )
        )
        .scalars()
        .all()
    )
    excess = len(live) - (settings.max_sessions_per_user - 1)
    if excess <= 0:
        return

    now = datetime.now(UTC)
    for device_session in live[:excess]:
        device_session.revoked_at = now
        device_session.revoked_reason = SessionRevocationReason.max_sessions
    _announce_revoked(
        session,
        user_id=user_id,
        session_ids=[device_session.id for device_session in live[:excess]],
    )


async def logout(session: AsyncSession, *, refresh_token: str, settings: Settings) -> None:
    """End one device's session.

    Succeeds silently for a token that is already gone: logging out is an
    outcome, not an operation, and failing a retry would only make clients
    paper over it.
    """
    token_hash = hash_secret(refresh_token, settings)
    statement = select(DeviceSession).where(DeviceSession.refresh_token_hash == token_hash)
    device_session = (await session.execute(statement)).scalar_one_or_none()
    if device_session is None or device_session.revoked_at is not None:
        return

    device_session.revoked_at = datetime.now(UTC)
    device_session.revoked_reason = SessionRevocationReason.logout
    _announce_revoked(session, user_id=device_session.user_id, session_ids=[device_session.id])


async def logout_all(
    session: AsyncSession, *, user: User, keep_session_id: uuid.UUID | None = None
) -> int:
    """Revoke every session, optionally sparing the one making the request.

    The spare exists so "sign out my other devices" does not also sign out the
    phone the user is holding.
    """
    statement = select(DeviceSession).where(
        DeviceSession.user_id == user.id, DeviceSession.revoked_at.is_(None)
    )
    now = datetime.now(UTC)
    revoked_ids: list[uuid.UUID] = []
    for device_session in (await session.execute(statement)).scalars():
        if keep_session_id is not None and device_session.id == keep_session_id:
            continue
        device_session.revoked_at = now
        device_session.revoked_reason = SessionRevocationReason.logout_all
        revoked_ids.append(device_session.id)

    revoked = len(revoked_ids)
    _announce_revoked(session, user_id=user.id, session_ids=revoked_ids)
    if revoked:
        await record_audit_event(
            session,
            action=AuditAction.sessions_revoked,
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            context={"count": revoked, "kept_current": keep_session_id is not None},
        )
    return revoked


async def list_sessions(session: AsyncSession, *, user_id: uuid.UUID) -> list[DeviceSession]:
    """Live sessions, newest first, for the "where am I signed in?" screen."""
    statement = (
        select(DeviceSession)
        .where(
            DeviceSession.user_id == user_id,
            DeviceSession.revoked_at.is_(None),
            DeviceSession.expires_at > datetime.now(UTC),
        )
        .order_by(DeviceSession.last_used_at.desc())
    )
    return list((await session.execute(statement)).scalars().all())


async def get_session_for_access(
    session: AsyncSession, *, session_id: uuid.UUID
) -> DeviceSession | None:
    """Load a session named by an access token, to confirm it is still live.

    This is what makes "log out this device" take effect on access tokens as well
    as refresh tokens. It costs one indexed lookup per authenticated request,
    which is the price of logout meaning something before the access token's
    fifteen minutes are up.
    """
    return await session.get(DeviceSession, session_id)


async def revoke_sessions_for_deleted_account(session: AsyncSession, *, user_id: uuid.UUID) -> None:
    statement = select(DeviceSession).where(
        DeviceSession.user_id == user_id, DeviceSession.revoked_at.is_(None)
    )
    now = datetime.now(UTC)
    revoked_ids: list[uuid.UUID] = []
    for device_session in (await session.execute(statement)).scalars():
        device_session.revoked_at = now
        device_session.revoked_reason = SessionRevocationReason.account_deleted
        revoked_ids.append(device_session.id)
    # Every session's installation hash, not only the live ones: it links the
    # account to a device, and a purged account has nothing left to ban.
    await execute_dml(
        session,
        update(DeviceSession)
        .where(DeviceSession.user_id == user_id, DeviceSession.device_id_hash.is_not(None))
        .values(device_id_hash=None),
    )
    _announce_revoked(session, user_id=user_id, session_ids=revoked_ids)


async def revoke_sessions_for_moderation(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Sign a banned account out everywhere, at once — open sockets included."""
    statement = select(DeviceSession).where(
        DeviceSession.user_id == user_id, DeviceSession.revoked_at.is_(None)
    )
    now = datetime.now(UTC)
    revoked_ids: list[uuid.UUID] = []
    for device_session in (await session.execute(statement)).scalars():
        device_session.revoked_at = now
        device_session.revoked_reason = SessionRevocationReason.admin_action
        revoked_ids.append(device_session.id)
    _announce_revoked(session, user_id=user_id, session_ids=revoked_ids)
    return len(revoked_ids)
