"""The admin API as the dashboard uses it (decisions D.1 to D.4).

- Every `/v1/admin` route, called with no token, a user's token, a moderator's
  and an admin's, answers as `staff.permissions.MINIMUM_ROLE` says.
- Looking a person up by phone number, and its audit row.
- The audit log's time filter.
- The overview numbers, on a seeded dataset, with no personal data in them.
- CORS: the dashboard's origin on `/v1/admin` and nowhere else.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RadiusFeature, Settings
from app.main import create_app
from app.modules.auth import service as auth_service
from app.modules.feed.models import Post
from app.modules.location.models import CellActivity
from app.modules.location.radius import RadiusEngine
from app.modules.marketplace.models import Listing
from app.modules.moderation import stats
from app.modules.moderation.models import (
    AuditAction,
    AuditActorType,
    AuditEvent,
    ContentStatus,
    Report,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)
from app.modules.staff.credentials import create_staff_token
from app.modules.staff.models import StaffRole, StaffSession
from app.modules.staff.permissions import MINIMUM_ROLE
from app.modules.users.models import User, UserStatus
from tests.factories import (
    KARATINA,
    NYERI_TOWN,
    make_post,
    make_staff,
    make_user,
    phone_of,
    set_cell_density,
)


async def token_for(session: AsyncSession, staff_id: uuid.UUID, settings: Settings) -> str:
    """A fresh staff session each time: one call may be the sign-out."""
    staff_session = StaffSession(
        staff_id=staff_id, expires_at=datetime.now(UTC) + settings.staff_session_ttl
    )
    session.add(staff_session)
    await session.flush()
    return create_staff_token(
        staff_id=staff_id,
        session_id=staff_session.id,
        expires_at=staff_session.expires_at,
        settings=settings,
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Every route, every role
# ---------------------------------------------------------------------------
def test_every_admin_route_has_a_minimum_role(app: FastAPI) -> None:
    served = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/v1/admin")
        for method in operations
    }
    assert served - MINIMUM_ROLE.keys() == set(), "add these to staff.permissions.MINIMUM_ROLE"
    assert MINIMUM_ROLE.keys() - served == set(), "these are in MINIMUM_ROLE but not served"


def _concrete(path: str) -> str:
    return re.sub(
        r"\{(\w+)\}",
        lambda m: "post" if m.group(1) == "target_type" else str(uuid.uuid4()),
        path,
    )


async def test_every_admin_route_answers_each_role_as_the_table_says(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """No token and a user's token get 401 everywhere but sign-in; a moderator
    gets 403 exactly where an admin is needed; nobody allowed is refused. The
    body is empty on purpose: a refused caller is stopped before it is read, an
    allowed one gets as far as validation or a missing record."""
    moderator = (await make_staff(db_session)).account.id
    admin = (await make_staff(db_session, role=StaffRole.admin)).account.id
    neighbour = await make_user(db_session, at=NYERI_TOWN)
    user_token = (
        await auth_service.issue_tokens(db_session, user=neighbour, settings=settings)
    ).access_token
    await db_session.flush()

    problems: list[str] = []
    for (method, template), required in sorted(MINIMUM_ROLE.items()):
        path = _concrete(template)
        body: dict[str, Any] | None = {} if method in {"POST", "PATCH"} else None

        async def call(
            headers: dict[str, str],
            path: str = path,
            method: str = method,
            body: dict[str, Any] | None = body,
        ) -> int:
            response = await client.request(method, path, headers=headers, json=body)
            return response.status_code

        if required is None:
            # Signing in needs no token: an empty body reaches validation.
            if (status := await call({})) != 422:
                problems.append(f"{method} {template}: no token got {status}, wanted 422")
            continue

        for who, headers in (("no token", {}), ("a user's token", bearer(user_token))):
            if (status := await call(headers)) != 401:
                problems.append(f"{method} {template}: {who} got {status}, wanted 401")

        status = await call(bearer(await token_for(db_session, moderator, settings)))
        if required is StaffRole.admin and status != 403:
            problems.append(f"{method} {template}: a moderator got {status}, wanted 403")
        if required is StaffRole.moderator and (status in {401, 403} or status >= 500):
            problems.append(f"{method} {template}: a moderator got {status}")

        status = await call(bearer(await token_for(db_session, admin, settings)))
        if status in {401, 403} or status >= 500:
            problems.append(f"{method} {template}: an admin got {status}")

    assert problems == []


# ---------------------------------------------------------------------------
# Looking a person up (decision D.2)
# ---------------------------------------------------------------------------
@pytest.fixture
async def moderator(
    db_session: AsyncSession, settings: Settings
) -> tuple[uuid.UUID, dict[str, str]]:
    account = (await make_staff(db_session)).account
    return account.id, bearer(await token_for(db_session, account.id, settings))


async def test_a_moderator_finds_a_person_by_their_number_as_typed(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    moderator: tuple[uuid.UUID, dict[str, str]],
) -> None:
    staff_id, headers = moderator
    person = await make_user(db_session, at=NYERI_TOWN, display_name="Wanjiku Kamau")
    number = phone_of(person)
    as_typed = "0" + number.removeprefix("+254")

    response = await client.post(
        "/v1/admin/users/lookup", headers=headers, json={"phone_number": as_typed}
    )

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == [str(person.id)]
    assert response.json()[0]["display_name"] == "Wanjiku Kamau"
    # The number is never sent back, in any form.
    assert number not in response.text and number[-9:] not in response.text

    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == AuditAction.user_looked_up)
    )
    assert event is not None
    assert (event.actor_type, event.actor_id) == (AuditActorType.moderator, staff_id)
    assert (event.target_type, event.target_id) == ("user", person.id)
    assert event.context == {"by": "phone", "found": True}


async def test_a_number_nobody_has_finds_nobody_and_is_still_audited(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    moderator: tuple[uuid.UUID, dict[str, str]],
) -> None:
    _, headers = moderator
    response = await client.post(
        "/v1/admin/users/lookup", headers=headers, json={"phone_number": "+254799000111"}
    )

    assert response.status_code == 200
    assert response.json() == []
    event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == AuditAction.user_looked_up)
    )
    assert event is not None
    assert event.target_id is None
    assert event.context == {"by": "phone", "found": False}
    assert "799000111" not in str(event.context)


async def test_a_deleted_account_is_not_found_and_nonsense_is_refused(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    moderator: tuple[uuid.UUID, dict[str, str]],
) -> None:
    _, headers = moderator
    gone = await make_user(db_session, at=NYERI_TOWN)
    number = phone_of(gone)
    gone.deleted_at = datetime.now(UTC)
    await db_session.flush()

    found = await client.post(
        "/v1/admin/users/lookup", headers=headers, json={"phone_number": number}
    )
    assert found.json() == []

    nonsense = await client.post(
        "/v1/admin/users/lookup", headers=headers, json={"phone_number": "not a number"}
    )
    assert nonsense.status_code == 400


# ---------------------------------------------------------------------------
# The audit log by time (decision D.2)
# ---------------------------------------------------------------------------
async def test_the_audit_log_filters_by_time(
    client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    admin = (await make_staff(db_session, role=StaffRole.admin)).account.id
    headers = bearer(await token_for(db_session, admin, settings))
    base = datetime(2026, 11, 20, 12, tzinfo=UTC)
    for days in (0, 1, 2):
        db_session.add(
            AuditEvent(
                actor_type=AuditActorType.system,
                action=AuditAction.badge_awarded,
                context={"n": days},
                created_at=base + timedelta(days=days),
            )
        )
    await db_session.flush()

    response = await client.get(
        "/v1/admin/audit",
        headers=headers,
        params={
            "action": "badge_awarded",
            "since": (base + timedelta(hours=12)).isoformat(),
            "until": (base + timedelta(days=2)).isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    assert [item["context"] for item in response.json()["items"]] == [{"n": 1}]


# ---------------------------------------------------------------------------
# The overview (decision D.3)
# ---------------------------------------------------------------------------
NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)  # 12:00 in Nairobi
LONG_AGO = datetime(2026, 9, 1, tzinfo=UTC)


async def _seed_overview(db_session: AsyncSession, redis: Redis) -> dict[str, Any]:
    author = await make_user(db_session, at=NYERI_TOWN, display_name="Achieng Otieno")
    reporter = await make_user(db_session, at=NYERI_TOWN, display_name="Kiprono Bett")
    joined_today = await make_user(db_session, at=NYERI_TOWN)
    joined_after_midnight = await make_user(db_session, at=NYERI_TOWN)
    joined_yesterday = await make_user(db_session, at=NYERI_TOWN)
    active_5_days = await make_user(db_session, at=NYERI_TOWN)
    active_10_days = await make_user(db_session, at=NYERI_TOWN)
    active_20_days = await make_user(db_session, at=NYERI_TOWN)
    suspended = await make_user(db_session, at=NYERI_TOWN, status=UserStatus.suspended)
    purged = await make_user(db_session, at=NYERI_TOWN)

    p_today = await make_post(db_session, redis, author=author, body="Water back on")
    p_after_midnight = await make_post(db_session, redis, author=author, body="Matatu stage")
    p_earlier = await make_post(db_session, redis, author=author, body="Lost umbrella")
    held = await make_post(db_session, redis, author=author, body="Held for review")
    listing = Listing(
        seller_id=author.id,
        title="Sofa",
        category="furniture",
        condition="good",
        pricing="fixed",
        price_kes=8500,
        expires_at=NOW + timedelta(days=30),
        content_hash="a" * 64,
        cell_res9=p_today.cell_res9,
        cell_res8=p_today.cell_res8,
        cell_res7=p_today.cell_res7,
        cell_res6=p_today.cell_res6,
        centroid=p_today.centroid,
        coarse_centroid=p_today.centroid,
    )
    db_session.add(listing)
    await db_session.flush()

    # Everything starts long ago, out of every window, then each is placed.
    await db_session.execute(update(User).values(created_at=LONG_AGO, last_active_at=LONG_AGO))
    await db_session.execute(update(Post).values(created_at=LONG_AGO))

    def at(when: datetime) -> dict[str, datetime]:
        return {"created_at": when}

    for user, created in (
        (joined_today, datetime(2026, 11, 25, 6, tzinfo=UTC)),
        # 01:30 in Nairobi: today there, still yesterday in UTC.
        (joined_after_midnight, datetime(2026, 11, 24, 22, 30, tzinfo=UTC)),
        # 23:00 in Nairobi on the 24th.
        (joined_yesterday, datetime(2026, 11, 24, 20, tzinfo=UTC)),
    ):
        await db_session.execute(update(User).where(User.id == user.id).values(**at(created)))
    for user, active in (
        (author, NOW - timedelta(hours=2)),
        (active_5_days, NOW - timedelta(days=5)),
        (active_10_days, NOW - timedelta(days=10)),
        (active_20_days, NOW - timedelta(days=20)),
        # Not in good standing: not active, whatever its last visit.
        (suspended, NOW - timedelta(hours=1)),
    ):
        await db_session.execute(
            update(User).where(User.id == user.id).values(last_active_at=active)
        )
    await db_session.execute(
        update(User).where(User.id == purged.id).values(deleted_at=NOW - timedelta(days=1))
    )
    for post, created in (
        (p_today, datetime(2026, 11, 25, 8, tzinfo=UTC)),
        (p_after_midnight, datetime(2026, 11, 24, 21, 30, tzinfo=UTC)),
        (p_earlier, datetime(2026, 11, 20, 12, tzinfo=UTC)),
    ):
        await db_session.execute(update(Post).where(Post.id == post.id).values(**at(created)))
    await db_session.execute(
        update(Post)
        .where(Post.id == held.id)
        .values(
            status=ContentStatus.hidden_pending_review, hidden_at=datetime(2026, 11, 23, tzinfo=UTC)
        )
    )
    await db_session.execute(
        update(Listing)
        .where(Listing.id == listing.id)
        .values(created_at=datetime(2026, 11, 23, 10, tzinfo=UTC))
    )
    pending = Report(
        reporter_id=reporter.id,
        target_type=ReportTargetType.post,
        target_id=p_today.id,
        reason=ReportReason.spam,
        status=ReportStatus.pending,
        created_at=datetime(2026, 11, 25, 7, tzinfo=UTC),
    )
    resolved = Report(
        reporter_id=reporter.id,
        target_type=ReportTargetType.post,
        target_id=p_earlier.id,
        reason=ReportReason.spam,
        status=ReportStatus.dismissed,
        created_at=datetime(2026, 11, 22, 9, tzinfo=UTC),
        resolved_at=datetime(2026, 11, 24, 12, tzinfo=UTC),
    )
    db_session.add_all([pending, resolved])

    # The map: a cluster around Nyeri, and one quiet cell near Karatina.
    await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=100, posts_per_cell=10, rings=2
    )
    await set_cell_density(
        db_session, origin=KARATINA, active_per_cell=5, posts_per_cell=0, rings=0
    )
    await db_session.flush()
    return {"names": ["Achieng Otieno", "Kiprono Bett"], "users": 9}


async def test_the_overview_counts_a_seeded_month(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    await _seed_overview(db_session, redis_client)

    out = await stats.compute(db_session, redis_client, settings=settings, now=NOW)

    assert len(out.days) == 30
    assert (out.days[0].date.isoformat(), out.days[-1].date.isoformat()) == (
        "2026-10-27",
        "2026-11-25",
    )
    day = {d.date.isoformat(): d for d in out.days}
    assert day["2026-11-25"].sign_ups == 2  # one of them only by Nairobi's clock
    assert day["2026-11-24"].sign_ups == 1
    assert day["2026-11-25"].posts == 2
    assert day["2026-11-20"].posts == 1
    assert day["2026-11-23"].listings == 1
    assert day["2026-11-25"].reports_opened == 1
    assert day["2026-11-22"].reports_opened == 1
    assert day["2026-11-24"].reports_resolved == 1
    assert sum(d.sign_ups for d in out.days) == 3

    totals = out.totals
    assert totals.users == 9  # the purged account is not one
    assert (
        totals.active.last_day,
        totals.active.last_7_days,
        totals.active.last_14_days,
        totals.active.last_30_days,
    ) == (1, 2, 3, 4)
    assert totals.open_reports == 1
    assert totals.held_items == 1
    assert totals.waiting == 2  # the reported post and the held one
    assert totals.oldest_open_report_at == datetime(2026, 11, 25, 7, tzinfo=UTC)
    assert totals.oldest_waiting_since == datetime(2026, 11, 23, tzinfo=UTC)

    radius = out.radius
    assert radius.people == 19 * 100 + 5
    assert sum(band.people for band in radius.bands) == radius.people
    assert sum(radius.by_condition.values()) == radius.people
    # The lone Karatina cell is nowhere near enough people: the ceiling.
    assert radius.bands[-1].people == 5
    assert radius.by_condition["ceiling"] == 5
    # The Nyeri cluster: nobody has enough in their own cell, so none sit on the floor.
    assert radius.bands[0].people == 0
    assert [(b.from_km, b.to_km) for b in radius.bands] == [
        (1.0, 1.0),
        (1.0, 3.0),
        (3.0, 5.0),
        (5.0, 10.0),
        (10.0, 15.0),
        (15.0, 15.0),
    ]


async def test_the_overview_names_nobody(
    client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    seeded = await _seed_overview(db_session, redis_client)
    admin = (await make_staff(db_session, role=StaffRole.admin)).account.id

    response = await client.get(
        "/v1/admin/stats", headers=bearer(await token_for(db_session, admin, settings))
    )

    assert response.status_code == 200, response.text
    body = response.text
    uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    assert re.search(uuid_pattern, body) is None
    assert not any(name in body for name in seeded["names"])
    assert re.search(r"\+?254\d{9}", body) is None


async def test_the_overview_is_cached_for_a_few_minutes(
    client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    admin = (await make_staff(db_session, role=StaffRole.admin)).account.id
    headers = bearer(await token_for(db_session, admin, settings))
    first = (await client.get("/v1/admin/stats", headers=headers)).json()

    await make_user(db_session, at=NYERI_TOWN)
    second = (await client.get("/v1/admin/stats", headers=headers)).json()

    assert second["generated_at"] == first["generated_at"]
    assert second["totals"]["users"] == first["totals"]["users"]
    assert await redis_client.ttl(stats.CACHE_KEY) <= settings.admin_stats_cache_seconds


# ---------------------------------------------------------------------------
# CORS (decision D.1)
# ---------------------------------------------------------------------------
ADMIN_ORIGIN = "https://admin.example.test"
OTHER_ORIGIN = "https://web.example.test"


@pytest.fixture
async def cors_client(settings: Settings) -> Any:
    application = create_app(
        settings.model_copy(
            update={"admin_cors_origins": ADMIN_ORIGIN, "cors_origins": OTHER_ORIGIN}
        )
    )
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


def preflight(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }


async def test_the_dashboard_origin_may_call_the_admin_api(cors_client: httpx.AsyncClient) -> None:
    allowed = await cors_client.options("/v1/admin/queue", headers=preflight(ADMIN_ORIGIN))
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ADMIN_ORIGIN
    assert "authorization" in allowed.headers["access-control-allow-headers"].lower()
    # A bearer token, no cookies: credentials stay off.
    assert "access-control-allow-credentials" not in allowed.headers

    refused = await cors_client.get("/v1/admin/me", headers={"Origin": ADMIN_ORIGIN})
    assert refused.status_code == 401
    assert refused.headers["access-control-allow-origin"] == ADMIN_ORIGIN


async def test_the_dashboard_origin_gets_nothing_outside_the_admin_api(
    cors_client: httpx.AsyncClient,
) -> None:
    for path in ("/v1/feed", "/v1/me", "/health"):
        response = await cors_client.get(path, headers={"Origin": ADMIN_ORIGIN})
        assert "access-control-allow-origin" not in response.headers, path
    feed = await cors_client.options("/v1/feed", headers=preflight(ADMIN_ORIGIN))
    assert "access-control-allow-origin" not in feed.headers


async def test_other_origins_get_nothing_inside_the_admin_api(
    cors_client: httpx.AsyncClient,
) -> None:
    response = await cors_client.options("/v1/admin/queue", headers=preflight(OTHER_ORIGIN))
    assert "access-control-allow-origin" not in response.headers
    # And the general policy still works where it applies.
    general = await cors_client.get("/health", headers={"Origin": OTHER_ORIGIN})
    assert general.headers.get("access-control-allow-origin") == OTHER_ORIGIN


async def test_the_spread_gives_each_home_the_radius_its_feed_gets(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    """The spread stops walking at the first ring that holds both targets; the
    feed measures every ring up to the ceiling first. They must agree, home by
    home: a dense core, a thin edge, a place with people and no posts, and one
    nobody posts from at all."""
    await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=60, posts_per_cell=4, rings=4
    )
    await set_cell_density(
        db_session, origin=KARATINA, active_per_cell=3, posts_per_cell=0, rings=1
    )
    await db_session.flush()
    engine = RadiusEngine(db_session, redis_client, settings)

    entries = await engine.spread()
    cells_with_people = (
        await db_session.execute(
            select(CellActivity.cell, CellActivity.active_user_count).where(
                CellActivity.resolution == 8, CellActivity.active_user_count > 0
            )
        )
    ).all()
    assert len(entries) == len(cells_with_people) == 61 + 7

    expected = []
    for cell, people in cells_with_people:
        await redis_client.flushdb()
        feed = await engine.radius_for(RadiusFeature.feed, int(cell))
        expected.append((people, round(feed.radius_km, 6), feed.limited_by))
    got = [(e.people, round(e.radius_km, 6), e.limited_by) for e in entries]
    assert sorted(got) == sorted(expected)
    assert {limit for _, _, limit in got} >= {"ceiling"}
