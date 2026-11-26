"""Where app users are, counted per hexagon: now, and hour by hour (decision D.9).

A person counts once, in the hexagon their phone was last in: the "around you
now" session the app keeps while they're away from home (decision L.1), or their
home when there is none, for those who used the app in the window. So it counts
where app users are when they use it, not crowds as such.

The hourly job keeps the counts, and only the counts, per hexagon at resolutions
8, 7 and 6, for `PRESENCE_RETENTION_DAYS` (a year). Never who: no account ID, no
order of places, nothing that joins one hour to the next for anyone. The live
view reads the same way and keeps nothing.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import h3
from redis.asyncio import Redis
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import execute_dml
from app.core.redis import CACHE_ERRORS
from app.modules.location.models import PresenceCount
from app.modules.location.service import EXPLORE_KEY_PREFIX
from app.modules.users.models import User, UserStatus

logger = logging.getLogger(__name__)

RESOLUTIONS: Final = (8, 7, 6)
_BATCH: Final = 500


@dataclass(frozen=True, slots=True)
class PresenceSnapshot:
    hour_start: datetime
    people: int
    cells: int
    removed: int


async def _explore_cells(
    redis: Redis, user_ids: list[uuid.UUID], now: datetime
) -> dict[uuid.UUID, int]:
    """Each user's "around you now" hexagon (res 8), for those who have one."""
    found: dict[uuid.UUID, int] = {}
    for start in range(0, len(user_ids), _BATCH):
        batch = user_ids[start : start + _BATCH]
        try:
            raws = await redis.mget([f"{EXPLORE_KEY_PREFIX}:{user_id}" for user_id in batch])
        except CACHE_ERRORS:
            # Without Redis everyone counts at home: degraded, not wrong in kind.
            logger.warning("presence_explore_lookup_failed", exc_info=True)
            return found
        for user_id, raw in zip(batch, raws, strict=True):
            if not raw:
                continue
            try:
                payload = json.loads(raw)
                if datetime.fromisoformat(payload["expires_at"]) > now:
                    found[user_id] = int(payload["cell_res8"])
            except (ValueError, KeyError, TypeError):
                continue
    return found


async def where_people_are(
    session: AsyncSession, redis: Redis, *, since: datetime, now: datetime | None = None
) -> dict[int, Counter[int]]:
    """People active since `since`, counted per hexagon at resolutions 8, 7, 6."""
    moment = now or datetime.now(UTC)
    rows = (
        await session.execute(
            select(User.id, User.home_cell_res8).where(
                User.deleted_at.is_(None),
                User.status == UserStatus.active,
                User.last_active_at >= since,
            )
        )
    ).all()
    explored = await _explore_cells(redis, [row.id for row in rows], moment)

    counts: dict[int, Counter[int]] = {resolution: Counter() for resolution in RESOLUTIONS}
    for user_id, home in rows:
        cell = explored.get(user_id, home)
        if cell is None:
            continue  # no home yet and not out exploring: nowhere to count them
        name = h3.int_to_str(int(cell))
        counts[8][int(cell)] += 1
        for resolution in (7, 6):
            counts[resolution][h3.str_to_int(h3.cell_to_parent(name, resolution))] += 1
    return counts


def hour_floor(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


async def snapshot_presence(
    session: AsyncSession, redis: Redis, *, settings: Settings, now: datetime | None = None
) -> PresenceSnapshot:
    """Count the hour just ended, and forget hours older than the retention.

    Run a few minutes past each hour. Everyone active since the hour began
    counts in it, where they were last; a re-run of the same hour replaces it.
    """
    moment = now or datetime.now(UTC)
    hour_start = hour_floor(moment) - timedelta(hours=1)
    counts = await where_people_are(session, redis, since=hour_start, now=moment)

    rows = [
        {"hour_start": hour_start, "resolution": resolution, "cell": cell, "people": people}
        for resolution, counter in counts.items()
        for cell, people in counter.items()
    ]
    await execute_dml(session, delete(PresenceCount).where(PresenceCount.hour_start == hour_start))
    if rows:
        await session.execute(insert(PresenceCount).values(rows))
    removed = await execute_dml(
        session,
        delete(PresenceCount).where(
            PresenceCount.hour_start < moment - timedelta(days=settings.presence_retention_days)
        ),
    )
    return PresenceSnapshot(
        hour_start=hour_start,
        people=sum(counts[8].values()),
        cells=len(counts[8]),
        removed=removed,
    )


async def counts_at_hour(
    session: AsyncSession, *, resolution: int, hour_start: datetime
) -> dict[int, float]:
    rows = await session.execute(
        select(PresenceCount.cell, PresenceCount.people).where(
            PresenceCount.resolution == resolution,
            PresenceCount.hour_start == hour_floor(hour_start),
        )
    )
    return {int(cell): float(people) for cell, people in rows}


async def typical_counts(
    session: AsyncSession,
    *,
    resolution: int,
    hour_of_day: int,
    days: int,
    now: datetime | None = None,
) -> tuple[dict[int, float], int]:
    """Average people per hexagon at an hour of the day (Nairobi), over the last
    `days` days. Hours with nobody in a hexagon count as zero, so the average is
    over the hours recorded, not only the busy ones. Returns the averages and how
    many hours were recorded."""
    moment = now or datetime.now(UTC)
    since = moment - timedelta(days=days)
    hours_recorded = int(
        await session.scalar(
            text(
                "SELECT count(DISTINCT hour_start) FROM presence_counts "
                "WHERE hour_start >= :since AND resolution = :resolution "
                "AND extract(hour FROM hour_start AT TIME ZONE 'Africa/Nairobi') = :hour"
            ),
            {"since": since, "resolution": resolution, "hour": hour_of_day},
        )
        or 0
    )
    if not hours_recorded:
        return {}, 0
    rows = await session.execute(
        text(
            "SELECT cell, sum(people) FROM presence_counts "
            "WHERE hour_start >= :since AND resolution = :resolution "
            "AND extract(hour FROM hour_start AT TIME ZONE 'Africa/Nairobi') = :hour "
            "GROUP BY cell"
        ),
        {"since": since, "resolution": resolution, "hour": hour_of_day},
    )
    return {
        int(cell): round(float(total) / hours_recorded, 1) for cell, total in rows
    }, hours_recorded
