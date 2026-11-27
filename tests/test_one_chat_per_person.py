"""One chat per person: a listing or service post is a chat's topic (decision P.1).

Messaging someone from their listing, their service post, or from Chats opens
the same chat. What used to need a chat per post (reviews, "who bought it", the
job safety notice) now reads the chat's topics.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.messaging.models import ConversationTopic
from app.modules.notifications.models import Notification
from app.modules.users.models import User
from tests.factories import NYERI_TOWN, make_user

Authenticate = Callable[[User], Awaitable[httpx.AsyncClient]]


async def person(db_session: AsyncSession, **kwargs: Any) -> User:
    return await make_user(db_session, at=NYERI_TOWN, created_days_ago=30, **kwargs)


async def list_item(client: httpx.AsyncClient, title: str = "Three-seater sofa") -> dict[str, Any]:
    response = await client.post(
        "/v1/listings",
        json={
            "title": title,
            "description": "Good condition, collect from Kamakwa",
            "category": "furniture",
            "condition": "good",
            "pricing": "negotiable",
            "price_kes": 8500,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def offer(client: httpx.AsyncClient, **fields: Any) -> dict[str, Any]:
    body = {"kind": "offering", "category": "plumbing", "title": "Plumber, 10 years", **fields}
    response = await client.post("/v1/services", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def say(client: httpx.AsyncClient, chat_id: str, body: str, expect: int = 201) -> None:
    response = await client.post(f"/v1/conversations/{chat_id}/messages", json={"body": body})
    assert response.status_code == expect, response.text


async def chat_of(client: httpx.AsyncClient, chat_id: str) -> dict[str, Any]:
    response = await client.get(f"/v1/conversations/{chat_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def folder(client: httpx.AsyncClient, name: str) -> list[str]:
    response = await client.get(f"/v1/conversations?folder={name}")
    return [item["id"] for item in response.json()["items"]]


# ---------------------------------------------------------------------------
# The reported problem
# ---------------------------------------------------------------------------
async def test_messaging_from_a_listing_and_from_chats_is_one_chat(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    seller, buyer = await person(db_session), await person(db_session)
    listing = await list_item(await authenticate(seller))

    from_listing = (
        await (await authenticate(buyer)).post(f"/v1/listings/{listing['id']}/chat")
    ).json()
    await say(await authenticate(buyer), from_listing["id"], "Is it still available?")
    await say(await authenticate(seller), from_listing["id"], "Yes")
    from_chats = (
        await (await authenticate(buyer)).post(
            "/v1/conversations/direct", json={"user_id": str(seller.id)}
        )
    ).json()

    assert from_chats["id"] == from_listing["id"]
    assert from_listing["kind"] == "direct"
    assert await folder(await authenticate(buyer), "chats") == [from_listing["id"]]
    assert await folder(await authenticate(seller), "chats") == [from_listing["id"]]


async def test_an_existing_chat_is_reused_when_asking_about_a_listing(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    seller, buyer = await person(db_session), await person(db_session)
    direct = (
        await (await authenticate(buyer)).post(
            "/v1/conversations/direct", json={"user_id": str(seller.id)}
        )
    ).json()
    await say(await authenticate(buyer), direct["id"], "Habari")
    await say(await authenticate(seller), direct["id"], "Poa")
    listing = await list_item(await authenticate(seller))
    job = await offer(await authenticate(seller))

    about_listing = (
        await (await authenticate(buyer)).post(f"/v1/listings/{listing['id']}/chat")
    ).json()
    about_service = (
        await (await authenticate(buyer)).post(f"/v1/services/{job['id']}/chat")
    ).json()

    assert about_listing["id"] == about_service["id"] == direct["id"]


async def test_two_listings_from_one_seller_share_the_chat_and_the_topic_follows(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    seller, buyer = await person(db_session), await person(db_session)
    sofa = await list_item(await authenticate(seller), "Sofa")
    table = await list_item(await authenticate(seller), "Table")

    chat = (await (await authenticate(buyer)).post(f"/v1/listings/{sofa['id']}/chat")).json()
    await say(await authenticate(buyer), chat["id"], "Is the sofa available?")
    await say(await authenticate(seller), chat["id"], "Yes")
    again = (await (await authenticate(buyer)).post(f"/v1/listings/{table['id']}/chat")).json()
    await say(await authenticate(buyer), chat["id"], "And the table?")

    assert again["id"] == chat["id"]
    assert (await chat_of(await authenticate(seller), chat["id"]))["listing_id"] == table["id"]
    for listing in (sofa, table):
        card = (await (await authenticate(buyer)).get(f"/v1/listings/{listing['id']}")).json()
        assert card["my_conversation_id"] == chat["id"]
        buyers = (
            await (await authenticate(seller)).get(f"/v1/listings/{listing['id']}/buyers")
        ).json()
        assert [item["user"]["id"] for item in buyers] == [str(buyer.id)]


# ---------------------------------------------------------------------------
# What the other person sees, and where it lands
# ---------------------------------------------------------------------------
async def test_opening_from_a_post_tells_the_owner_nothing_until_a_message(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    seller, buyer = await person(db_session), await person(db_session)
    direct = (
        await (await authenticate(buyer)).post(
            "/v1/conversations/direct", json={"user_id": str(seller.id)}
        )
    ).json()
    await say(await authenticate(buyer), direct["id"], "Habari")
    await say(await authenticate(seller), direct["id"], "Poa")
    listing = await list_item(await authenticate(seller))

    opened = (await (await authenticate(buyer)).post(f"/v1/listings/{listing['id']}/chat")).json()

    # The buyer sees the listing at once; the seller does not.
    assert opened["listing_id"] == listing["id"]
    assert (await chat_of(await authenticate(seller), direct["id"]))["listing_id"] is None

    await say(await authenticate(buyer), direct["id"], "Is the sofa still there?")

    assert (await chat_of(await authenticate(seller), direct["id"]))["listing_id"] == listing["id"]


async def test_a_request_about_a_listing_lands_in_the_inbox(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    seller, buyer, stranger = [await person(db_session) for _ in range(3)]
    listing = await list_item(await authenticate(seller))

    chat = (await (await authenticate(buyer)).post(f"/v1/listings/{listing['id']}/chat")).json()
    await say(await authenticate(buyer), chat["id"], "Still there?")
    await say(await authenticate(buyer), chat["id"], "Hello?", expect=409)
    plain = (
        await (await authenticate(stranger)).post(
            "/v1/conversations/direct", json={"user_id": str(seller.id)}
        )
    ).json()
    await say(await authenticate(stranger), plain["id"], "Hi")

    seller_client = await authenticate(seller)
    assert await folder(seller_client, "chats") == [chat["id"]]
    assert await folder(seller_client, "requests") == [plain["id"]]
    note = (
        await db_session.execute(
            select(Notification).where(
                Notification.user_id == seller.id, Notification.actor_id == buyer.id
            )
        )
    ).scalar_one()
    assert note.type == "listing_inquiry"
    assert note.data["listing_id"] == listing["id"]


async def test_a_job_chat_keeps_its_safety_notice_after_the_topic_moves_on(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    employer, seeker = await person(db_session), await person(db_session)
    job = await offer(
        await authenticate(employer), kind="hiring", category="catering", title="Cook"
    )
    catering = await offer(await authenticate(employer), category="catering", title="Catering")

    chat = (await (await authenticate(seeker)).post(f"/v1/services/{job['id']}/chat")).json()
    await say(await authenticate(seeker), chat["id"], "Interested")
    await say(await authenticate(employer), chat["id"], "Come on Monday")
    (await (await authenticate(seeker)).post(f"/v1/services/{catering['id']}/chat")).json()
    await say(await authenticate(seeker), chat["id"], "Do you also cater weddings?")

    seen = await chat_of(await authenticate(employer), chat["id"])
    assert seen["service_post_id"] == catering["id"]
    assert "Never pay to get a job" in seen["safety_notice"]


# ---------------------------------------------------------------------------
# Reviews still need a question about that exact post, answered
# ---------------------------------------------------------------------------
async def test_reviews_need_an_answered_question_about_that_post(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    seller, buyer = await person(db_session), await person(db_session)
    sofa = await list_item(await authenticate(seller), "Sofa")
    table = await list_item(await authenticate(seller), "Table")

    async def review(listing: dict[str, Any]) -> int:
        response = await (await authenticate(buyer)).post(
            "/v1/reviews",
            json={
                "subject_id": str(seller.id),
                "context_type": "listing",
                "context_id": listing["id"],
                "rating": 5,
            },
        )
        return response.status_code

    chat = (await (await authenticate(buyer)).post(f"/v1/listings/{sofa['id']}/chat")).json()
    await say(await authenticate(buyer), chat["id"], "Sofa?")
    assert await review(sofa) == 403  # not answered yet
    await say(await authenticate(seller), chat["id"], "Yes")
    assert await review(sofa) == 201
    # The chat is accepted, but nobody asked about the table in it.
    assert await review(table) == 403
    (await (await authenticate(buyer)).post(f"/v1/listings/{table['id']}/chat")).json()
    await say(await authenticate(buyer), chat["id"], "And the table?")
    assert await review(table) == 403  # asked, not answered
    await say(await authenticate(seller), chat["id"], "Sold, sorry")
    assert await review(table) == 201


async def test_accepting_a_request_answers_what_it_asked(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    provider, customer = await person(db_session), await person(db_session)
    plumbing = await offer(await authenticate(provider))
    chat = (await (await authenticate(customer)).post(f"/v1/services/{plumbing['id']}/chat")).json()
    await say(await authenticate(customer), chat["id"], "Free on Saturday?")

    accepted = await (await authenticate(provider)).post(
        f"/v1/conversations/{chat['id']}/request", json={"action": "accept"}
    )

    assert accepted.status_code == 200, accepted.text
    topic = (
        await db_session.execute(
            select(ConversationTopic).where(
                ConversationTopic.conversation_id == uuid.UUID(chat["id"])
            )
        )
    ).scalar_one()
    assert topic.asked_by_id == customer.id and topic.answered_at is not None


# ---------------------------------------------------------------------------
# Migration 0030: chats made the old way are merged
# ---------------------------------------------------------------------------
def _migration() -> Any:
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0030_one_chat_per_person.py"
    spec = importlib.util.spec_from_file_location("migration_0030", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _old_chat(
    db_session: AsyncSession,
    *,
    kind: str,
    state: str,
    asker: User,
    owner: User,
    messages: list[tuple[User, str, datetime]],
    reads: dict[uuid.UUID, int] | None = None,
    listing_id: str | None = None,
    service_post_id: str | None = None,
) -> uuid.UUID:
    """A conversation as the code before decision P.1 stored one."""
    chat_id = uuid.uuid4()
    low, high = sorted((str(asker.id), str(owner.id)))
    await db_session.execute(
        text(
            "INSERT INTO conversations (id, kind, state, created_by_id, request_sender_id,"
            " direct_key, listing_id, service_post_id, last_seq, last_message_at, created_at)"
            " VALUES (:id, :kind, :state, :asker, :asker, :key, :listing, :service, :seq,"
            " :last, :created)"
        ),
        {
            "id": chat_id,
            "kind": kind,
            "state": state,
            "asker": asker.id,
            "key": f"{low}:{high}" if kind == "direct" else None,
            "listing": uuid.UUID(listing_id) if listing_id else None,
            "service": uuid.UUID(service_post_id) if service_post_id else None,
            "seq": len(messages),
            "last": messages[-1][2],
            "created": messages[0][2],
        },
    )
    for user in (asker, owner):
        await db_session.execute(
            text(
                "INSERT INTO conversation_members (id, conversation_id, user_id, last_read_seq)"
                " VALUES (:id, :c, :u, :r)"
            ),
            {"id": uuid.uuid4(), "c": chat_id, "u": user.id, "r": (reads or {}).get(user.id, 0)},
        )
    for seq, (sender, body, at) in enumerate(messages, start=1):
        await db_session.execute(
            text(
                "INSERT INTO messages (id, conversation_id, sender_id, seq, kind, body, created_at)"
                " VALUES (:id, :c, :s, :seq, 'text', :b, :at)"
            ),
            {"id": uuid.uuid4(), "c": chat_id, "s": sender.id, "seq": seq, "b": body, "at": at},
        )
    return chat_id


async def test_the_migration_merges_post_chats_into_the_pairs_chat(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    seller, buyer, other = [await person(db_session) for _ in range(3)]
    seller_id, buyer_id, other_id = seller.id, buyer.id, other.id
    listing = await list_item(await authenticate(seller))
    plumbing = await offer(await authenticate(seller))
    lonely = await list_item(await authenticate(other), "Bike")
    # Old kinds, allowed again for this test's transaction only.
    await db_session.execute(
        text("ALTER TABLE conversations DROP CONSTRAINT ck_conversations_conversation_kind")
    )
    t0 = datetime(2026, 11, 1, 9, tzinfo=UTC)

    direct = await _old_chat(
        db_session,
        kind="direct",
        state="active",
        asker=buyer,
        owner=seller,
        messages=[(buyer, "Habari", t0), (seller, "Poa", t0 + timedelta(hours=3))],
        reads={buyer.id: 2, seller.id: 2},
    )
    await _old_chat(
        db_session,
        kind="listing",
        state="active",
        asker=buyer,
        owner=seller,
        listing_id=listing["id"],
        messages=[
            (buyer, "Sofa?", t0 + timedelta(hours=1)),
            (seller, "Yes", t0 + timedelta(hours=2)),
        ],
        reads={buyer.id: 2, seller.id: 2},
    )
    about_service = await _old_chat(
        db_session,
        kind="service",
        state="request_pending",
        asker=buyer,
        owner=seller,
        service_post_id=plumbing["id"],
        messages=[(buyer, "Free Saturday?", t0 + timedelta(hours=4))],
        reads={buyer.id: 1},
    )
    only_listing = await _old_chat(
        db_session,
        kind="listing",
        state="request_pending",
        asker=buyer,
        owner=other,
        listing_id=lonely["id"],
        messages=[(buyer, "Bike?", t0)],
        reads={buyer.id: 1},
    )
    db_session.add(
        Notification(
            user_id=seller.id,
            type="service_inquiry",
            actor_id=buyer.id,
            target_type="conversation",
            target_id=about_service,
            collapse_key=f"message_request:{about_service}",
            data={"conversation_id": str(about_service), "service_post_id": plumbing["id"]},
        )
    )
    await db_session.flush()

    merged = await db_session.run_sync(lambda s: _migration().merge_post_chats(s.connection()))
    db_session.expire_all()

    assert merged == 3
    kinds = dict((await db_session.execute(text("SELECT id, kind FROM conversations"))).all())
    assert kinds == {direct: "direct", only_listing: "direct"}
    # One chat with the seller, in the order things were said, numbered again.
    said = (
        await db_session.execute(
            text("SELECT seq, body FROM messages WHERE conversation_id = :c ORDER BY seq"),
            {"c": direct},
        )
    ).all()
    assert [tuple(row) for row in said] == [
        (1, "Habari"),
        (2, "Sofa?"),
        (3, "Yes"),
        (4, "Poa"),
        (5, "Free Saturday?"),
    ]
    chat = (
        await db_session.execute(
            text(
                "SELECT state, last_seq, listing_id, service_post_id FROM conversations"
                " WHERE id = :c"
            ),
            {"c": direct},
        )
    ).one()
    assert (chat.state, chat.last_seq, chat.listing_id) == ("active", 5, None)
    assert str(chat.service_post_id) == plumbing["id"]
    reads = dict(
        (
            await db_session.execute(
                text(
                    "SELECT user_id, last_read_seq FROM conversation_members"
                    " WHERE conversation_id = :c"
                ),
                {"c": direct},
            )
        ).all()
    )
    assert reads == {buyer_id: 5, seller_id: 4}
    topics = {
        (str(t.listing_id or t.service_post_id), t.asked_seq, t.answered_at is not None)
        for t in (
            await db_session.execute(
                select(ConversationTopic).where(ConversationTopic.conversation_id == direct)
            )
        ).scalars()
    }
    assert topics == {(listing["id"], 2, True), (plumbing["id"], 5, False)}
    note = (
        await db_session.execute(select(Notification).where(Notification.user_id == seller_id))
    ).scalar_one()
    assert note.target_id == direct and note.data["conversation_id"] == str(direct)
    # A pair with only a post chat keeps it, now as their direct chat.
    lone = (
        await db_session.execute(
            text("SELECT state, direct_key, listing_id FROM conversations WHERE id = :c"),
            {"c": only_listing},
        )
    ).one()
    assert lone.state == "request_pending" and str(lone.listing_id) == lonely["id"]
    assert lone.direct_key == ":".join(sorted((str(buyer_id), str(other_id))))


async def test_a_purged_account_leaves_no_record_of_what_it_asked_about(
    db_session: AsyncSession, authenticate: Authenticate
) -> None:
    from app.modules.messaging import service as messaging_service

    seller, buyer = await person(db_session), await person(db_session)
    buyer_id = buyer.id
    listing = await list_item(await authenticate(seller))
    chat = (await (await authenticate(buyer)).post(f"/v1/listings/{listing['id']}/chat")).json()
    await say(await authenticate(buyer), chat["id"], "Still there?")

    await messaging_service.purge_user_messages(db_session, None, user_id=buyer_id)

    left = await db_session.scalar(
        select(ConversationTopic.id).where(ConversationTopic.asked_by_id == buyer_id)
    )
    assert left is None
