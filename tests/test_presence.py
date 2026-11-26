"""Where app users are, now and hour by hour (decision D.9)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import h3
import httpx
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.location import cells, presence
from app.modules.location.models import PresenceCount
from app.modules.moderation.models import AuditAction, AuditEvent
from app.modules.users.models import User, UserStatus
from app.workers.tasks import count_presence
from tests.factories import KARATINA, NYERI_TOWN, make_user
from tests.test_admin_map import admin_headers

NOW = datetime(2026, 11, 26, 9, 2, tzinfo=UTC)  # 12:02 in Nairobi


def res8(at: object) -> int:
    return cells.locate(at.latitude, at.longitude).cell_res8  # type: ignore[attr-defined]


async def exploring(redis: Redis, user: User, at: object, *, expires: datetime) -> None:
    await redis.set(
        f"explore:{user.id}",
        json.dumps({"cell_res9": 0, "cell_res8": res8(at), "expires_at": expires.isoformat()}),
        ex=3600,
    )


async def _people(session: AsyncSession, redis: Redis) -> dict[str, User]:
    at_home = await make_user(session, at=NYERI_TOWN, last_active_at=NOW - timedelta(minutes=10))
    away = await make_user(session, at=NYERI_TOWN, last_active_at=NOW - timedelta(minutes=20))
    await exploring(redis, away, KARATINA, expires=NOW + timedelta(hours=1))
    stale_trip = await make_user(session, at=NYERI_TOWN, last_active_at=NOW - timedelta(minutes=30))
    await exploring(redis, stale_trip, KARATINA, expires=NOW - timedelta(minutes=1))
    asleep = await make_user(session, at=NYERI_TOWN, last_active_at=NOW - timedelta(hours=3))
    suspended = await make_user(
        session,
        at=NYERI_TOWN,
        status=UserStatus.suspended,
        last_active_at=NOW - timedelta(minutes=5),
    )
    homeless = await make_user(session, last_active_at=NOW - timedelta(minutes=5))
    return {
        "at_home": at_home,
        "away": away,
        "stale_trip": stale_trip,
        "asleep": asleep,
        "suspended": suspended,
        "homeless": homeless,
    }


async def test_people_count_where_their_phone_was_last(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    """Out exploring counts where they are; otherwise home. An expired trip is
    home again. Asleep, suspended, or nowhere to put them: not counted."""
    await _people(db_session, redis_client)

    counts = await presence.where_people_are(
        db_session, redis_client, since=NOW - timedelta(hours=1), now=NOW
    )

    assert counts[8] == {res8(NYERI_TOWN): 2, res8(KARATINA): 1}
    nyeri7 = h3.str_to_int(h3.cell_to_parent(h3.int_to_str(res8(NYERI_TOWN)), 7))
    assert counts[7][nyeri7] == 2
    assert sum(counts[6].values()) == 3


async def test_the_hour_just_ended_is_kept_and_a_rerun_replaces_it(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    await _people(db_session, redis_client)
    old = PresenceCount(
        hour_start=NOW - timedelta(days=settings.presence_retention_days + 1),
        resolution=8,
        cell=res8(NYERI_TOWN),
        people=5,
    )
    db_session.add(old)
    await db_session.flush()

    first = await presence.snapshot_presence(db_session, redis_client, settings=settings, now=NOW)
    again = await presence.snapshot_presence(db_session, redis_client, settings=settings, now=NOW)

    assert first.hour_start == datetime(2026, 11, 26, 8, tzinfo=UTC)
    assert (first.people, first.cells, first.removed) == (3, 2, 1)
    assert again.removed == 0
    rows = (
        await db_session.execute(
            select(PresenceCount.resolution, func.sum(PresenceCount.people))
            .where(PresenceCount.hour_start == first.hour_start)
            .group_by(PresenceCount.resolution)
        )
    ).all()
    assert dict(rows) == {8: 3, 7: 3, 6: 3}


async def test_the_hourly_job_runs_the_snapshot(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    await make_user(db_session, at=NYERI_TOWN)
    result = await count_presence({"job_id": "t", "session": db_session})
    assert result["people"] >= 1
    kept = await db_session.scalar(select(func.count()).select_from(PresenceCount))
    assert (kept or 0) >= 3


async def test_god_view_shows_now_an_hour_and_a_typical_day(
    client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    headers = await admin_headers(db_session, settings)
    person = await make_user(db_session, at=NYERI_TOWN)
    await exploring(redis_client, person, KARATINA, expires=datetime.now(UTC) + timedelta(hours=1))

    now = (
        await client.get("/v1/admin/map/presence", headers=headers, params={"mode": "now"})
    ).json()
    assert [(c["id"], c["people"]) for c in now["cells"]] == [(h3.int_to_str(res8(KARATINA)), 1.0)]
    assert len(now["cells"][0]["boundary"]) == 6

    # Two recorded mornings at 09:00 Nairobi (06:00 UTC), and one other hour.
    nyeri, karatina = res8(NYERI_TOWN), res8(KARATINA)
    day1 = datetime(2026, 11, 24, 6, tzinfo=UTC)
    day2 = datetime(2026, 11, 25, 6, tzinfo=UTC)
    db_session.add_all(
        [
            PresenceCount(hour_start=day1, resolution=8, cell=nyeri, people=4),
            PresenceCount(hour_start=day1, resolution=8, cell=karatina, people=1),
            PresenceCount(hour_start=day2, resolution=8, cell=nyeri, people=2),
            PresenceCount(hour_start=day2 + timedelta(hours=1), resolution=8, cell=nyeri, people=9),
        ]
    )
    await db_session.flush()

    hour = (
        await client.get(
            "/v1/admin/map/presence",
            headers=headers,
            params={"mode": "hour", "at": "2026-11-24T09:00:00+03:00"},
        )
    ).json()
    assert sorted((c["id"], c["people"]) for c in hour["cells"]) == sorted(
        [(h3.int_to_str(nyeri), 4.0), (h3.int_to_str(karatina), 1.0)]
    )

    typical = (
        await client.get(
            "/v1/admin/map/presence",
            headers=headers,
            params={"mode": "typical", "hour_of_day": 9, "days": 30},
        )
    ).json()
    assert typical["hours_recorded"] == 2
    assert {c["id"]: c["people"] for c in typical["cells"]} == {
        h3.int_to_str(nyeri): 3.0,
        h3.int_to_str(karatina): 0.5,
    }

    missing = await client.get("/v1/admin/map/presence", headers=headers, params={"mode": "hour"})
    assert missing.status_code == 400

    view = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == AuditAction.people_map_viewed)
    )
    assert view is not None
    assert view.context == {"resolution": 8, "mode": "now"}
