"""Authentication endpoints. Google is the only way to sign in (decision A.2).

Rate limits here are the strictest in the product and fail closed: these are the
endpoints an unauthenticated caller can reach.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.db import SessionDep
from app.core.errors import ConflictError, UnauthenticatedError
from app.core.providers.google import GoogleTokenVerifier, get_google_verifier
from app.core.ratelimit import rate_limit
from app.core.redis import get_redis
from app.modules.auth import service as auth_service
from app.modules.auth.dependencies import CurrentUser, current_session_id
from app.modules.auth.schemas import (
    AuthMethodsOut,
    GoogleSignInIn,
    LogoutAllIn,
    LogoutAllOut,
    LogoutIn,
    RefreshIn,
    SessionOut,
    SignInOut,
    SignupIn,
    SignupOut,
    TokenPairOut,
)
from app.modules.moderation import banlist
from app.modules.users import service as users_service
from app.modules.users.models import ConsentType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
RedisDep = Annotated[Redis, Depends(get_redis)]
GoogleDep = Annotated[GoogleTokenVerifier, Depends(get_google_verifier)]


def _to_token_pair(pair: auth_service.TokenPair) -> TokenPairOut:
    return TokenPairOut(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in_seconds=pair.access_expires_in_seconds,
    )


@router.get(
    "/methods",
    response_model=AuthMethodsOut,
    summary="How to sign in",
    description=(
        "Whether Google sign-in is on, and the client ID the app needs for it. "
        "Google is the only way to sign in (decision A.2); `phone` is always false, "
        "for app builds that still offer a number."
    ),
)
async def sign_in_methods(settings: SettingsDep) -> AuthMethodsOut:
    client_id = settings.google_client_id or None
    return AuthMethodsOut(phone=False, google=client_id is not None, google_client_id=client_id)


@router.post(
    "/google",
    response_model=SignInOut,
    summary="Sign in with Google",
    description=(
        "Takes the ID token Google gave the app. A Google account with a Hoodora "
        "account receives tokens; a new one receives a single-use `signup_token` "
        "for `POST /v1/auth/signup`. Only the account's Google ID is kept. 503 "
        "when Google sign-in is off."
    ),
    dependencies=[
        Depends(
            rate_limit(
                bucket="google_sign_in_ip",
                limit=30,
                window_seconds=3600,
                scope="ip",
                fail_open=False,
            )
        )
    ],
)
async def sign_in_with_google(
    payload: GoogleSignInIn,
    session: SessionDep,
    redis: RedisDep,
    verifier: GoogleDep,
    settings: SettingsDep,
) -> SignInOut:
    outcome = await auth_service.sign_in_with_google(
        session,
        redis,
        verifier,
        id_token=payload.id_token,
        settings=settings,
        device_name=payload.device_name,
        device_platform=payload.device_platform,
        device_id=payload.device_id,
    )
    if outcome.tokens is not None:
        return SignInOut(status="signed_in", tokens=_to_token_pair(outcome.tokens))
    return SignInOut(status="signup_required", signup_token=outcome.signup_token)


@router.post(
    "/signup",
    response_model=SignupOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    description=(
        "Completes signup for a Google account verified by `POST /v1/auth/google`. "
        "Requires an 18+ confirmation and "
        "explicit consent to the terms, privacy policy, and location use; "
        "marketing consent is optional."
    ),
    dependencies=[
        Depends(
            rate_limit(
                bucket="signup_ip",
                limit=10,
                window_seconds=86_400,
                scope="ip",
                fail_open=False,
            )
        )
    ],
)
async def signup(
    payload: SignupIn,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> SignupOut:
    google_sub = await auth_service.consume_signup_token(
        redis, token=payload.signup_token, settings=settings
    )
    device_id_hash = banlist.device_hash(payload.device_id, settings) if payload.device_id else None
    if await banlist.is_device_banned(session, device_id_hash):
        raise UnauthenticatedError("That signup session has expired. Please sign in again.")

    # The token is single-use and already consumed, so a race between two
    # simultaneous signups cannot create two accounts. This covers the other
    # order: a Google account that gained an account between verifying and
    # signing up.
    if await users_service.get_user_by_google_sub(session, google_sub) is not None:
        raise ConflictError("An account already exists for that Google account")

    granted = {
        ConsentType.terms,
        ConsentType.privacy_policy,
        ConsentType.location_use,
    }
    if payload.accept_marketing:
        granted.add(ConsentType.marketing)

    user = await users_service.create_user(
        session,
        google_sub=google_sub,
        display_name=payload.display_name,
        settings=settings,
        granted_consents=granted,
    )
    tokens = await auth_service.issue_tokens(
        session,
        user=user,
        settings=settings,
        device_name=payload.device_name,
        device_platform=payload.device_platform,
        device_id_hash=device_id_hash,
    )
    return SignupOut(tokens=_to_token_pair(tokens), user_id=user.id)


@router.post(
    "/refresh",
    response_model=TokenPairOut,
    summary="Exchange a refresh token",
    description=(
        "Rotates the refresh token and issues a new access token. Presenting a "
        "token that has already been rotated revokes every session descended from "
        "the same sign-in, because a replay and a client that lost the response "
        "are indistinguishable."
    ),
    dependencies=[
        Depends(rate_limit(bucket="refresh_ip", limit=120, window_seconds=3600, scope="ip"))
    ],
)
async def refresh(payload: RefreshIn, session: SessionDep, settings: SettingsDep) -> TokenPairOut:
    tokens = await auth_service.rotate_refresh_token(
        session,
        refresh_token=payload.refresh_token,
        settings=settings,
        device_name=payload.device_name,
        device_platform=payload.device_platform,
    )
    return _to_token_pair(tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out this device",
    description=(
        "Revokes the session behind the given refresh token. Succeeds even if the "
        "token is already gone, so a client retrying on a flaky connection is not "
        "left unable to complete a sign-out."
    ),
)
async def logout(payload: LogoutIn, session: SessionDep, settings: SettingsDep) -> None:
    await auth_service.logout(session, refresh_token=payload.refresh_token, settings=settings)


@router.post(
    "/logout-all",
    response_model=LogoutAllOut,
    summary="Sign out everywhere",
    description="Revokes every session for the account, optionally keeping this one.",
)
async def logout_all(
    payload: LogoutAllIn,
    user: CurrentUser,
    request: Request,
    session: SessionDep,
) -> LogoutAllOut:
    keep = current_session_id(request) if payload.keep_current_session else None
    revoked = await auth_service.logout_all(session, user=user, keep_session_id=keep)
    return LogoutAllOut(sessions_revoked=revoked)


@router.get(
    "/sessions",
    response_model=list[SessionOut],
    summary="List signed-in devices",
    description=(
        "Every live session for the account, newest first, so a user can spot a "
        "device they do not recognise."
    ),
)
async def list_sessions(
    user: CurrentUser, request: Request, session: SessionDep
) -> list[SessionOut]:
    current_id = current_session_id(request)
    sessions = await auth_service.list_sessions(session, user_id=user.id)
    return [
        SessionOut(
            id=device.id,
            device_name=device.device_name,
            device_platform=device.device_platform,
            created_at=device.created_at,
            last_used_at=device.last_used_at,
            expires_at=device.expires_at,
            is_current=device.id == current_id,
        )
        for device in sessions
    ]


__all__ = ["router"]
