"""Zones: where someone has been this week, and whether they may post there.

Decision L.2. People see what is around them anywhere, but posting in a place
means having been there: `POSTING_PRESENCE_DAYS` of the last seven days in the
zone, or in a zone touching it so that living near an edge counts. A zone is an
H3 resolution-7 cell, about 2.5 km across.

**What is kept:** for each zone someone was in this week, seven bits, one per
day. Never a coordinate, never a time of day, and nothing older than a week:
the nightly roll deletes a row once its days have aged out. A day counts when
the app reported the phone there, which it does when it opens and comes back to
the foreground.

**The one shortcut:** someone who said "this is my home area" when they signed
up, has a verified phone, and has not moved home since, may post around home
from day one. Moving home, or saying the place was not home, means the days.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import execute_dml
from app.core.errors import ForbiddenError
from app.modules.location import cells
from app.modules.location.models import UserZoneDay
from app.modules.users.models import User

ZONE_RESOLUTION = 7
WINDOW_DAYS = 7
_WINDOW_MASK = (1 << WINDOW_DAYS) - 1


def zone_of(cell: int) -> int:
    """The zone a cell of resolution 7 or finer lies in."""
    if cells.cell_resolution(cell) == ZONE_RESOLUTION:
        return cell
    return cells.parent_cell(cell, ZONE_RESOLUTION)


def today_utc() -> date:
    """Days are UTC days, as the home-presence record's are."""
    return datetime.now(UTC).date()


def rolled(mask: int, updated_on: date, today: date) -> int:
    """Age a seven-day mask forward to today. Bit 0 is `updated_on`."""
    elapsed = (today - updated_on).days
    if elapsed <= 0:
        return mask & _WINDOW_MASK
    if elapsed >= WINDOW_DAYS:
        return 0
    return (mask << elapsed) & _WINDOW_MASK


async def record(session: AsyncSession, *, user_id: uuid.UUID, cell: int, today: date) -> None:
    """Note that the person was in this cell's zone today."""
    zone = zone_of(cell)
    existing = await session.scalar(
        select(UserZoneDay).where(UserZoneDay.user_id == user_id, UserZoneDay.zone == zone)
    )
    if existing is not None:
        existing.days_mask = rolled(existing.days_mask, existing.updated_on, today) | 1
        existing.updated_on = today
        await session.flush()
        return
    # A first visit this week. The upsert covers two reports racing to create it:
    # both were today, so the second simply keeps today's bit.
    await execute_dml(
        session,
        insert(UserZoneDay)
        .values(user_id=user_id, zone=zone, days_mask=1, updated_on=today)
        .on_conflict_do_update(
            index_elements=["user_id", "zone"],
            set_={"days_mask": UserZoneDay.days_mask.op("|")(1), "updated_on": today},
        ),
    )


@dataclass(frozen=True, slots=True)
class ZoneStanding:
    days: int
    """Distinct days of the last seven spent in the zone or a touching one."""
    needed: int
    by_home: bool
    """The sign-up shortcut applies here."""

    @property
    def may_post(self) -> bool:
        return self.by_home or self.days >= self.needed


async def standing(
    session: AsyncSession,
    *,
    user: User,
    cell: int,
    settings: Settings,
    today: date | None = None,
) -> ZoneStanding:
    """How established someone is in the zone of `cell`."""
    zone = zone_of(cell)
    nearby = cells.disk(zone, 1)
    day = today or today_utc()
    rows = (
        await session.execute(
            select(UserZoneDay.days_mask, UserZoneDay.updated_on).where(
                UserZoneDay.user_id == user.id, UserZoneDay.zone.in_(nearby)
            )
        )
    ).all()
    combined = 0
    for mask, updated_on in rows:
        combined |= rolled(int(mask), updated_on, day)
    by_home = (
        user.home_claimed_at_signup
        and not user.home_provisional
        and user.phone_verified_at is not None
        and user.home_cell_res7 is not None
        and user.home_cell_res7 in nearby
    )
    return ZoneStanding(
        days=bin(combined).count("1"),
        needed=settings.posting_presence_days,
        by_home=bool(by_home),
    )


async def require_may_post(
    session: AsyncSession, *, user: User, cell: int, settings: Settings
) -> None:
    """Refuse to place something in a zone the person is new to."""
    result = await standing(session, user=user, cell=cell, settings=settings)
    if result.may_post:
        return
    raise ForbiddenError(
        f"You can post here once you've been around on {result.needed} days in a week. "
        f"So far: {result.days}.",
        details={
            "reason": "new_to_area",
            "days": result.days,
            "needed": result.needed,
            "window_days": WINDOW_DAYS,
        },
    )


async def require_may_post_at(
    session: AsyncSession, *, user: User, location: dict[str, object], settings: Settings
) -> None:
    """`require_may_post` for the location columns new content is about to take."""
    cell = location.get("cell_res9")
    if not isinstance(cell, int):  # pragma: no cover — the columns always carry it
        raise TypeError("location columns without a res-9 cell")
    await require_may_post(session, user=user, cell=cell, settings=settings)


# ---------------------------------------------------------------------------
# Retention and data rights
# ---------------------------------------------------------------------------
async def prune(session: AsyncSession, *, today: date | None = None) -> int:
    """Delete rows whose days have all aged out of the week. Run nightly."""
    cutoff = (today or today_utc()) - timedelta(days=WINDOW_DAYS - 1)
    return await execute_dml(session, delete(UserZoneDay).where(UserZoneDay.updated_on < cutoff))


async def purge_user_zones(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    return await execute_dml(session, delete(UserZoneDay).where(UserZoneDay.user_id == user_id))


async def export_user_zones(
    session: AsyncSession, *, user_id: uuid.UUID, today: date | None = None
) -> dict[str, Any]:
    """How many days of the last week each zone was recorded, without naming the
    zone's cell: the export says what is held, in words a person can read."""
    day = today or today_utc()
    rows = (
        await session.execute(
            select(UserZoneDay.days_mask, UserZoneDay.updated_on).where(
                UserZoneDay.user_id == user_id
            )
        )
    ).all()
    days = sorted(
        (bin(rolled(int(mask), updated_on, day)).count("1") for mask, updated_on in rows),
        reverse=True,
    )
    return {
        "zones_this_week": [{"days_recorded": count} for count in days if count],
        "notes": (
            "To decide where you may post, Hoodora keeps which zones (about 2.5 km "
            "across) your phone was in on each of the last seven days, as one yes/no "
            "per day. Never where in a zone, never a time, and nothing older than a "
            "week."
        ),
    }
