"""The media CDN: signing URLs, and purging deleted media (decision U.2).

Media is served through a Bunny pull zone with token authentication, so every
URL carries a signature and an expiry, and the edge refuses one without a valid
token. Signing is a local HMAC, like a presigned URL: no network call, no SDK.

The pull zone ignores query strings in its cache key, so one cached copy of a
variant serves every viewer whatever their token says. When media is deleted,
its variants are purged from the edge in the same job that deletes them from
storage (see `StorageProvider.delete_object`). If a purge fails, a deleted image
is still never signed again, so it stops loading once the last token handed out
for it expires: a week at most.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from urllib.parse import parse_qs, urlsplit

import httpx

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

# Expiries are rounded up to this, so a URL stays the same for the hour and an
# HTTP cache keyed on the full URL still works.
EXPIRY_STEP_SECONDS = 3600


def _token(security_key: str, path: str, expires: int) -> str:
    """Bunny's advanced token: "HS256-" + base64url(HMAC-SHA256(key, path + expires)),
    unpadded. No IP is bound and the URL has no other parameters to sign."""
    digest = hmac.new(security_key.encode(), f"{path}{expires}".encode(), hashlib.sha256).digest()
    return "HS256-" + base64.urlsafe_b64encode(digest).decode().rstrip("=")


def sign_cdn_url(url: str, *, security_key: str, ttl_seconds: int, now: float | None = None) -> str:
    """`url` with a token valid for at least `ttl_seconds`."""
    moment = time.time() if now is None else now
    expires = math.ceil((moment + ttl_seconds) / EXPIRY_STEP_SECONDS) * EXPIRY_STEP_SECONDS
    path = urlsplit(url).path
    return f"{url}?token={_token(security_key, path, expires)}&expires={expires}"


def verify_cdn_url(url: str, *, security_key: str, now: float | None = None) -> bool:
    """What the edge checks, for tests: the token matches the path and expiry, and
    the expiry has not passed."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    try:
        token, expires = query["token"][0], int(query["expires"][0])
    except (KeyError, IndexError, ValueError):
        return False
    moment = time.time() if now is None else now
    expected = _token(security_key, parts.path, expires)
    return hmac.compare_digest(token, expected) and expires > moment


# ---------------------------------------------------------------------------
# Purging
# ---------------------------------------------------------------------------
class CdnProvider(Protocol):
    name: str

    async def purge(self, url: str) -> bool:
        """Drop `url` from every edge. True when the CDN accepted the purge."""
        ...


class NoCdnProvider:
    """No CDN configured: nothing is cached at an edge, so nothing to purge."""

    name = "none"

    async def purge(self, url: str) -> bool:
        return True


@dataclass
class RecordingCdnProvider:
    """For tests: remembers what it was asked to purge."""

    name: str = "recording"
    purged: list[str] = field(default_factory=list)
    fail: bool = False

    async def purge(self, url: str) -> bool:
        if self.fail:
            return False
        self.purged.append(url)
        return True


class BunnyCdnProvider:
    """Purges through Bunny's API (`POST /purge?url=`), with the account API key."""

    name = "bunny"
    endpoint = "https://api.bunny.net/purge"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = settings.bunny_api_key.get_secret_value()
        self._client = client

    async def purge(self, url: str) -> bool:
        headers = {"AccessKey": self._api_key, "Accept": "application/json"}
        params = {"url": url, "async": "false"}
        try:
            if self._client is not None:
                response = await self._client.post(self.endpoint, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                    response = await client.post(self.endpoint, params=params, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning(
                "cdn_purge_failed", extra={"provider": self.name, "error": type(exc).__name__}
            )
            return False
        if response.status_code >= 400:
            logger.warning(
                "cdn_purge_refused", extra={"provider": self.name, "status": response.status_code}
            )
            return False
        return True


def build_cdn_provider(settings: Settings) -> CdnProvider:
    if settings.bunny_api_key.get_secret_value() and settings.storage_public_base_url:
        return BunnyCdnProvider(settings)
    return NoCdnProvider()


_provider: CdnProvider | None = None


def get_cdn_provider() -> CdnProvider:
    """The process-wide provider, like the push provider."""
    global _provider
    if _provider is None:
        from app.core.config import get_settings

        _provider = build_cdn_provider(get_settings())
    return _provider


def set_cdn_provider(provider: CdnProvider | None) -> None:
    """Override the provider. Used by tests; `None` restores the default."""
    global _provider
    _provider = provider


async def purge_variant(settings: Settings, storage_key: str) -> None:
    """After a variant is deleted from storage, drop it from the edge too. Only
    processed variants (`public/…`) are ever served through the CDN."""
    base = settings.storage_public_base_url.rstrip("/")
    if not base or not storage_key.startswith("public/"):
        return
    if not await get_cdn_provider().purge(f"{base}/{storage_key}"):
        # Logged, not raised: the object is gone from storage either way, and the
        # API will never sign this key again (see the module docstring).
        logger.warning("cdn_purge_incomplete", extra={"storage_key": storage_key})
