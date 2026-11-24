"""The media CDN: signed URLs and purging deleted media (decision U.2).

Bunny's API sits behind fakes here, as the SMS and push providers do: a recording
provider for the purge hook, and an httpx mock transport for the real client.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.config import Settings
from app.core.providers.cdn import (
    BunnyCdnProvider,
    NoCdnProvider,
    RecordingCdnProvider,
    build_cdn_provider,
    set_cdn_provider,
    sign_cdn_url,
    verify_cdn_url,
)
from app.core.providers.storage import MemoryStorageProvider, S3StorageProvider
from app.modules.media.models import MediaAsset, MediaPurpose, MediaStatus
from app.modules.media.service import variant_views

KEY = "test-zone-token-key"
BASE = "https://media.example.test"
VARIANT = f"public/post/{uuid.UUID(int=1)}/{'a' * 32}.webp"
URL = f"{BASE}/{VARIANT}"
NOW = 1_800_000_000.0  # a fixed moment, a whole number of hours since 1970
HOUR, WEEK = 3600, 604_800


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "app_env": "local",
        "secret_key": "test-secret",
        "database_url": "postgresql+asyncpg://user:pw@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "storage_provider": "s3",
        "storage_access_key_id": "id",
        "storage_secret_access_key": "secret",
        "storage_public_base_url": BASE,
        "bunny_token_key": KEY,
        "bunny_api_key": "account-key",
    }
    return Settings(_env_file=None, **(defaults | overrides))  # type: ignore[arg-type]


def _expires(url: str) -> int:
    return int(parse_qs(urlsplit(url).query)["expires"][0])


@pytest.fixture
def recording() -> Iterator[RecordingCdnProvider]:
    provider = RecordingCdnProvider()
    set_cdn_provider(provider)
    yield provider
    set_cdn_provider(None)


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------
def test_a_signed_url_carries_bunnys_token_and_an_expiry() -> None:
    signed = sign_cdn_url(URL, security_key=KEY, ttl_seconds=HOUR, now=NOW)

    query = parse_qs(urlsplit(signed).query)
    expires = int(query["expires"][0])
    digest = hmac.new(
        KEY.encode(), f"{urlsplit(URL).path}{expires}".encode(), hashlib.sha256
    ).digest()
    assert signed.startswith(URL + "?token=HS256-")
    assert query["token"][0] == "HS256-" + base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert "=" not in query["token"][0]
    assert verify_cdn_url(signed, security_key=KEY, now=NOW)


@pytest.mark.parametrize(
    "spoil",
    [
        lambda url: url.replace("token=HS256-", "token=HS256-x"),  # tampered token
        lambda url: url.replace("/public/post/", "/public/message/"),  # another path
        lambda url: url.replace(f"expires={_expires(url)}", f"expires={_expires(url) + HOUR}"),
        lambda url: url.split("?")[0],  # no token at all
    ],
)
def test_a_tampered_or_missing_token_fails(spoil: object) -> None:
    signed = sign_cdn_url(URL, security_key=KEY, ttl_seconds=HOUR, now=NOW)
    assert callable(spoil)
    assert not verify_cdn_url(spoil(signed), security_key=KEY, now=NOW)


def test_another_key_or_a_passed_expiry_fails() -> None:
    signed = sign_cdn_url(URL, security_key=KEY, ttl_seconds=HOUR, now=NOW)
    assert not verify_cdn_url(signed, security_key="another-zone", now=NOW)
    assert not verify_cdn_url(signed, security_key=KEY, now=_expires(signed) + 1)


def test_the_url_stays_the_same_within_the_hour() -> None:
    """Expiries round up to the hour, so repeated reads hand out one URL."""
    first = sign_cdn_url(URL, security_key=KEY, ttl_seconds=HOUR, now=NOW + 60)
    later = sign_cdn_url(URL, security_key=KEY, ttl_seconds=HOUR, now=NOW + 1800)
    assert first == later
    assert _expires(first) >= NOW + 60 + HOUR


# ---------------------------------------------------------------------------
# Lifetime by purpose
# ---------------------------------------------------------------------------
def test_public_media_signs_for_a_week_and_private_for_an_hour() -> None:
    storage = S3StorageProvider(_settings())
    public = storage.public_url(storage_key=VARIANT)
    private = storage.public_url(storage_key=VARIANT, private=True)

    import time

    now = time.time()
    assert WEEK <= _expires(public) - now <= WEEK + HOUR
    assert HOUR <= _expires(private) - now <= 2 * HOUR
    assert verify_cdn_url(public, security_key=KEY)


def test_without_a_token_key_the_cdn_url_is_plain() -> None:
    storage = S3StorageProvider(_settings(bunny_token_key=""))
    assert storage.public_url(storage_key=VARIANT) == URL


def _asset(purpose: MediaPurpose) -> MediaAsset:
    return MediaAsset(
        owner_id=uuid.UUID(int=1),
        purpose=purpose,
        status=MediaStatus.ready,
        declared_content_type="image/jpeg",
        variants={"320": {"key": VARIANT, "width": 320, "height": 240, "bytes": 1}},
    )


@pytest.mark.parametrize(
    ("purpose", "private"),
    [
        (MediaPurpose.post, False),
        (MediaPurpose.listing, False),
        (MediaPurpose.avatar, False),
        (MediaPurpose.cover, False),
        (MediaPurpose.message, True),
        (MediaPurpose.story, True),
        (MediaPurpose.group, True),
    ],
)
def test_the_lifetime_follows_the_purpose(purpose: MediaPurpose, private: bool) -> None:
    import time

    url = variant_views(_asset(purpose), S3StorageProvider(_settings()))["320"].url
    lifetime = _expires(url) - time.time()
    assert (lifetime <= 2 * HOUR) is private


def test_a_group_posts_photo_is_short_lived_though_its_purpose_is_post() -> None:
    import time

    url = variant_views(_asset(MediaPurpose.post), S3StorageProvider(_settings()), private=True)[
        "320"
    ].url
    assert _expires(url) - time.time() <= 2 * HOUR


# ---------------------------------------------------------------------------
# Purging
# ---------------------------------------------------------------------------
async def test_deleting_a_variant_purges_it_from_the_edge(recording: RecordingCdnProvider) -> None:
    storage = MemoryStorageProvider(settings=_settings())
    await storage.put_object(storage_key=VARIANT, data=b"x", content_type="image/webp")

    await storage.delete_object(storage_key=VARIANT)

    assert recording.purged == [URL]
    assert not await storage.object_exists(storage_key=VARIANT)


async def test_originals_are_never_served_so_never_purged(recording: RecordingCdnProvider) -> None:
    storage = MemoryStorageProvider(settings=_settings())
    await storage.delete_object(storage_key=f"original/post/{uuid.UUID(int=1)}/{'b' * 32}.jpg")
    assert recording.purged == []


async def test_without_a_cdn_nothing_is_purged(recording: RecordingCdnProvider) -> None:
    storage = MemoryStorageProvider(settings=_settings(storage_public_base_url=""))
    await storage.delete_object(storage_key=VARIANT)
    assert recording.purged == []


async def test_a_failed_purge_does_not_stop_the_deletion() -> None:
    set_cdn_provider(RecordingCdnProvider(fail=True))
    try:
        storage = MemoryStorageProvider(settings=_settings())
        await storage.put_object(storage_key=VARIANT, data=b"x", content_type="image/webp")
        await storage.delete_object(storage_key=VARIANT)
        assert not await storage.object_exists(storage_key=VARIANT)
    finally:
        set_cdn_provider(None)


async def test_bunny_is_asked_to_purge_the_url_with_the_account_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ok = await BunnyCdnProvider(_settings(), client=client).purge(URL)

    assert ok
    request = seen[0]
    assert (request.method, request.url.host, request.url.path) == (
        "POST",
        "api.bunny.net",
        "/purge",
    )
    assert request.url.params["url"] == URL
    assert request.headers["AccessKey"] == "account-key"


@pytest.mark.parametrize("status", [401, 500])
async def test_a_refused_purge_reports_failure(status: int) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    ) as client:
        assert not await BunnyCdnProvider(_settings(), client=client).purge(URL)


async def test_an_unreachable_bunny_reports_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert not await BunnyCdnProvider(_settings(), client=client).purge(URL)


def test_bunny_is_used_only_when_configured() -> None:
    assert isinstance(build_cdn_provider(_settings()), BunnyCdnProvider)
    assert isinstance(build_cdn_provider(_settings(bunny_api_key="")), NoCdnProvider)
    assert isinstance(build_cdn_provider(_settings(storage_public_base_url="")), NoCdnProvider)
