"""The feed radius also counts recent posts (decision T.2).

Rings grow until they hold enough active users *and* enough recent posts. The
sections below follow the brief: the engine's two conditions, which posts count
(the window, the per-author cap, the exclusions, where a post is placed), the
refresh against a slow reference count, hysteresis on each condition, and the
reach estimate staying a count of people.
"""

from __future__ import annotations

import random
import uuid
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RadiusFeature, Settings
from app.modules.feed.models import Post
from app.modules.groups.models import Group, GroupJoinPolicy, GroupVisibility
from app.modules.location import cells
from app.modules.location.models import CellActivity
from app.modules.location.radius import RadiusEngine, RadiusResult
from app.modules.location.tasks import refresh_cell_activity
from app.modules.moderation.models import ContentStatus
from app.modules.users.models import User, UserStatus
from tests.factories import (
    KARATINA,
    NYERI_TOWN,
    Coordinates,
    make_user,
    offset_km,
    scatter,
    set_cell_density,
)

Authenticate = Callable[[User], Awaitable[httpx.AsyncClient]]

# Real time, fixed once: the feed's views compare against the clock.
NOW = datetime.now(UTC).replace(microsecond=0)


def cells_within(k: int) -> int:
    """Cells in a disk of k rings: 1, 7, 19, 37, 61, 91, 127..."""
    return 1 + 3 * k * (k + 1)


def first_ring(per_cell: int, target: int) -> int:
    k = 0
    while per_cell * cells_within(k) < target:
        k += 1
    return k


async def feed(engine: RadiusEngine, anchor: int) -> RadiusResult:
    return await engine.radius_for(RadiusFeature.feed, anchor)


async def set_counts(
    session: AsyncSession,
    anchor: int,
    *,
    rings: range,
    users: int | None = None,
    posts: int | None = None,
) -> None:
    """Rewrite the counts of every cell in the given rings around the anchor."""
    targets = [cell for k in rings for cell in cells.ring(anchor, k)]
    values: dict[str, int] = {}
    if users is not None:
        values["active_user_count"] = users
        values["registered_user_count"] = users
    if posts is not None:
        values["recent_post_count"] = posts
    await session.execute(
        update(CellActivity)
        .where(CellActivity.resolution == 8, CellActivity.cell.in_(targets))
        .values(**values)
    )


# ---------------------------------------------------------------------------
# Two conditions
# ---------------------------------------------------------------------------
async def test_enough_people_but_too_few_posts_widens_until_there_are_posts(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    """A busy estate where nobody posts: the people are close, the reading is
    not, so the radius goes out to where there is something to read."""
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=100, posts_per_cell=2, rings=12
    )
    result = await feed(RadiusEngine(db_session, redis_client, settings), anchor)

    expected = first_ring(2, settings.feed_target_recent_posts)
    assert expected > first_ring(100, settings.feed_target_active_users)
    assert result.rings_expanded == expected
    assert result.limited_by == "posts"
    assert result.recent_posts_counted >= settings.feed_target_recent_posts
    assert result.reached_target is True


async def test_enough_posts_but_too_few_people_widens_until_there_are_people(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=5, posts_per_cell=50, rings=12
    )
    result = await feed(RadiusEngine(db_session, redis_client, settings), anchor)

    expected = first_ring(5, settings.feed_target_active_users)
    assert expected > first_ring(50, settings.feed_target_recent_posts)
    assert result.rings_expanded == expected
    assert result.limited_by == "users"
    assert result.active_users_counted >= settings.feed_target_active_users


async def test_when_both_need_the_same_ring_both_are_named(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    # 4 a cell reaches 200 at ring 4 (244; 148 at ring 3); 1 a cell reaches 60
    # at ring 4 too (61; 37 at ring 3).
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=4, posts_per_cell=1, rings=12
    )
    result = await feed(RadiusEngine(db_session, redis_client, settings), anchor)

    assert result.rings_expanded == 4
    assert result.limited_by == "both"


async def test_both_met_in_the_home_cell_sits_on_the_floor(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=300, posts_per_cell=100, rings=2
    )
    result = await feed(RadiusEngine(db_session, redis_client, settings), anchor)

    assert result.rings_expanded == 0
    assert result.radius_km == settings.feed_radius_min_km
    assert result.limited_by == "floor"
    assert result.clamped_to_minimum is True
    assert result.reached_target is True


async def test_neither_met_by_fifteen_kilometres_sits_on_the_ceiling(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=1, posts_per_cell=0, rings=3
    )
    result = await feed(RadiusEngine(db_session, redis_client, settings), anchor)

    assert result.radius_km == settings.feed_radius_max_km
    assert result.limited_by == "ceiling"
    assert result.reached_target is False


async def test_people_without_posts_no_longer_shrink_the_radius(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    """The point of the change: before it, 100 people a cell gave a 1.5 km feed
    with nothing in it."""
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=100, posts_per_cell=0, rings=12
    )
    result = await feed(RadiusEngine(db_session, redis_client, settings), anchor)

    assert result.radius_km == settings.feed_radius_max_km
    assert result.limited_by == "ceiling"


async def test_a_posts_target_of_zero_turns_the_condition_off(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=100, posts_per_cell=0, rings=12
    )
    off = settings.model_copy(update={"feed_target_recent_posts": 0})
    result = await feed(RadiusEngine(db_session, redis_client, off), anchor)

    assert result.rings_expanded == first_ring(100, off.feed_target_active_users)
    assert result.limited_by == "users"


async def test_a_people_target_of_zero_lets_recent_posts_alone_set_the_radius(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    """The launch setting (decision T.3): nobody counted as active nearby, yet the
    feed is as small as the posts around it allow."""
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=0, posts_per_cell=5, rings=12
    )
    launch = settings.model_copy(update={"feed_target_active_users": 0})
    result = await feed(RadiusEngine(db_session, redis_client, launch), anchor)

    assert result.rings_expanded == first_ring(5, launch.feed_target_recent_posts)
    assert result.limited_by == "posts"
    assert result.radius_km < launch.feed_radius_max_km
    assert result.reached_target is True


async def test_with_both_targets_off_the_radius_sits_on_the_floor(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=0, posts_per_cell=0, rings=3
    )
    off = settings.model_copy(update={"feed_target_active_users": 0, "feed_target_recent_posts": 0})
    result = await feed(RadiusEngine(db_session, redis_client, off), anchor)

    assert result.radius_km == off.feed_radius_min_km


async def test_the_other_radii_follow_a_feed_radius_set_by_posts(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=100, posts_per_cell=2, rings=12
    )
    radii = await RadiusEngine(db_session, redis_client, settings).all_radii(anchor)
    feed_km = radii[RadiusFeature.feed].radius_km

    for feature, rule in settings.radius_rules.items():
        if rule.feed_multiplier is None:
            continue
        expected = min(max(feed_km * rule.feed_multiplier, rule.min_km), rule.max_km)
        assert radii[feature].radius_km == pytest.approx(expected), feature
        assert radii[feature].limited_by == "posts"


# ---------------------------------------------------------------------------
# Which posts count
# ---------------------------------------------------------------------------
async def put_post(
    session: AsyncSession,
    author: User,
    *,
    at: Coordinates = NYERI_TOWN,
    days_ago: float = 1.0,
    status: ContentStatus = ContentStatus.visible,
    deleted: bool = False,
    group_id: uuid.UUID | None = None,
    service_post_id: uuid.UUID | None = None,
) -> Post:
    """A post row placed at `at`, written directly so its age and state are exact."""
    where = cells.locate(at.latitude, at.longitude)
    created = NOW - timedelta(days=days_ago)
    post = Post(
        author_id=author.id,
        body="Water is back on in Kamakwa",
        category="general",
        cell_res9=where.cell_res9,
        cell_res8=where.cell_res8,
        cell_res7=where.cell_res7,
        cell_res6=where.cell_res6,
        centroid=where.centroid_wkt,
        status=status,
        created_at=created,
        deleted_at=created if deleted else None,
        group_id=group_id,
        service_post_id=service_post_id,
    )
    session.add(post)
    await session.flush()
    return post


async def counted(session: AsyncSession, at: Coordinates, resolution: int = 8) -> int:
    cell = cells.locate(at.latitude, at.longitude).cell_at(resolution)
    value = await session.scalar(
        select(CellActivity.recent_post_count).where(
            CellActivity.resolution == resolution, CellActivity.cell == cell
        )
    )
    return int(value or 0)


async def test_a_post_counts_inside_the_window_and_not_past_its_edge(
    db_session: AsyncSession, settings: Settings
) -> None:
    window = settings.feed_recent_post_days
    inside = await make_user(db_session, at=NYERI_TOWN)
    outside = await make_user(db_session, at=NYERI_TOWN)
    await put_post(db_session, inside, days_ago=window - 1 / 1440)
    await put_post(db_session, outside, days_ago=window + 1 / 1440)

    await refresh_cell_activity(db_session, settings=settings, now=NOW)

    assert await counted(db_session, NYERI_TOWN) == 1


async def test_one_author_counts_three_posts_however_many_they_make(
    db_session: AsyncSession, settings: Settings
) -> None:
    author = await make_user(db_session, at=NYERI_TOWN)
    for n in range(10):
        await put_post(db_session, author, days_ago=1 + n)

    await refresh_cell_activity(db_session, settings=settings, now=NOW)

    assert settings.feed_max_posts_per_author == 3
    for resolution in (8, 7, 6):
        assert await counted(db_session, NYERI_TOWN, resolution) == 3


async def test_the_cap_is_across_the_window_not_per_cell(
    db_session: AsyncSession, settings: Settings
) -> None:
    """Their three newest count, wherever they were posted. Per cell, someone who
    posts from five places would count fifteen times."""
    elsewhere = offset_km(NYERI_TOWN, north=4.0)
    author = await make_user(db_session, at=NYERI_TOWN)
    for n in range(3):
        await put_post(db_session, author, at=elsewhere, days_ago=1 + n)
    for n in range(7):
        await put_post(db_session, author, days_ago=5 + n)

    await refresh_cell_activity(db_session, settings=settings, now=NOW)

    assert await counted(db_session, elsewhere) == 3
    assert await counted(db_session, NYERI_TOWN) == 0


async def test_only_posts_the_feed_shows_from_active_accounts_count(
    db_session: AsyncSession, settings: Settings, authenticate: Authenticate
) -> None:
    """Exactly what the neighbourhood feed returns, less the posts of suspended
    and deletion-pending accounts (the product owner's choice). Each case has
    its own author so the per-author cap cannot hide a miscount."""

    async def author(status: UserStatus = UserStatus.active) -> User:
        return await make_user(db_session, at=NYERI_TOWN, status=status, created_days_ago=60)

    seller = await author()
    listing = await (await authenticate(seller)).post(
        "/v1/listings",
        json={
            "title": "Three-seater sofa, grey",
            "description": "Collect from Kamakwa",
            "category": "furniture",
            "condition": "good",
            "pricing": "negotiable",
            "price_kes": 8500,
        },
    )
    assert listing.status_code == 201, listing.text
    plumber = await author()
    offering = await (await authenticate(plumber)).post(
        "/v1/services",
        json={"kind": "offering", "category": "plumbing", "title": "Plumber, 10 years"},
    )
    assert offering.status_code == 201, offering.text

    owner = await author()
    group = Group(
        name="Estate committee",
        category="estate",
        visibility=GroupVisibility.private,
        join_policy=GroupJoinPolicy.open,
        owner_id=owner.id,
        created_by_id=owner.id,
    )
    db_session.add(group)
    await db_session.flush()

    # Two that count: a plain post, and one made as a service (the feed shows it).
    await put_post(db_session, await author())
    await put_post(db_session, plumber, service_post_id=uuid.UUID(offering.json()["id"]))
    # Everything else does not.
    await put_post(db_session, await author(), status=ContentStatus.hidden_pending_review)
    await put_post(db_session, await author(), status=ContentStatus.removed)
    await put_post(db_session, await author(), deleted=True)
    await put_post(db_session, owner, group_id=group.id)
    await put_post(db_session, await author(UserStatus.suspended))
    await put_post(db_session, await author(UserStatus.deletion_pending))
    await put_post(db_session, await author(UserStatus.banned))

    await refresh_cell_activity(db_session, settings=settings, now=NOW)

    assert await counted(db_session, NYERI_TOWN) == 2


async def test_a_post_stays_where_it_was_posted_when_its_author_moves(
    db_session: AsyncSession, settings: Settings
) -> None:
    author = await make_user(db_session, at=NYERI_TOWN)
    await put_post(db_session, author)
    moved = cells.locate(*KARATINA.as_tuple())
    author.home_cell_res8 = moved.cell_res8
    author.home_cell_res7 = moved.cell_res7
    author.home_cell_res6 = moved.cell_res6
    await db_session.flush()

    await refresh_cell_activity(db_session, settings=settings, now=NOW)

    assert await counted(db_session, NYERI_TOWN) == 1
    assert await counted(db_session, KARATINA) == 0


async def test_a_cell_with_posts_and_no_residents_is_kept_until_they_age_out(
    db_session: AsyncSession, settings: Settings
) -> None:
    """Somewhere people post from but nobody lives (a market, a campus) still
    holds something to read, and the stale-row clean-up must not drop it."""
    market = offset_km(NYERI_TOWN, east=6.0)
    author = await make_user(db_session, at=NYERI_TOWN)
    await put_post(db_session, author, at=market, days_ago=2)

    await refresh_cell_activity(db_session, settings=settings, now=NOW)
    await refresh_cell_activity(db_session, settings=settings, now=NOW + timedelta(minutes=15))
    row = await db_session.scalar(
        select(CellActivity).where(
            CellActivity.resolution == 8,
            CellActivity.cell == cells.locate(*market.as_tuple()).cell_res8,
        )
    )
    assert row is not None
    assert (row.active_user_count, row.registered_user_count, row.recent_post_count) == (0, 0, 1)

    later = NOW + timedelta(days=settings.feed_recent_post_days)
    await refresh_cell_activity(db_session, settings=settings, now=later)
    assert await counted(db_session, market) == 0


async def test_the_refresh_matches_a_slow_reference_count(
    db_session: AsyncSession, settings: Settings
) -> None:
    """A seeded neighbourhood of mixed posts, counted twice: by the refresh's SQL,
    and by plain Python straight from the brief's rules."""
    rng = random.Random(25)
    homes = scatter(NYERI_TOWN, count=24, radius_km=3.0, seed=11)
    statuses = [UserStatus.active] * 5 + [UserStatus.suspended, UserStatus.deletion_pending]
    authors = [await make_user(db_session, at=home, status=rng.choice(statuses)) for home in homes]
    places = scatter(NYERI_TOWN, count=40, radius_km=5.0, seed=12)
    post_states = [ContentStatus.visible] * 6 + [
        ContentStatus.hidden_pending_review,
        ContentStatus.removed,
    ]
    posts: list[tuple[Post, User]] = []
    minutes = rng.sample(range(1, 45 * 1440), 220)
    for minute in minutes:
        who = rng.choice(authors)
        post = await put_post(
            db_session,
            who,
            at=rng.choice(places),
            days_ago=minute / 1440,
            status=rng.choice(post_states),
            deleted=rng.random() < 0.08,
        )
        posts.append((post, who))

    await refresh_cell_activity(db_session, settings=settings, now=NOW)

    since = NOW - timedelta(days=settings.feed_recent_post_days)
    by_author: dict[uuid.UUID, list[Post]] = defaultdict(list)
    for post, who in posts:
        if (
            post.created_at >= since
            and post.status == ContentStatus.visible
            and post.deleted_at is None
            and post.group_id is None
            and who.status == UserStatus.active
        ):
            by_author[who.id].append(post)
    kept = [
        post
        for mine in by_author.values()
        for post in sorted(mine, key=lambda p: (p.created_at, p.id), reverse=True)[
            : settings.feed_max_posts_per_author
        ]
    ]
    assert kept, "the seed should leave something to count"

    for resolution, column in ((8, "cell_res8"), (7, "cell_res7"), (6, "cell_res6")):
        expected = Counter(getattr(post, column) for post in kept)
        rows = (
            await db_session.execute(
                select(CellActivity.cell, CellActivity.recent_post_count).where(
                    CellActivity.resolution == resolution, CellActivity.recent_post_count > 0
                )
            )
        ).all()
        assert {int(cell): count for cell, count in rows} == dict(expected), resolution


# ---------------------------------------------------------------------------
# Hysteresis, on each condition
# ---------------------------------------------------------------------------
async def test_users_a_little_short_keep_the_radius_and_well_short_grow_it(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    # Users bind at ring 4 (4 a cell: 244), posts at ring 3.
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=4, posts_per_cell=2, rings=12
    )
    engine = RadiusEngine(db_session, redis_client, settings)
    first = await feed(engine, anchor)
    assert (first.rings_expanded, first.limited_by) == (4, "users")

    # 3 a cell: 183 inside ring 4, 92% of 200. A fresh count says ring 5.
    await set_counts(db_session, anchor, rings=range(13), users=3)
    kept = await feed(engine, anchor)
    assert kept.rings_expanded == 4
    assert kept.source == "stabilised"
    assert kept.reached_target is False

    # 2 a cell: 122, 61%. Out to the first ring holding both: ring 6 (254).
    await set_counts(db_session, anchor, rings=range(13), users=2)
    grown = await feed(engine, anchor)
    assert grown.rings_expanded == first_ring(2, settings.feed_target_active_users) == 6
    assert grown.source == "computed"
    assert grown.limited_by == "users"


async def test_posts_a_little_short_keep_the_radius_and_well_short_grow_it(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    # Posts bind at ring 3 (2 a cell: 74; 38 at ring 2); people are plentiful.
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=100, posts_per_cell=2, rings=12
    )
    engine = RadiusEngine(db_session, redis_client, settings)
    first = await feed(engine, anchor)
    assert (first.rings_expanded, first.limited_by) == (3, "posts")

    # Rings 0 and 1 go quiet, and ring 2's first cell: 58 inside ring 3, 97%.
    await set_counts(db_session, anchor, rings=range(2), posts=0)
    await set_counts(db_session, anchor, rings=range(2, 3), posts=2)
    ring_two = cells.ring(anchor, 2)
    await db_session.execute(
        update(CellActivity)
        .where(CellActivity.resolution == 8, CellActivity.cell == next(iter(ring_two)))
        .values(recent_post_count=0)
    )
    kept = await feed(engine, anchor)
    assert kept.recent_posts_counted == 58
    assert kept.rings_expanded == 3
    assert kept.source == "stabilised"

    # Ring 2 goes quiet too: 36 inside ring 3, 60%. Out to ring 4 (84).
    await set_counts(db_session, anchor, rings=range(2, 3), posts=0)
    grown = await feed(engine, anchor)
    assert grown.rings_expanded == 4
    assert grown.limited_by == "posts"
    assert grown.source == "computed"


async def test_a_burst_of_posts_does_not_pull_the_radius_in_on_its_own(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=4, posts_per_cell=2, rings=12
    )
    engine = RadiusEngine(db_session, redis_client, settings)
    assert (await feed(engine, anchor)).rings_expanded == 4

    await set_counts(db_session, anchor, rings=range(13), posts=50)
    assert (await feed(engine, anchor)).rings_expanded == 4

    # People up 50% too, but only 111% of target inside ring 3 (6 a cell: 222).
    # A fresh count would say ring 3; the margin is not there yet.
    await set_counts(db_session, anchor, rings=range(13), users=6)
    held = await feed(engine, anchor)
    assert held.rings_expanded == 4
    assert held.source == "stabilised"


async def test_both_comfortably_over_target_nearer_in_shrinks_the_radius(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=4, posts_per_cell=2, rings=12
    )
    engine = RadiusEngine(db_session, redis_client, settings)
    assert (await feed(engine, anchor)).rings_expanded == 4

    # 7 a cell: 259 inside ring 3, 130%; posts 2 a cell: 74, 123%.
    await set_counts(db_session, anchor, rings=range(13), users=7)
    shrunk = await feed(engine, anchor)
    assert shrunk.rings_expanded == 3
    assert shrunk.source == "computed"


async def test_a_radius_cached_before_the_change_is_recomputed(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    """The old cache held kilometres only. Reading one as a ring would be a guess,
    so it is a miss and the radius is counted afresh."""
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=100, posts_per_cell=2, rings=12
    )
    await redis_client.set(RadiusEngine.cache_key(anchor), "1.4900")
    result = await feed(RadiusEngine(db_session, redis_client, settings), anchor)

    assert result.source == "computed"
    assert result.limited_by == "posts"
    cached = await redis_client.get(RadiusEngine.cache_key(anchor))
    assert cached is not None
    text = cached.decode() if isinstance(cached, bytes) else cached
    assert text.startswith(f"{result.rings_expanded}|posts|")


# ---------------------------------------------------------------------------
# The reach estimate still counts people
# ---------------------------------------------------------------------------
async def test_the_reach_estimate_counts_people_never_posts(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    anchor = await set_cell_density(
        db_session, origin=NYERI_TOWN, active_per_cell=3, posts_per_cell=0, rings=6
    )
    engine = RadiusEngine(db_session, redis_client, settings)
    before = await engine.active_users_within(anchor, 3.0)

    await set_counts(db_session, anchor, rings=range(7), posts=500)
    after = await engine.active_users_within(anchor, 3.0)

    assert before == after
    assert after % 3 == 0
    assert after == 3 * cells_within(3)


# ---------------------------------------------------------------------------
# The feed response
# ---------------------------------------------------------------------------
async def test_the_feed_says_how_recent_is_recent_and_which_alerts_are_fresh(
    db_session: AsyncSession, settings: Settings, authenticate: Authenticate
) -> None:
    author = await make_user(db_session, at=NYERI_TOWN)
    viewer = await make_user(db_session, at=NYERI_TOWN)
    fresh = await put_post(db_session, author, days_ago=settings.alert_fresh_days - 0.1)
    fresh.category = settings.alert_category
    stale = await put_post(db_session, author, days_ago=settings.alert_fresh_days + 0.1)
    stale.category = settings.alert_category
    general = await put_post(db_session, author, days_ago=0.5)
    old = await put_post(db_session, author, days_ago=settings.feed_recent_post_days + 5)
    await db_session.flush()

    body = (await (await authenticate(viewer)).get("/v1/feed")).json()

    assert body["recent_post_days"] == settings.feed_recent_post_days == 30
    flags = {item["id"]: item["fresh_alert"] for item in body["items"]}
    assert flags == {
        str(fresh.id): True,
        str(stale.id): False,
        str(general.id): False,
        # Older than the window, still in the feed: only the count ignores it.
        str(old.id): False,
    }
