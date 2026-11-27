"""Posting in a place means having been there (decision L.2).

Seeing is open everywhere. Posting in a zone (H3 res 7, about 2.5 km across)
needs 4 of the last 7 days there or in a touching zone, with one shortcut: a home
claimed at sign-up, with a verified phone, and never moved. Someone new to the
area they are in may comment, but not with links; and whoever starts a chat sends
no links in their first few messages, and is marked to the recipient if new.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.links import contains_link
from app.modules.feed import service as feed_service
from app.modules.groups import service as groups_service
from app.modules.groups.models import GroupJoinPolicy, GroupVisibility
from app.modules.location import cells, zones
from app.modules.location.models import UserZoneDay
from app.modules.users.models import User
from tests.factories import (
    KARATINA,
    NYERI_TOWN,
    give_zone_days,
    make_post,
    make_user,
    offset_km,
)
from tests.test_events import organise

Authenticate = Callable[[User], Awaitable[httpx.AsyncClient]]

POST = {"body": "Water is back on in Kamakwa", "category": "general"}


async def newcomer(db_session: AsyncSession, *, starter_left: bool = False, **kwargs: Any) -> User:
    """Lives in Nyeri town with none of the days yet. Their starter posts (L.3)
    are used up unless `starter_left`, so the days rule is what's tested."""
    user = await make_user(db_session, at=NYERI_TOWN, established=False, **kwargs)
    if not starter_left:
        user.starter_posts_used = 3
        await db_session.flush()
    return user


async def zone_rows(db_session: AsyncSession, user: User) -> list[UserZoneDay]:
    return list(
        (await db_session.execute(select(UserZoneDay).where(UserZoneDay.user_id == user.id)))
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------
async def test_reporting_where_the_phone_is_records_a_day_in_its_zone(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    user = await newcomer(db_session)

    await (await authenticate(user)).post("/v1/me/explore", json=KARATINA.as_payload())

    (row,) = await zone_rows(db_session, user)
    karatina_cell = cells.locate(KARATINA.latitude, KARATINA.longitude).cell_res9
    assert row.zone == zones.zone_of(karatina_cell)
    assert row.days_mask == 1


async def test_the_same_zone_on_a_later_day_adds_a_day(db_session: AsyncSession) -> None:
    user = await newcomer(db_session)
    cell = cells.locate(KARATINA.latitude, KARATINA.longitude).cell_res9
    today = zones.today_utc()

    await zones.record(db_session, user_id=user.id, cell=cell, today=today - timedelta(days=2))
    await zones.record(db_session, user_id=user.id, cell=cell, today=today)

    (row,) = await zone_rows(db_session, user)
    assert row.days_mask == 0b101
    assert row.updated_on == today


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------
async def test_new_to_an_area_a_post_is_refused_with_the_days_so_far(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    user = await newcomer(db_session)
    await give_zone_days(db_session, user, NYERI_TOWN, days=3)

    refused = await (await authenticate(user)).post("/v1/posts", json=POST)

    assert refused.status_code == 403
    details = refused.json()["error"]["details"]
    assert details == {
        "reason": "new_to_area",
        "days": 3,
        "needed": 4,
        "window_days": 7,
        "starter_posts_left": 0,
    }


async def test_four_days_in_the_week_and_they_may_post(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    user = await newcomer(db_session)
    await give_zone_days(db_session, user, NYERI_TOWN, days=4)

    posted = await (await authenticate(user)).post("/v1/posts", json=POST)

    assert posted.status_code == 201, posted.text


async def test_days_in_a_touching_zone_count(db_session: AsyncSession, settings: Settings) -> None:
    """Living near a zone's edge is not a reason to wait longer."""
    user = await newcomer(db_session)
    here = cells.locate(NYERI_TOWN.latitude, NYERI_TOWN.longitude).cell_res9
    neighbour = next(c for c in cells.disk(zones.zone_of(here), 1) if c != zones.zone_of(here))
    db_session.add(
        UserZoneDay(user_id=user.id, zone=neighbour, days_mask=0b1111, updated_on=zones.today_utc())
    )
    await db_session.flush()

    result = await zones.standing(db_session, user=user, cell=here, settings=settings)

    assert result.days == 4
    assert result.may_post


async def test_days_older_than_a_week_do_not_count(
    db_session: AsyncSession, settings: Settings
) -> None:
    user = await newcomer(db_session)
    here = cells.locate(NYERI_TOWN.latitude, NYERI_TOWN.longitude).cell_res9
    db_session.add(
        UserZoneDay(
            user_id=user.id,
            zone=zones.zone_of(here),
            days_mask=0b1111,
            updated_on=zones.today_utc() - timedelta(days=5),
        )
    )
    await db_session.flush()

    result = await zones.standing(db_session, user=user, cell=here, settings=settings)

    # Four days ending five days ago: only the newest two are still inside the week.
    assert result.days == 2
    assert not result.may_post


async def test_listings_services_and_public_groups_need_the_days_too(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await newcomer(db_session))

    attempts = [
        await client.post(
            "/v1/listings",
            json={
                "title": "Sofa",
                "category": "furniture",
                "condition": "good",
                "pricing": "fixed",
                "price_kes": 5000,
            },
        ),
        await client.post(
            "/v1/services", json={"kind": "offering", "category": "plumbing", "title": "Plumber"}
        ),
        await client.post(
            "/v1/groups",
            json={"name": "Kamakwa walkers", "category": "sports", "visibility": "public"},
        ),
    ]

    for attempt in attempts:
        assert attempt.status_code == 403, attempt.text
        assert attempt.json()["error"]["details"]["reason"] == "new_to_area"


async def test_a_group_post_is_not_placed_so_needs_no_days(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    owner = await make_user(db_session, at=NYERI_TOWN)
    member = await newcomer(db_session)
    group = await groups_service.create_group(
        db_session,
        redis_client,
        creator=owner,
        name="Kamakwa church choir",
        description=None,
        category="church",
        visibility=GroupVisibility.private,
        join_policy=GroupJoinPolicy.approval,
        requires_post_approval=False,
        rules=None,
        cover_media_id=None,
        settings=settings,
    )

    post, _reach = await feed_service.create_post(
        db_session,
        redis_client,
        author=member,
        body="Practice moved to Thursday",
        category="general",
        media_ids=[],
        settings=settings,
        group=group,
    )

    assert post.group_id == group.id


async def test_a_public_event_needs_the_days_at_its_venue(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    """A public event is placed at its venue; group and private ones reach only
    the people invited."""
    # An older account, so the daily cap on new accounts' events doesn't interfere.
    client = await authenticate(await newcomer(db_session, created_days_ago=60))

    refused = await organise(client, expect=403)
    await organise(client, visibility="private")

    assert refused["error"]["details"]["reason"] == "new_to_area"


# ---------------------------------------------------------------------------
# Starter posts (decision L.3)
# ---------------------------------------------------------------------------
async def starter_left(client: httpx.AsyncClient) -> int:
    return int((await client.get("/v1/me")).json()["starter_posts_left"])


LISTING = {
    "title": "Sofa",
    "category": "furniture",
    "condition": "good",
    "pricing": "fixed",
    "price_kes": 5000,
}


async def test_a_newcomer_gets_three_starter_posts_then_waits_for_the_days(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await newcomer(db_session, starter_left=True))
    assert await starter_left(client) == 3

    made = [
        await client.post("/v1/posts", json=POST),
        await client.post("/v1/listings", json=LISTING),
        await client.post(
            "/v1/services", json={"kind": "seeking", "category": "plumbing", "title": "Gate fix?"}
        ),
    ]
    assert [r.status_code for r in made] == [201, 201, 201], [r.text for r in made]
    assert await starter_left(client) == 0

    refused = await client.post("/v1/posts", json=POST)
    assert refused.status_code == 403
    details = refused.json()["error"]["details"]
    assert details["reason"] == "new_to_area"
    assert details["starter_posts_left"] == 0
    assert "used your 3 starter posts" in refused.json()["error"]["message"]


async def test_a_starter_post_has_no_links_and_a_refusal_costs_nothing(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await newcomer(db_session, starter_left=True))

    refused = await client.post(
        "/v1/posts", json={"body": "Cheap phones at bit.ly/deal", "category": "general"}
    )

    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "links_not_allowed_yet"
    assert await starter_left(client) == 3


async def test_starter_posts_go_anywhere_the_phone_is(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await newcomer(db_session, starter_left=True))

    await client.post("/v1/me/explore", json=KARATINA.as_payload())
    posted = await client.post("/v1/posts", json=POST)

    assert posted.status_code == 201, posted.text


async def test_jobs_need_the_days_even_with_starter_posts_left(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await newcomer(db_session, starter_left=True, created_days_ago=60))

    job = await client.post(
        "/v1/services", json={"kind": "hiring", "category": "other", "title": "Shop assistant"}
    )

    assert job.status_code == 403
    assert job.json()["error"]["details"]["reason"] == "new_to_area"
    assert await starter_left(client) == 3


async def test_with_the_days_a_post_uses_no_starter_post(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await make_user(db_session, at=NYERI_TOWN))

    assert (await client.post("/v1/posts", json=POST)).status_code == 201
    assert await starter_left(client) == 3


# ---------------------------------------------------------------------------
# Stories (decision L.3)
# ---------------------------------------------------------------------------
async def test_stories_need_no_days(db_session: AsyncSession, authenticate: Authenticate) -> None:
    client = await authenticate(await newcomer(db_session))

    for line in ("Mandazi at the stage", "Rain coming", "Lights back on"):
        story = await client.post("/v1/stories", json={"kind": "text", "text": line})
        assert story.status_code == 201, story.text


async def test_a_newcomers_story_has_no_links(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await newcomer(db_session))

    refused = await client.post("/v1/stories", json={"kind": "text", "text": "Deals: bit.ly/x"})

    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "links_not_allowed_yet"


async def test_stories_are_seen_only_around_their_zone(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    """Inside the feed's 15 km, but beyond the zone and the zones touching it."""
    author = await make_user(db_session, at=NYERI_TOWN)
    next_door = await make_user(db_session, at=offset_km(NYERI_TOWN, north=0.5))
    across_town = await make_user(db_session, at=offset_km(NYERI_TOWN, north=11.0))
    posted = await (await authenticate(author)).post(
        "/v1/stories", json={"kind": "text", "text": "Mandazi at the stage"}
    )
    story_id = posted.json()["id"]

    async def sees(viewer: User) -> bool:
        listed = (await (await authenticate(viewer)).get("/v1/stories")).json()["items"]
        return story_id in {item["id"] for item in listed}

    assert await sees(next_door)
    assert not await sees(across_town)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
async def test_someone_new_may_comment_but_not_with_a_link(
    db_session: AsyncSession, redis_client: Redis, authenticate: Authenticate
) -> None:
    local = await make_user(db_session, at=NYERI_TOWN)
    post = await make_post(db_session, redis_client, author=local, body="Who fixes gates?")
    client = await authenticate(await newcomer(db_session))

    plain = await client.post(f"/v1/posts/{post.id}/comments", json={"body": "Try Kamau"})
    linked = await client.post(
        f"/v1/posts/{post.id}/comments", json={"body": "See www.gatefix.co.ke for prices"}
    )

    assert plain.status_code == 201, plain.text
    assert linked.status_code == 403
    assert linked.json()["error"]["details"]["reason"] == "links_not_allowed_yet"


async def test_a_local_may_put_a_link_in_a_comment(
    db_session: AsyncSession, redis_client: Redis, authenticate: Authenticate
) -> None:
    local = await make_user(db_session, at=NYERI_TOWN)
    post = await make_post(db_session, redis_client, author=local, body="Who fixes gates?")
    # Past the new-account window too: a brand-new account shares no links (L.5).
    neighbour = await make_user(db_session, at=offset_km(NYERI_TOWN, north=0.3), created_days_ago=3)

    linked = await (await authenticate(neighbour)).post(
        f"/v1/posts/{post.id}/comments", json={"body": "See www.gatefix.co.ke for prices"}
    )

    assert linked.status_code == 201, linked.text


# ---------------------------------------------------------------------------
# New accounts share no links, wherever they post (decision L.5)
# ---------------------------------------------------------------------------
LINK = "Prices at www.gatefix.co.ke"


async def test_a_new_account_shares_no_links_even_with_the_days(
    db_session: AsyncSession, authenticate: Authenticate, settings: Settings
) -> None:
    client = await authenticate(await make_user(db_session, at=NYERI_TOWN, created_days_ago=0))

    linked = await client.post("/v1/posts", json={**POST, "body": LINK})
    plain = await client.post("/v1/posts", json=POST)

    assert linked.status_code == 403
    assert linked.json()["error"]["details"] == {
        "reason": "links_not_allowed_yet",
        "new_account": True,
        "hours": settings.new_account_age_hours,
    }
    assert "2 days old" in linked.json()["error"]["message"]
    assert plain.status_code == 201, plain.text


async def test_past_the_new_account_window_links_are_fine(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await make_user(db_session, at=NYERI_TOWN, created_days_ago=3))

    linked = await client.post("/v1/posts", json={**POST, "body": LINK})

    assert linked.status_code == 201, linked.text


async def test_a_new_accounts_links_are_refused_everywhere_it_posts(
    db_session: AsyncSession, redis_client: Redis, authenticate: Authenticate
) -> None:
    local = await make_user(db_session, at=NYERI_TOWN, created_days_ago=30)
    post = await make_post(db_session, redis_client, author=local, body="Who fixes gates?")
    client = await authenticate(await make_user(db_session, at=NYERI_TOWN, created_days_ago=0))

    attempts = {
        "listing": await client.post(
            "/v1/listings",
            json={
                "title": "Gate, as new",
                "description": LINK,
                "category": "furniture",
                "condition": "good",
                "pricing": "fixed",
                "price_kes": 5000,
            },
        ),
        "service": await client.post(
            "/v1/services",
            json={
                "kind": "offering",
                "category": "plumbing",
                "title": "Plumber",
                "description": LINK,
            },
        ),
        "public group": await client.post(
            "/v1/groups",
            json={
                "name": "Kamakwa walkers",
                "description": LINK,
                "category": "sports",
                "visibility": "public",
            },
        ),
        "comment": await client.post(f"/v1/posts/{post.id}/comments", json={"body": LINK}),
        "story": await client.post("/v1/stories", json={"kind": "text", "text": LINK}),
    }

    for what, attempt in attempts.items():
        assert attempt.status_code == 403, (what, attempt.text)
        details = attempt.json()["error"]["details"]
        assert details["reason"] == "links_not_allowed_yet", what
        assert details["new_account"] is True, what


async def test_with_presence_days_set_to_one_a_first_day_is_enough(
    db_session: AsyncSession, authenticate: Authenticate, app: Any, settings: Settings
) -> None:
    """The launch setting (decision L.5): post where you are from your first day."""
    from app.core.config import get_settings

    launch = settings.model_copy(update={"posting_presence_days": 1})
    app.dependency_overrides[get_settings] = lambda: launch
    user = await newcomer(db_session)
    await give_zone_days(db_session, user, NYERI_TOWN, days=1)
    elsewhere = offset_km(NYERI_TOWN, north=40.0)

    here = await (await authenticate(user)).post("/v1/posts", json=POST)

    assert here.status_code == 201, here.text
    # Still only where they've been: a day in Nyeri says nothing about 40 km away.
    standing = await zones.standing(
        db_session,
        user=user,
        cell=cells.locate(elsewhere.latitude, elsewhere.longitude).cell_res9,
        settings=launch,
    )
    assert not standing.may_post


# ---------------------------------------------------------------------------
# Chats
# ---------------------------------------------------------------------------
async def open_chat(client: httpx.AsyncClient, other: User) -> str:
    response = await client.post("/v1/conversations/direct", json={"user_id": str(other.id)})
    assert response.status_code in (200, 201), response.text
    return str(response.json()["id"])


async def say(client: httpx.AsyncClient, conversation_id: str, body: str) -> httpx.Response:
    return await client.post(f"/v1/conversations/{conversation_id}/messages", json={"body": body})


async def test_whoever_starts_a_chat_sends_no_links_at_first(
    db_session: AsyncSession, authenticate: Authenticate, settings: Settings
) -> None:
    asker = await make_user(db_session, at=NYERI_TOWN)
    other = await make_user(db_session, at=offset_km(NYERI_TOWN, north=0.4))
    conversation = await open_chat(await authenticate(asker), other)

    refused = await say(await authenticate(asker), conversation, "Details at bit.ly/xyz")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "links_not_allowed_yet"

    assert (await say(await authenticate(asker), conversation, "Hello!")).status_code == 201
    # The other person may share a link at once.
    reply = await say(await authenticate(other), conversation, "Menu: www.mamas-kitchen.co.ke")
    assert reply.status_code == 201, reply.text
    for _ in range(settings.initiator_link_free_messages - 1):
        await say(await authenticate(asker), conversation, "Okay, noted")
    allowed = await say(await authenticate(asker), conversation, "Mine: www.example.com")
    assert allowed.status_code == 201, allowed.text


async def test_the_recipient_is_told_the_asker_is_new_to_the_area(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    asker = await newcomer(db_session)
    other = await make_user(db_session, at=offset_km(NYERI_TOWN, north=0.4))
    conversation = await open_chat(await authenticate(asker), other)
    await say(await authenticate(asker), conversation, "Hello, is the room still free?")

    as_recipient = (
        await (await authenticate(other)).get(f"/v1/conversations/{conversation}")
    ).json()
    as_sender = (await (await authenticate(asker)).get(f"/v1/conversations/{conversation}")).json()

    assert as_recipient["requester_new_to_area"] is True
    assert as_sender["requester_new_to_area"] is False


async def test_a_local_asker_is_not_marked(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    asker = await make_user(db_session, at=NYERI_TOWN)
    other = await make_user(db_session, at=offset_km(NYERI_TOWN, north=0.4))
    conversation = await open_chat(await authenticate(asker), other)
    await say(await authenticate(asker), conversation, "Hello neighbour")

    seen = (await (await authenticate(other)).get(f"/v1/conversations/{conversation}")).json()

    assert seen["requester_new_to_area"] is False


# ---------------------------------------------------------------------------
# Keeping only a week, and the data rights
# ---------------------------------------------------------------------------
async def test_the_nightly_roll_deletes_weeks_old_zone_days(db_session: AsyncSession) -> None:
    user = await newcomer(db_session)
    today = zones.today_utc()
    for days_ago, cell_at in ((0, NYERI_TOWN), (7, KARATINA)):
        cell = cells.locate(cell_at.latitude, cell_at.longitude).cell_res9
        await zones.record(
            db_session, user_id=user.id, cell=cell, today=today - timedelta(days=days_ago)
        )

    deleted = await zones.prune(db_session, today=today)

    assert deleted == 1
    (kept,) = await zone_rows(db_session, user)
    assert kept.updated_on == today


async def test_the_export_says_how_many_days_without_naming_cells(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    user = await newcomer(db_session)
    await give_zone_days(db_session, user, NYERI_TOWN, days=3)

    exported = (await (await authenticate(user)).get("/v1/me/export")).json()["zones"]

    assert exported["zones_this_week"] == [{"days_recorded": 3}]


async def test_the_purge_deletes_a_persons_zone_days(db_session: AsyncSession) -> None:
    user = await newcomer(db_session)
    await give_zone_days(db_session, user, NYERI_TOWN)

    await zones.purge_user_zones(db_session, user_id=user.id)

    assert await zone_rows(db_session, user) == []


# ---------------------------------------------------------------------------
# Spotting links
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "https://example.com/pay",
        "visit www.example.org",
        "mpesa-help.co.ke",
        "Pay at kazi-jobs.ke/apply",
        "chat me wa.me/254712345678",
        "short link: bit.ly/3xYz",
        "Join t.me/nyerideals",
    ],
)
def test_links_are_spotted(text: str) -> None:
    assert contains_link(text)


@pytest.mark.parametrize(
    "text",
    [
        "Water is back on in Kamakwa",
        "Meet at 8.30am by the stage",
        "It's 3.5 km from town",
        "Mt. Kenya view, Ksh. 500",
        "e.g. tomatoes, onions",
        "",
    ],
)
def test_ordinary_words_are_not_links(text: str) -> None:
    assert not contains_link(text)
