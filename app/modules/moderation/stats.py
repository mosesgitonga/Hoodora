"""The admin dashboard's overview numbers (decision D.3).

Counts only, never a person: daily totals for the last 30 days, the current
totals, and how the feed radius spreads across the people using the app. Read
from what the database already holds; nothing new is tracked for it.

Days are Nairobi days. Kenya keeps UTC+3 all year, so "today" is computed with a
fixed offset here, and rows are bucketed with PostgreSQL's own `Africa/Nairobi`.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Final

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RadiusFeature, Settings
from app.core.redis import CACHE_ERRORS
from app.modules.location.radius import RadiusEngine, SpreadEntry
from app.modules.moderation import console
from app.modules.moderation.admin_schemas import (
    ActiveUsersOut,
    DayCountsOut,
    RadiusBandOut,
    RadiusSpreadOut,
    StatsOut,
    TotalsOut,
)

logger = logging.getLogger(__name__)

CACHE_KEY: Final = "admin:stats:v1"
DAYS: Final = 30
NAIROBI: Final = timezone(timedelta(hours=3), "EAT")
LIMITS: Final = ("users", "posts", "both", "floor", "ceiling")

# What each daily column counts: a table and the moment that puts a row in a day.
# Fixed strings, never input, so formatting them into SQL is safe.
_DAILY: Final = {
    "sign_ups": ("users", "created_at"),
    "posts": ("posts", "created_at"),
    "listings": ("listings", "created_at"),
    "reports_opened": ("reports", "created_at"),
    "reports_resolved": ("reports", "resolved_at"),
}

# Accounts, then those in good standing that opened the app in each window: the
# same test the radius engine uses for "active" (`cell_activity`).
_USERS_SQL: Final = """
SELECT
    count(*) FILTER (WHERE deleted_at IS NULL),
    count(*) FILTER (WHERE deleted_at IS NULL AND status = 'active' AND last_active_at >= :w1),
    count(*) FILTER (WHERE deleted_at IS NULL AND status = 'active' AND last_active_at >= :w7),
    count(*) FILTER (WHERE deleted_at IS NULL AND status = 'active' AND last_active_at >= :w14),
    count(*) FILTER (WHERE deleted_at IS NULL AND status = 'active' AND last_active_at >= :w30)
FROM users
"""

# Middle band edges in km; the floor and the ceiling come from the feed's rule.
BAND_EDGES_KM: Final = (3.0, 5.0, 10.0)


async def overview(
    session: AsyncSession, redis: Redis, *, settings: Settings, now: datetime | None = None
) -> StatsOut:
    """The overview, from Redis while it is fresh, else counted afresh."""
    if settings.admin_stats_cache_seconds and now is None:
        try:
            cached = await redis.get(CACHE_KEY)
        except CACHE_ERRORS:
            logger.warning("admin_stats_cache_unavailable", exc_info=True)
            cached = None
        if cached:
            return StatsOut.model_validate_json(cached)

    stats = await compute(session, redis, settings=settings, now=now)
    if settings.admin_stats_cache_seconds and now is None:
        try:
            await redis.set(
                CACHE_KEY, stats.model_dump_json(), ex=settings.admin_stats_cache_seconds
            )
        except CACHE_ERRORS:
            logger.warning("admin_stats_cache_write_failed", exc_info=True)
    return stats


async def compute(
    session: AsyncSession, redis: Redis, *, settings: Settings, now: datetime | None = None
) -> StatsOut:
    moment = now or datetime.now(UTC)
    today = moment.astimezone(NAIROBI).date()
    first = today - timedelta(days=DAYS - 1)
    start = datetime(first.year, first.month, first.day, tzinfo=NAIROBI)

    by_day: dict[str, dict[date, int]] = {}
    for name, (table, column) in _DAILY.items():
        rows = await session.execute(
            text(
                f"SELECT ({column} AT TIME ZONE 'Africa/Nairobi')::date AS day, count(*) "  # noqa: S608 — fixed names
                f"FROM {table} WHERE {column} >= :start AND {column} < :end GROUP BY 1"
            ),
            {"start": start, "end": moment},
        )
        by_day[name] = {row[0]: int(row[1]) for row in rows}
    days = [
        DayCountsOut(date=day, **{name: by_day[name].get(day, 0) for name in _DAILY})
        for day in (first + timedelta(days=offset) for offset in range(DAYS))
    ]

    users, *windows = (
        await session.execute(
            text(_USERS_SQL),
            {f"w{days_back}": moment - timedelta(days=days_back) for days_back in (1, 7, 14, 30)},
        )
    ).one()
    waiting = await console.queue_summary(session)

    entries = await RadiusEngine(session, redis, settings).spread()
    return StatsOut(
        generated_at=moment,
        days=days,
        totals=TotalsOut(
            users=int(users),
            active=ActiveUsersOut(
                last_day=int(windows[0]),
                last_7_days=int(windows[1]),
                last_14_days=int(windows[2]),
                last_30_days=int(windows[3]),
            ),
            open_reports=waiting.open_reports,
            held_items=waiting.held,
            waiting=waiting.waiting,
            oldest_open_report_at=waiting.oldest_open_report_at,
            oldest_waiting_since=waiting.oldest_waiting_since,
        ),
        radius=spread_out(entries, settings),
    )


def spread_out(entries: list[SpreadEntry], settings: Settings) -> RadiusSpreadOut:
    """People by radius band and by what set their radius.

    The bands: the floor alone, then up to 3, 5 and 10 km, then short of the
    ceiling, then the ceiling alone. The floor and the ceiling get bands of
    their own because sitting on either says the most about an area.
    """
    rule = settings.radius_rules[RadiusFeature.feed]
    edges = [rule.min_km, *(e for e in BAND_EDGES_KM if rule.min_km < e < rule.max_km)]
    bands = [RadiusBandOut(from_km=rule.min_km, to_km=rule.min_km, people=0)]
    bands += [
        RadiusBandOut(from_km=low, to_km=high, people=0)
        for low, high in zip(edges, [*edges[1:], rule.max_km], strict=True)
    ]
    bands.append(RadiusBandOut(from_km=rule.max_km, to_km=rule.max_km, people=0))

    tolerance = 1e-6
    limits: Counter[str] = Counter()
    for entry in entries:
        limits[entry.limited_by] += entry.people
        km = entry.radius_km
        if km <= rule.min_km + tolerance:
            band = bands[0]
        elif km >= rule.max_km - tolerance:
            band = bands[-1]
        else:
            band = next(b for b in bands[1:-1] if b.from_km < km <= b.to_km + tolerance)
        band.people += entry.people

    return RadiusSpreadOut(
        people=sum(entry.people for entry in entries),
        bands=bands,
        by_condition={limit: limits.get(limit, 0) for limit in LIMITS},
    )
