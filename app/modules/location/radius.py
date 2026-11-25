"""The adaptive radius engine.

Each user sees a different distance, chosen so that their feed holds roughly the
same number of people wherever they live. In a dense estate the radius shrinks
until the feed is genuinely local; out in the countryside it widens until there is
something to read.

**Computed per cell, not per user.** The unit of computation is the viewer's H3
res-8 cell, so everyone in that cell shares one answer and one cache entry. Per
user it would be the same arithmetic repeated thousands of times for an identical
result, and it would make the radius a function of *who* is asking rather than
*where* — which would leak something about the user.

**How it works.** Rings are walked outward from the viewer's cell, accumulating
two counts the density worker precomputed: active users, and recent posts
(decision T.2). The radius is the first ring where *both* reach their targets:
enough people, and enough recent posts for there to be something to read. That
ring is converted to kilometres using real H3 geometry, then clamped to the
feature's bounds. Which condition needed the last ring is kept as `limited_by`.

**Only the feed radius is computed.** Every other feature is a multiple of it, as
the brief specifies, so the expensive part happens once and the rest is
arithmetic. That also means features widen and narrow together as an area fills
up, instead of drifting apart.

**Hysteresis.** A radius that moves every fifteen minutes would reshuffle the feed
every fifteen minutes, which reads to a user as a bug rather than as adaptation.
So a cached ring is kept until a count says otherwise, by the configured ratio
(0.2) on each condition:

- **Grow** when either count inside the cached ring falls below 80% of its target:
  out to the first ring where both are met.
- **Shrink** only when both counts reach 120% of their targets inside a smaller
  ring: in to the first ring where both have that margin.
- **Otherwise keep** the cached ring.

A burst of posts cannot pull the radius in unless the people are comfortably
there too, and a quiet week does not push it out until it is clearly short.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal, cast

from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RadiusFeature, RadiusRule, Settings
from app.core.redis import CACHE_ERRORS
from app.modules.location import cells
from app.modules.location.models import CellActivity

logger = logging.getLogger(__name__)

CACHE_PREFIX = "radius:feed"

RadiusSource = Literal["computed", "cached", "stabilised"]

LimitedBy = Literal["users", "posts", "both", "floor", "ceiling"]
"""What set the feed radius: the condition that needed the last ring, both of
them, or a bound (the floor already held both; the ceiling cut the walk short).
For logs and debugging; never sent to the app."""

_LIMITED_BY: frozenset[str] = frozenset(("users", "posts", "both", "floor", "ceiling"))


@dataclass(frozen=True, slots=True)
class RadiusResult:
    """One feature's radius, with enough context to explain itself."""

    feature: RadiusFeature
    radius_km: float
    active_users_counted: int
    rings_expanded: int
    reached_target: bool
    clamped_to_minimum: bool
    clamped_to_maximum: bool
    source: RadiusSource
    recent_posts_counted: int = 0
    """Counted recent posts inside the feed's ring (decision T.2)."""
    limited_by: LimitedBy = "users"

    @property
    def radius_m(self) -> int:
        """Metres, for `ST_DWithin`."""
        return round(self.radius_km * 1000)

    def display_km(self, rounding_km: float) -> float:
        """Rounded up for display. See `rounded_for_display`."""
        return rounded_for_display(self.radius_km, rounding_km)


def rounded_for_display(radius_km: float, rounding_km: float) -> float:
    """A radius as people are told it: rounded *up* to the next step, so the app
    shows "3 km" rather than "2.87 km". The one rule for every radius a response
    carries.

    Up, so "within X km" holds for everything shown: a 2.2 km reach reads 2.5,
    never 2, which would be contradicted by a post 2.1 km away.

    Rounded at all because an exact radius is a direct read-out of how dense the
    caller's own immediate area is, which is information about their neighbours
    rather than about them (decision 1.19).
    """
    # The tolerance keeps a radius that is a whole step, give or take float
    # error (1.5000000001), from being pushed up a step.
    steps = math.ceil(radius_km / rounding_km - 1e-9)
    # Never down to nothing; the smallest meaningful answer is one step.
    return max(rounding_km, round(steps * rounding_km, 3))


@dataclass(frozen=True, slots=True)
class _FeedRadius:
    """The computed feed radius before per-feature derivation."""

    radius_km: float
    """The feed's actual radius, already clamped to the feed's own bounds. Other
    features multiply this rather than the raw value, because the brief's
    "2 x feed radius" means twice the radius the feed really uses."""

    raw_ring_km: float
    """The unclamped distance the ring walk reached. Kept only so the result can
    report honestly whether a clamp was applied; a pre-clamped value would make
    every dense area look as though it had landed naturally on the minimum."""

    active_users_counted: int
    recent_posts_counted: int
    rings_expanded: int
    reached_target: bool
    limited_by: LimitedBy
    source: RadiusSource


@dataclass(frozen=True, slots=True)
class _RingTotals:
    """Running totals out from the anchor: index k counts everything within k
    rings, so the counts inside any candidate radius are one lookup."""

    users: tuple[int, ...]
    posts: tuple[int, ...]
    target_users: int
    target_posts: int

    def meets(self, k: int, factor: float = 1.0) -> bool:
        """Both conditions hold inside ring k, at `factor` times their targets."""
        return (
            self.users[k] >= self.target_users * factor
            and self.posts[k] >= self.target_posts * factor
        )

    def first_meeting(self, factor: float = 1.0) -> int | None:
        """The first ring where both hold, or None if none does in range."""
        for k in range(len(self.users)):
            if self.meets(k, factor):
                return k
        return None

    def binding(self, k: int, factor: float = 1.0) -> LimitedBy:
        """Which condition needed ring k: the one (or both) still short one ring
        in. Ring 0 needed no walk at all, so both are reported."""
        if k == 0:
            return "both"
        users_short = self.users[k - 1] < self.target_users * factor
        posts_short = self.posts[k - 1] < self.target_posts * factor
        if users_short and posts_short:
            return "both"
        return "posts" if posts_short else "users"


@dataclass(frozen=True, slots=True)
class _CachedRadius:
    ring: int
    limited_by: LimitedBy


class RadiusEngine:
    """Computes and caches radii for one anchor cell at a time."""

    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings

    # -- Public API ----------------------------------------------------------
    async def radius_for(self, feature: RadiusFeature, anchor_cell_res8: int) -> RadiusResult:
        feed = await self._feed_radius(anchor_cell_res8)
        return self._derive(feature, feed)

    async def all_radii(self, anchor_cell_res8: int) -> dict[RadiusFeature, RadiusResult]:
        """Every feature's radius from one density computation."""
        feed = await self._feed_radius(anchor_cell_res8)
        return {feature: self._derive(feature, feed) for feature in RadiusFeature}

    # -- Derivation ----------------------------------------------------------
    def _derive(self, feature: RadiusFeature, feed: _FeedRadius) -> RadiusResult:
        rule = self._settings.radius_rules[feature]
        # The feed compares against the unclamped ring distance; every other
        # feature is a multiple of the feed's clamped radius.
        raw_km = (
            feed.raw_ring_km
            if rule.feed_multiplier is None
            else feed.radius_km * rule.feed_multiplier
        )
        clamped_km = min(max(raw_km, rule.min_km), rule.max_km)
        return RadiusResult(
            feature=feature,
            radius_km=clamped_km,
            active_users_counted=feed.active_users_counted,
            rings_expanded=feed.rings_expanded,
            reached_target=feed.reached_target,
            clamped_to_minimum=clamped_km > raw_km,
            clamped_to_maximum=clamped_km < raw_km,
            source=feed.source,
            recent_posts_counted=feed.recent_posts_counted,
            limited_by=feed.limited_by,
        )

    def user_filter_cap_km(self, feature: RadiusFeature) -> float | None:
        """How far a user may widen this feature with their own distance filter."""
        return self._settings.radius_rules[feature].user_filter_max_km

    def effective_radius_km(self, result: RadiusResult, requested_km: float | None) -> float:
        """Apply a user's distance filter on top of the adaptive radius.

        A filter can only widen up to the feature's cap, and can narrow freely —
        narrowing is always safe, and someone who wants to see only their own
        street should be able to.
        """
        if requested_km is None:
            return result.radius_km
        cap = self.user_filter_cap_km(result.feature)
        if cap is None:
            # The feed has no filter on purpose: "show me everything" is how a
            # local feed stops being local.
            return result.radius_km
        return min(max(requested_km, 0.1), cap)

    # -- Computation ---------------------------------------------------------
    async def _feed_radius(self, anchor_cell_res8: int) -> _FeedRadius:
        rule = self._settings.radius_rules[RadiusFeature.feed]
        # Bounded by the feed's own maximum rather than by the global ring cap:
        # a radius can never exceed max_km, so counting beyond it would be work
        # whose result is thrown away. At res 8 this is roughly 17 rings for a
        # 15 km maximum, against 40 for the cap.
        ring_limit = self._ring_limit_for_km(anchor_cell_res8, rule.max_km)
        totals = await self._ring_totals(anchor_cell_res8, ring_limit, rule)
        target_ring = totals.first_meeting()

        cached = await self._read_cache(anchor_cell_res8)
        if cached is None:
            result = self._at_target(anchor_cell_res8, totals, target_ring, ring_limit, rule)
            await self._write_cache(anchor_cell_res8, result)
            return result

        ratio = self._settings.radius_hysteresis_ratio
        cached_ring = min(cached.ring, ring_limit)
        if not totals.meets(cached_ring, 1 - ratio):
            # Either count has fallen clearly short inside the cached ring. Both
            # are cumulative, so nothing inside it holds either: grow.
            result = self._at_target(anchor_cell_res8, totals, target_ring, ring_limit, rule)
        else:
            margin_ring = totals.first_meeting(1 + ratio)
            if margin_ring is not None and margin_ring < cached_ring:
                # Both counts are comfortably above target nearer in: shrink.
                result = self._at_ring(
                    anchor_cell_res8,
                    totals,
                    margin_ring,
                    rule,
                    limited_by=self._bound_or(
                        anchor_cell_res8, margin_ring, rule, totals.binding(margin_ring, 1 + ratio)
                    ),
                    source="computed",
                )
            else:
                # Keep the cached ring and refresh its TTL, so a stable area stops
                # recomputing rather than recomputing and discarding the answer.
                result = self._at_ring(
                    anchor_cell_res8,
                    totals,
                    cached_ring,
                    rule,
                    limited_by=cached.limited_by,
                    source="stabilised",
                )
                await self._write_cache(anchor_cell_res8, result)
                return result

        await self._write_cache(anchor_cell_res8, result)
        if result.rings_expanded != cached_ring:
            logger.info(
                "radius_moved",
                extra={
                    "from_rings": cached_ring,
                    "to_rings": result.rings_expanded,
                    "to_km": round(result.radius_km, 2),
                    "limited_by": result.limited_by,
                },
            )
        return result

    def _at_target(
        self,
        anchor_cell_res8: int,
        totals: _RingTotals,
        target_ring: int | None,
        ring_limit: int,
        rule: RadiusRule,
    ) -> _FeedRadius:
        """The first ring holding both targets or, failing that, the ceiling.
        Not reaching them is the expected state at launch, not an error: the
        brief says most users will sit at the maximum."""
        if target_ring is None:
            return self._at_ring(
                anchor_cell_res8, totals, ring_limit, rule, limited_by="ceiling", source="computed"
            )
        return self._at_ring(
            anchor_cell_res8,
            totals,
            target_ring,
            rule,
            limited_by=self._bound_or(
                anchor_cell_res8, target_ring, rule, totals.binding(target_ring)
            ),
            source="computed",
        )

    @staticmethod
    def _bound_or(
        anchor_cell_res8: int, ring: int, rule: RadiusRule, condition: LimitedBy
    ) -> LimitedBy:
        """A bound that overrode the ring, else the condition that set it."""
        raw_km = cells.ring_distance_km(anchor_cell_res8, ring)
        if raw_km < rule.min_km:
            return "floor"
        if raw_km > rule.max_km:
            return "ceiling"
        return condition

    @staticmethod
    def _at_ring(
        anchor_cell_res8: int,
        totals: _RingTotals,
        ring: int,
        rule: RadiusRule,
        *,
        limited_by: LimitedBy,
        source: RadiusSource,
    ) -> _FeedRadius:
        raw_km = cells.ring_distance_km(anchor_cell_res8, ring)
        return _FeedRadius(
            radius_km=min(max(raw_km, rule.min_km), rule.max_km),
            raw_ring_km=raw_km,
            active_users_counted=totals.users[ring],
            recent_posts_counted=totals.posts[ring],
            rings_expanded=ring,
            reached_target=totals.meets(ring),
            limited_by=limited_by,
            source=source,
        )

    def _ring_limit_for_km(self, anchor_cell_res8: int, max_km: float) -> int:
        """The fewest rings that reach at least `max_km`, within the safety cap."""
        cap = self._settings.radius_max_ring_k
        for k in range(cap + 1):
            if cells.ring_distance_km(anchor_cell_res8, k) >= max_km:
                return k
        return cap

    async def _ring_totals(
        self, anchor_cell_res8: int, ring_limit: int, rule: RadiusRule
    ) -> _RingTotals:
        """Active users and counted recent posts, totalled ring by ring.

        One query for the whole disk, then grouped in Python. The alternative —
        a query per ring — is up to seventeen round trips for the same rows, and
        at launch density most of those rows do not exist at all, so the single
        query returns almost nothing.
        """
        disk = cells.disk(anchor_cell_res8, ring_limit)
        statement = select(
            CellActivity.cell, CellActivity.active_user_count, CellActivity.recent_post_count
        ).where(
            CellActivity.resolution == self._settings.h3_radius_resolution,
            CellActivity.cell.in_(disk),
            or_(CellActivity.active_user_count > 0, CellActivity.recent_post_count > 0),
        )
        rows = (await self._session.execute(statement)).all()

        users = [0] * (ring_limit + 1)
        posts = [0] * (ring_limit + 1)
        for cell, active, recent in rows:
            k = cells.grid_distance(anchor_cell_res8, int(cell))
            if 0 <= k <= ring_limit:
                users[k] += int(active)
                posts[k] += int(recent)
        for k in range(1, ring_limit + 1):
            users[k] += users[k - 1]
            posts[k] += posts[k - 1]
        return _RingTotals(
            users=tuple(users),
            posts=tuple(posts),
            target_users=rule.target_active_users or 1,
            target_posts=rule.target_recent_posts or 0,
        )

    async def active_users_within(self, anchor_cell_res8: int, radius_km: float) -> int:
        """Active users whose home cell lies within `radius_km` of the anchor.

        Used for reach estimates, so it counts people only: posts widen the
        radius it is given, never the number it returns.
        """
        rule = self._settings.radius_rules[RadiusFeature.feed]
        ring_limit = self._ring_limit_for_km(anchor_cell_res8, radius_km)
        totals = await self._ring_totals(anchor_cell_res8, ring_limit, rule)
        return totals.users[ring_limit]

    # -- Cache ---------------------------------------------------------------
    @staticmethod
    def cache_key(anchor_cell_res8: int) -> str:
        return f"{CACHE_PREFIX}:{anchor_cell_res8}"

    async def _read_cache(self, anchor_cell_res8: int) -> _CachedRadius | None:
        """A cache miss is not an error: the radius is simply recomputed.

        Only the feed radius is cached. Every other feature is a fixed multiple of
        it, so stabilising the feed stabilises all of them, and caching five
        derived values would be five round trips to avoid one multiplication.

        The entry is `<ring>|<limited_by>|<km>`. The ring is what hysteresis
        compares against; the km is only for a person reading Redis. An entry in
        any other shape (the km-only one before decision T.2) is a miss.
        """
        try:
            raw = await self._redis.get(self.cache_key(anchor_cell_res8))
        except CACHE_ERRORS:
            logger.warning("radius_cache_unavailable", exc_info=True)
            return None
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
        parts = text.split("|")
        if len(parts) != 3 or parts[1] not in _LIMITED_BY:
            return None
        try:
            ring = int(parts[0])
        except ValueError:
            return None
        if ring < 0:
            return None
        return _CachedRadius(ring=ring, limited_by=cast(LimitedBy, parts[1]))

    async def _write_cache(self, anchor_cell_res8: int, feed: _FeedRadius) -> None:
        try:
            await self._redis.set(
                self.cache_key(anchor_cell_res8),
                f"{feed.rings_expanded}|{feed.limited_by}|{feed.radius_km:.4f}",
                ex=self._settings.radius_cache_ttl_seconds,
            )
        except CACHE_ERRORS:
            # Losing the cache costs performance and stability, not correctness.
            logger.warning("radius_cache_write_failed", exc_info=True)

    async def invalidate(self, anchor_cell_res8: int) -> None:
        """Drop a cached radius. Used by tests and by density backfills."""
        try:
            await self._redis.delete(self.cache_key(anchor_cell_res8))
        except CACHE_ERRORS:
            logger.warning("radius_cache_invalidate_failed", exc_info=True)


def rule_for(settings: Settings, feature: RadiusFeature) -> RadiusRule:
    return settings.radius_rules[feature]
