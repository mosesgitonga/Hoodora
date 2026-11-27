"""Polls on posts, and how many people saw a post (decision F.1).

**Votes are anonymous by construction.** A vote adds one to its answer's count and
records only *that* the person voted, in `post_poll_votes`, so they can't vote
twice. Which answer they chose is never stored, so nobody can say how anyone
voted, Hoodora included. It follows that a vote can't be changed.

**Views are counted without a list of viewers.** Each post has a Redis
HyperLogLog of the people who saw it. It answers "how many distinct people", to
within about 1%, and can't be asked "who". A worker copies the count onto
`posts.view_count` every minute. The author's own views don't count, and nor do
views of someone blocked either way.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.modules.feed.models import Post, PostPoll, PostPollOption, PostPollVote
from app.modules.moderation.models import ContentStatus
from app.modules.users.models import User
from app.modules.users.service import blocked_user_ids

logger = logging.getLogger(__name__)

POLL_MIN_OPTIONS: Final = 2
POLL_MAX_OPTIONS: Final = 4
POLL_OPTION_MAX_LENGTH: Final = 80
POLL_DURATIONS_HOURS: Final = (24, 72, 168)
"""A day, three days, or a week."""

VIEWS_KEY_PREFIX: Final = "post-views"
VIEWS_DIRTY_KEY: Final = "post-views:dirty"
VIEWS_KEY_TTL_SECONDS: Final = 90 * 86_400
"""A post nobody has seen for 90 days keeps its count on the row; its key goes."""
MAX_VIEWS_PER_REPORT: Final = 50


# ---------------------------------------------------------------------------
# Making a poll
# ---------------------------------------------------------------------------
def clean_poll(options: Sequence[str], duration_hours: int) -> list[str]:
    """The answers as they will be stored, or `BadRequestError`."""
    cleaned = [" ".join(option.split()) for option in options]
    if not POLL_MIN_OPTIONS <= len(cleaned) <= POLL_MAX_OPTIONS:
        raise BadRequestError(
            f"A poll has {POLL_MIN_OPTIONS} to {POLL_MAX_OPTIONS} answers",
            details={"field": "poll.options"},
        )
    if any(not option for option in cleaned):
        raise BadRequestError("An answer can't be empty", details={"field": "poll.options"})
    if any(len(option) > POLL_OPTION_MAX_LENGTH for option in cleaned):
        raise BadRequestError(
            f"Answers are limited to {POLL_OPTION_MAX_LENGTH} characters",
            details={"field": "poll.options", "max_length": POLL_OPTION_MAX_LENGTH},
        )
    if len({option.casefold() for option in cleaned}) != len(cleaned):
        raise BadRequestError("Each answer must be different", details={"field": "poll.options"})
    if duration_hours not in POLL_DURATIONS_HOURS:
        raise BadRequestError(
            "A poll runs for a day, three days or a week",
            details={"field": "poll.duration_hours", "allowed": list(POLL_DURATIONS_HOURS)},
        )
    return cleaned


def new_poll(options: Sequence[str], duration_hours: int, *, now: datetime) -> PostPoll:
    return PostPoll(
        closes_at=now + timedelta(hours=duration_hours),
        options=[
            PostPollOption(position=position, text=text) for position, text in enumerate(options)
        ],
    )


def is_closed(poll: PostPoll, now: datetime | None = None) -> bool:
    return (now or datetime.now(UTC)) >= poll.closes_at


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------
async def vote(session: AsyncSession, *, voter: User, post: Post, option_id: uuid.UUID) -> PostPoll:
    """One vote, final, for one answer. The caller has checked the voter may see
    the post and engage with it."""
    poll = post.poll
    if poll is None:
        raise NotFoundError("This post has no poll")
    if is_closed(poll):
        raise ConflictError("This poll has closed", details={"reason": "poll_closed"})
    if option_id not in {option.id for option in poll.options}:
        raise NotFoundError("That answer isn't in this poll")

    recorded = await session.scalar(
        pg_insert(PostPollVote)
        .values(post_id=post.id, user_id=voter.id)
        .on_conflict_do_nothing()
        .returning(PostPollVote.post_id)
    )
    if recorded is None:
        raise ConflictError(
            "You've already voted in this poll", details={"reason": "already_voted"}
        )
    await session.execute(
        update(PostPollOption)
        .where(PostPollOption.id == option_id)
        .values(vote_count=PostPollOption.vote_count + 1)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(PostPoll)
        .where(PostPoll.post_id == post.id)
        .values(vote_count=PostPoll.vote_count + 1)
        .execution_options(synchronize_session=False)
    )
    await session.refresh(poll, ["vote_count"])
    for option in poll.options:
        await session.refresh(option, ["vote_count"])
    logger.info("poll_voted", extra={"post_id": str(post.id)})
    return poll


async def voted_in(
    session: AsyncSession, *, user_id: uuid.UUID, post_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    ids = list(post_ids)
    if not ids:
        return set()
    return set(
        (
            await session.execute(
                select(PostPollVote.post_id).where(
                    PostPollVote.user_id == user_id, PostPollVote.post_id.in_(ids)
                )
            )
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def views_key(post_id: uuid.UUID | str) -> str:
    return f"{VIEWS_KEY_PREFIX}:{post_id}"


async def _run(command: Any) -> Any:
    """Await a redis-py command whose stubs say `Awaitable[T] | T`."""
    return await cast("Awaitable[Any]", command)


async def record_views(
    session: AsyncSession, redis: Redis, *, viewer: User, post_ids: Sequence[uuid.UUID]
) -> int:
    """Count `viewer` once in each post's views. Returns how many were counted.

    Only live, visible posts count, never the viewer's own, and never one by
    someone blocked either way. Seeing a post twice counts once.
    """
    ids = list(dict.fromkeys(post_ids))[:MAX_VIEWS_PER_REPORT]
    if not ids:
        return 0
    rows = (
        await session.execute(
            select(Post.id, Post.author_id).where(
                Post.id.in_(ids),
                Post.deleted_at.is_(None),
                Post.status == ContentStatus.visible,
            )
        )
    ).all()
    hidden = await blocked_user_ids(session, viewer.id)
    counted = [
        post_id for post_id, author_id in rows if author_id != viewer.id and author_id not in hidden
    ]
    if not counted:
        return 0
    pipe = redis.pipeline(transaction=False)
    for post_id in counted:
        pipe.pfadd(views_key(post_id), str(viewer.id))
        pipe.expire(views_key(post_id), VIEWS_KEY_TTL_SECONDS)
    pipe.sadd(VIEWS_DIRTY_KEY, *(str(post_id) for post_id in counted))
    await pipe.execute()
    return len(counted)


async def count_as_seen(
    session: AsyncSession, redis: Redis, *, viewer: User, post_id: uuid.UUID
) -> None:
    """Acting on a post means having seen it: a vote, reaction or comment counts as
    a view, so a post never shows more people acting on it than seeing it,
    whatever the app reported. Best effort: a Redis hiccup never fails the act.
    """
    try:
        await record_views(session, redis, viewer=viewer, post_ids=[post_id])
    except RedisError:
        logger.warning("post_view_not_counted", extra={"post_id": str(post_id)})


async def flush_view_counts(session: AsyncSession, redis: Redis, *, batch: int = 500) -> int:
    """Copy the counts of posts seen since the last run onto their rows.

    `greatest`, so a count never goes down: if Redis ever lost a post's key, its
    count would start again from nothing, and the row keeps what it had.
    """
    popped = await _run(redis.spop(VIEWS_DIRTY_KEY, batch))
    ids = [str(item) for item in (popped or [])]
    for raw in ids:
        try:
            post_id = uuid.UUID(raw)
        except ValueError:
            continue
        count = int(await _run(redis.pfcount(views_key(post_id))) or 0)
        await session.execute(
            update(Post)
            .where(Post.id == post_id)
            .values(view_count=func.greatest(Post.view_count, count))
            .execution_options(synchronize_session=False)
        )
    return len(ids)
