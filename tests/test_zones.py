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
from app.modules.location import service as location_service
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


async def newcomer(db_session: AsyncSession, **kwargs: Any) -> User:
    """Lives in Nyeri town, but without the sign-up shortcut: has the days to earn."""
    return await make_user(db_session, at=NYERI_TOWN, claimed_home=False, **kwargs)


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
    assert details == {"reason": "new_to_area", "days": 3, "needed": 4, "window_days": 7}


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


async def test_listings_services_stories_and_public_groups_need_the_days_too(
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
        await client.post("/v1/stories", json={"kind": "text", "text": "Hello Kamakwa"}),
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
# The sign-up shortcut
# ---------------------------------------------------------------------------
async def test_a_home_claimed_at_sign_up_with_a_verified_phone_posts_at_once(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    user = await make_user(db_session, at=NYERI_TOWN, claimed_home=True)

    posted = await (await authenticate(user)).post("/v1/posts", json=POST)

    assert posted.status_code == 201, posted.text


async def test_the_shortcut_is_for_home_not_for_somewhere_else(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    user = await make_user(db_session, at=NYERI_TOWN, claimed_home=True)
    client = await authenticate(user)

    await client.post("/v1/me/explore", json=KARATINA.as_payload())
    refused = await client.post("/v1/posts", json=POST)

    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "new_to_area"


async def test_no_verified_phone_means_no_shortcut(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    """Signed up with Google and no number yet (decision A.1)."""
    user = await make_user(db_session, at=NYERI_TOWN, claimed_home=True)
    user.phone_number = None
    user.phone_verified_at = None
    user.google_sub = "g-zones"
    await db_session.flush()

    refused = await (await authenticate(user)).post("/v1/posts", json=POST)

    assert refused.status_code == 403


async def test_saying_yes_at_sign_up_claims_home_and_no_does_not(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    yes = await make_user(db_session)
    no = await make_user(db_session)

    for user, at_home in ((yes, True), (no, False)):
        await location_service.set_home_location(
            db_session,
            redis_client,
            user=user,
            latitude=NYERI_TOWN.latitude,
            longitude=NYERI_TOWN.longitude,
            settings=settings,
            at_home=at_home,
        )

    assert yes.home_claimed_at_signup is True
    assert no.home_claimed_at_signup is False
    # Either way they were there today.
    assert len(await zone_rows(db_session, yes)) == 1


async def test_moving_home_gives_up_the_shortcut(
    db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    user = await make_user(db_session, at=NYERI_TOWN, claimed_home=True)
    no_cooldown = settings.model_copy(update={"home_change_cooldown_days": 0})

    await location_service.set_home_location(
        db_session,
        redis_client,
        user=user,
        latitude=KARATINA.latitude,
        longitude=KARATINA.longitude,
        settings=no_cooldown,
    )

    assert user.home_claimed_at_signup is False


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
    neighbour = await make_user(db_session, at=offset_km(NYERI_TOWN, north=0.3))

    linked = await (await authenticate(neighbour)).post(
        f"/v1/posts/{post.id}/comments", json={"body": "See www.gatefix.co.ke for prices"}
    )

    assert linked.status_code == 201, linked.text


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
