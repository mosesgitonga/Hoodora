"""Request and response models for authentication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DeviceIn(BaseModel):
    """Optional device description, shown back on the sessions screen.

    Client-supplied and therefore untrusted. It is only ever displayed to the
    account's own owner so they can recognise their devices, and is never used
    for any authorisation decision.
    """

    device_name: str | None = Field(default=None, max_length=100, examples=["Pixel 6a"])
    device_platform: Literal["android", "ios", "web", "other"] | None = None
    device_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description=(
            "A random ID the app generates once per installation and keeps. Stored "
            "only as a keyed hash, so that a ban can reach the devices an account "
            "used. Never shown back, and never used to sign anyone in."
        ),
    )


class AddPhoneIn(BaseModel):
    """Proof of a number from Firebase (decision A.2)."""

    firebase_id_token: str = Field(
        min_length=20,
        max_length=4096,
        description=(
            "The ID token Firebase gave the app when it signed in with the number "
            "and the code Firebase texted to it. Only the number is taken from it."
        ),
    )


class AuthMethodsOut(BaseModel):
    """How someone can sign in or sign up right now."""

    phone: bool = Field(
        default=False,
        description="Always false: Google is the only way to sign in (decision A.2).",
    )
    google: bool = Field(description="Whether Google sign-in is switched on.")
    google_client_id: str | None = Field(
        default=None,
        description=(
            "The client ID to hand Google as the server client ID, so the ID token "
            "it issues is for this server. Null when Google sign-in is off. Not a "
            "secret: every copy of the app holds it."
        ),
        examples=["1234567890-abc123.apps.googleusercontent.com"],
    )


class GoogleSignInIn(DeviceIn):
    id_token: str = Field(
        min_length=20,
        max_length=4096,
        description=(
            "The ID token Google gave the app at sign-in. Only the account's Google "
            "ID is taken from it; its email, name and photo are not kept."
        ),
    )


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — the OAuth scheme name
    expires_in_seconds: int = Field(description="Lifetime of the access token.")


class SignInOut(BaseModel):
    """Either signed in, or cleared to sign up: the answer to
    `POST /v1/auth/google`."""

    status: Literal["signed_in", "signup_required"]
    tokens: TokenPairOut | None = Field(
        default=None, description="Present when `status` is `signed_in`."
    )
    signup_token: str | None = Field(
        default=None,
        description=(
            "Present when `status` is `signup_required`. Single-use, short-lived, "
            "and must be passed to `POST /v1/auth/signup`."
        ),
    )


class SignupIn(DeviceIn):
    """Completing signup after a number or a Google account is verified.

    Consents are separate booleans rather than one "I agree" flag, because the
    Data Protection Act requires consent to be specific and freely given. Marketing
    is optional and defaults to false; bundling it in would make it not a choice.
    """

    signup_token: str = Field(description="From `POST /v1/auth/google`.")
    display_name: str = Field(min_length=2, max_length=50, examples=["Wanjiku M."])

    is_adult: Literal[True] = Field(
        description=(
            "Must be `true`. The service is for adults only, which keeps the "
            "Act's parental-consent requirements out of scope."
        )
    )
    accept_terms: Literal[True] = Field(description="Must be `true`.")
    accept_privacy_policy: Literal[True] = Field(description="Must be `true`.")
    accept_location_use: Literal[True] = Field(
        description=(
            "Must be `true`. Everything in Hoodora is scoped by location, so "
            "there is no version of the product that works without it."
        )
    )
    accept_marketing: bool = Field(
        default=False, description="Optional, and may be withdrawn at any time."
    )


class SignupOut(BaseModel):
    tokens: TokenPairOut
    user_id: uuid.UUID


class RefreshIn(DeviceIn):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str


class LogoutAllIn(BaseModel):
    keep_current_session: bool = Field(
        default=True,
        description=(
            "Keep the session making this request, so signing out other devices "
            "does not sign out the phone in your hand."
        ),
    )


class LogoutAllOut(BaseModel):
    sessions_revoked: int


class SessionOut(BaseModel):
    """One signed-in device. Carries no token and no location."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_name: str | None
    device_platform: str | None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    is_current: bool = False
