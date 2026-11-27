"""Polls on posts, and how many people saw a post (decision F.1)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.feed import polls
from app.modules.feed.models import Post, PostPoll, PostPollVote
from app.modules.feed.service import export_author_content, purge_author_content
from app.modules.users.models import User
from app.modules.users.service import block_user
from tests.factories import NYERI_TOWN, make_user, offset_km

Authenticate = Callable[[User], Awaitable[httpx.AsyncClient]]

QUESTION = "When should we do the Kamakwa clean-up?"
OPTIONS = ["Saturday morning", "Sunday afternoon", "Next weekend"]


async def neighbour(db_session: AsyncSession, north: float = 0.3) -> User:
    return await make_user(db_session, at=offset_km(NYERI_TOWN, north=north), created_days_ago=30)


async def post_poll(
    client: httpx.AsyncClient, options: list[str] | None = None, **poll: Any
) -> httpx.Response:
    return await client.post(
        "/v1/posts",
        json={
            "body": QUESTION,
            "category": "question",
            "poll": {"options": options or OPTIONS, **poll},
        },
    )


async def a_poll(
    db_session: AsyncSession, authenticate: Authenticate
) -> tuple[User, dict[str, Any]]:
    author = await make_user(db_session, at=NYERI_TOWN, created_days_ago=30)
    created = await post_poll(await authenticate(author))
    assert created.status_code == 201, created.text
    return author, created.json()["post"]


async def vote(client: httpx.AsyncClient, post: dict[str, Any], index: int) -> httpx.Response:
    option_id = post["poll"]["options"][index]["id"]
    return await client.post(f"/v1/posts/{post['id']}/poll/vote", json={"option_id": option_id})


# ---------------------------------------------------------------------------
# Making a poll
# ---------------------------------------------------------------------------
async def test_a_post_can_ask_a_question_with_answers(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    _author, post = await a_poll(db_session, authenticate)

    poll = post["poll"]
    assert post["body"] == QUESTION
    assert [option["text"] for option in poll["options"]] == OPTIONS
    # The author sees the results from the start; there are none yet.
    assert poll["results_visible"] is True
    assert [option["votes"] for option in poll["options"]] == [0, 0, 0]
    assert poll["total_votes"] == 0 and poll["closed"] is False and poll["voted"] is False
    closes = datetime.fromisoformat(poll["closes_at"])
    assert timedelta(hours=71) < closes - datetime.now(UTC) <= timedelta(hours=72)


@pytest.mark.parametrize(
    ("options", "poll"),
    [
        (["Only one"], {}),
        (["A", "B", "C", "D", "E"], {}),
        (["Same", "same "], {}),
        (["Fine", "  "], {}),
        (["Fine", "x" * 81], {}),
        (OPTIONS, {"duration_hours": 5}),
    ],
    ids=["too few", "too many", "repeated", "empty", "too long", "odd duration"],
)
async def test_a_poll_needs_two_to_four_different_short_answers(
    db_session: AsyncSession,
    authenticate: Authenticate,
    options: list[str],
    poll: dict[str, Any],
) -> None:
    client = await authenticate(await make_user(db_session, at=NYERI_TOWN, created_days_ago=30))

    response = await post_poll(client, options, **poll)

    assert response.status_code in (400, 422), response.text


async def test_a_new_accounts_poll_answers_carry_no_links(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    client = await authenticate(await make_user(db_session, at=NYERI_TOWN, created_days_ago=0))

    response = await post_poll(client, ["Yes", "See www.example.co.ke"])

    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason"] == "links_not_allowed_yet"


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------
async def test_results_show_once_you_have_voted(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    _author, post = await a_poll(db_session, authenticate)
    voter = await neighbour(db_session)
    client = await authenticate(voter)

    before = (await client.get(f"/v1/posts/{post['id']}")).json()["poll"]
    voted = await vote(client, post, 1)
    after = (await client.get(f"/v1/posts/{post['id']}")).json()["poll"]

    assert before["results_visible"] is False
    assert all(option["votes"] is None for option in before["options"])
    assert voted.status_code == 200, voted.text
    assert [option["votes"] for option in voted.json()["options"]] == [0, 1, 0]
    assert after["voted"] is True and after["total_votes"] == 1
    assert [option["votes"] for option in after["options"]] == [0, 1, 0]


async def test_one_vote_each_and_it_cannot_be_changed(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    _author, post = await a_poll(db_session, authenticate)
    client = await authenticate(await neighbour(db_session))

    first = await vote(client, post, 0)
    again = await vote(client, post, 2)

    assert first.status_code == 200
    assert again.status_code == 409
    assert again.json()["error"]["details"]["reason"] == "already_voted"
    assert [option["votes"] for option in first.json()["options"]] == [1, 0, 0]


async def test_nobody_can_tell_how_anyone_voted(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    """What is stored is that someone voted, never what they chose."""
    _author, post = await a_poll(db_session, authenticate)
    voter = await neighbour(db_session)
    await vote(await authenticate(voter), post, 2)

    columns = {column.key for column in inspect(PostPollVote).columns}
    assert columns == {"post_id", "user_id", "created_at"}
    stored = (
        await db_session.execute(select(PostPollVote).where(PostPollVote.user_id == voter.id))
    ).scalar_one()
    assert str(stored.post_id) == post["id"]


async def test_a_closed_poll_takes_no_votes_and_shows_its_results_to_all(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    _author, post = await a_poll(db_session, authenticate)
    await vote(await authenticate(await neighbour(db_session)), post, 0)
    await db_session.execute(
        update(PostPoll)
        .where(PostPoll.post_id == uuid.UUID(post["id"]))
        .values(closes_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    db_session.expire_all()
    latecomer = await authenticate(await neighbour(db_session, north=0.6))

    refused = await vote(latecomer, post, 1)
    seen = (await latecomer.get(f"/v1/posts/{post['id']}")).json()["poll"]

    assert refused.status_code == 409
    assert refused.json()["error"]["details"]["reason"] == "poll_closed"
    assert seen["closed"] is True and seen["results_visible"] is True
    assert [option["votes"] for option in seen["options"]] == [1, 0, 0]


async def test_a_post_without_a_poll_takes_no_votes(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    author = await make_user(db_session, at=NYERI_TOWN, created_days_ago=30)
    created = await (await authenticate(author)).post(
        "/v1/posts", json={"body": "Water is back on", "category": "general"}
    )
    post_id = created.json()["post"]["id"]

    response = await (await authenticate(await neighbour(db_session))).post(
        f"/v1/posts/{post_id}/poll/vote", json={"option_id": str(uuid.uuid4())}
    )

    assert created.json()["post"]["poll"] is None
    assert response.status_code == 404


async def test_a_purged_account_leaves_its_votes_counted_but_unrecorded(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    _author, post = await a_poll(db_session, authenticate)
    voter = await neighbour(db_session)
    voter_id = voter.id
    await vote(await authenticate(voter), post, 0)

    exported = await export_author_content(db_session, user_id=voter_id)
    await purge_author_content(db_session, user_id=voter_id)

    assert exported["poll_votes"][0]["post_id"] == post["id"]
    assert "option" not in exported["poll_votes"][0]
    left = await db_session.scalar(
        select(PostPollVote.post_id).where(PostPollVote.user_id == voter_id)
    )
    assert left is None
    poll = await db_session.get(PostPoll, uuid.UUID(post["id"]))
    assert poll is not None and poll.vote_count == 1


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
async def views_of(db_session: AsyncSession, redis: Redis, post_id: str) -> int:
    await polls.flush_view_counts(db_session, redis)
    db_session.expire_all()
    count = await db_session.scalar(select(Post.view_count).where(Post.id == uuid.UUID(post_id)))
    return int(count or 0)


async def test_each_person_counts_once_and_the_author_not_at_all(
    db_session: AsyncSession, redis_client: Redis, authenticate: Authenticate
) -> None:
    author, post = await a_poll(db_session, authenticate)
    first, second = await neighbour(db_session), await neighbour(db_session, north=0.6)

    for viewer in (first, first, second, author):
        seen = await (await authenticate(viewer)).post(
            "/v1/posts/views", json={"post_ids": [post["id"]]}
        )
        assert seen.status_code == 204, seen.text

    assert await views_of(db_session, redis_client, post["id"]) == 2
    shown = (await (await authenticate(first)).get(f"/v1/posts/{post['id']}")).json()
    assert shown["view_count"] == 2


async def test_views_never_say_who(
    db_session: AsyncSession, authenticate: Authenticate, settings: Settings
) -> None:
    """The count is a HyperLogLog: it can say how many, not who."""
    _author, post = await a_poll(db_session, authenticate)
    viewer = await neighbour(db_session)
    await (await authenticate(viewer)).post("/v1/posts/views", json={"post_ids": [post["id"]]})

    binary = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        stored = await binary.get(polls.views_key(post["id"]))
    finally:
        await binary.aclose()

    assert stored is not None
    assert str(viewer.id).encode() not in stored
    assert viewer.id.bytes not in stored


async def test_someone_blocked_adds_no_view(
    db_session: AsyncSession, redis_client: Redis, authenticate: Authenticate
) -> None:
    author, post = await a_poll(db_session, authenticate)
    blocked = await neighbour(db_session)
    await block_user(db_session, blocker=author, blocked_id=blocked.id)

    await (await authenticate(blocked)).post("/v1/posts/views", json={"post_ids": [post["id"]]})

    assert await views_of(db_session, redis_client, post["id"]) == 0


async def test_a_count_never_goes_down(
    db_session: AsyncSession, redis_client: Redis, authenticate: Authenticate
) -> None:
    """If Redis lost a post's counter, the row keeps what it had."""
    _author, post = await a_poll(db_session, authenticate)
    for north in (0.3, 0.6, 0.9):
        await (await authenticate(await neighbour(db_session, north))).post(
            "/v1/posts/views", json={"post_ids": [post["id"]]}
        )
    assert await views_of(db_session, redis_client, post["id"]) == 3

    await redis_client.delete(polls.views_key(post["id"]))
    await (await authenticate(await neighbour(db_session, 1.2))).post(
        "/v1/posts/views", json={"post_ids": [post["id"]]}
    )

    assert await views_of(db_session, redis_client, post["id"]) == 3


async def test_acting_on_a_post_counts_as_seeing_it(
    db_session: AsyncSession, redis_client: Redis, authenticate: Authenticate
) -> None:
    """Never more voters than viewers, whatever the app reported: two people on
    one phone, the second never reported, still both count."""
    author, post = await a_poll(db_session, authenticate)
    voters = [await neighbour(db_session, north) for north in (0.3, 0.6)]
    reactor, commenter = await neighbour(db_session, 0.9), await neighbour(db_session, 1.2)

    for index, voter in enumerate(voters):
        assert (await vote(await authenticate(voter), post, index)).status_code == 200
    reacted = await (await authenticate(reactor)).put(
        f"/v1/posts/{post['id']}/reaction", json={"kind": "helpful"}
    )
    commented = await (await authenticate(commenter)).post(
        f"/v1/posts/{post['id']}/comments", json={"body": "Saturday suits us"}
    )
    await (await authenticate(author)).post(
        f"/v1/posts/{post['id']}/comments", json={"body": "Thanks all"}
    )

    assert reacted.status_code == 200, reacted.text
    assert commented.status_code == 201, commented.text
    assert await views_of(db_session, redis_client, post["id"]) == 4
