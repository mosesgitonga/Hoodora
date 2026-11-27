"""One chat per person: posts become a chat's topics

Until now, asking about a listing or a service post opened a chat of its own,
one per post per person, beside any direct chat the two already had. So the same
two people could have several chats (decision P.1). From here:

- **`conversation_topics`** keeps each post someone asked about in a direct chat:
  who asked, the message that asked, and when the owner answered. That is what
  reviews and "who bought it" read.
- **`conversation_members.pending_listing_id` / `pending_service_post_id`**: the
  post a member opened the chat from, until their next message.
- **Existing listing and service chats are merged** into the direct chat of the
  same two people (`merge_post_chats`). Messages keep their order in time and
  are numbered again from 1; read markers, notifications and reviews follow. A
  pair with no direct chat has its oldest post chat turned into one.
- **The `listing` and `service` kinds are retired**, with their one-per-post
  indexes.

The downgrade drops the new table and columns and allows the old kinds again,
but cannot split merged chats apart: they stay direct chats.

Revision ID: 0030
Revises: 0029
Created: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS_BEFORE = ("direct", "group", "listing", "service")
KINDS_AFTER = ("direct", "group")

# Above any real sequence number, so renumbering never collides on the way.
_PARK = 1_000_000_000_000
_LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _replace_check(table: str, suffix: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{suffix}"), table, type_="check")
    op.create_check_constraint(suffix, table, condition)


def _pair_key(first: Any, second: Any) -> str:
    low, high = sorted((str(first), str(second)))
    return f"{low}:{high}"


def _read_up_to(connection: sa.Connection, conversation_id: Any, seq: int) -> Any:
    """The last message at or below `seq`, to carry a read marker across."""
    return connection.execute(
        sa.text(
            "SELECT id FROM messages WHERE conversation_id = :c AND seq <= :s "
            "ORDER BY seq DESC LIMIT 1"
        ),
        {"c": conversation_id, "s": seq},
    ).scalar()


def _mark_reads(
    connection: sa.Connection, marks: dict[Any, list[Any]], conversation_id: Any
) -> None:
    for row in connection.execute(
        sa.text(
            "SELECT user_id, last_read_seq FROM conversation_members WHERE conversation_id = :c"
        ),
        {"c": conversation_id},
    ):
        marks.setdefault(row.user_id, []).append(
            _read_up_to(connection, conversation_id, row.last_read_seq)
        )


def _renumber(connection: sa.Connection, conversation_id: Any) -> int:
    """Number a chat's messages 1, 2, 3… in the order they were sent."""
    connection.execute(
        sa.text("UPDATE messages SET seq = seq + :park WHERE conversation_id = :c"),
        {"park": _PARK, "c": conversation_id},
    )
    connection.execute(
        sa.text(
            "WITH ranked AS ("
            "  SELECT id, row_number() OVER (ORDER BY created_at, seq) AS n"
            "  FROM messages WHERE conversation_id = :c"
            ") UPDATE messages m SET seq = ranked.n FROM ranked WHERE m.id = ranked.id"
        ),
        {"c": conversation_id},
    )
    return int(
        connection.execute(
            sa.text("SELECT coalesce(max(seq), 0) FROM messages WHERE conversation_id = :c"),
            {"c": conversation_id},
        ).scalar()
        or 0
    )


def merge_post_chats(connection: sa.Connection) -> int:
    """Fold every listing and service chat into its pair's direct chat.

    Returns how many post chats there were. Runs inside the migration's
    transaction; tests call it directly on rows made the old way.
    """
    chats = (
        connection.execute(
            sa.text(
                "SELECT c.id, c.state, c.listing_id, c.service_post_id, c.created_by_id,"
                "       c.request_sender_id, c.request_sender_new_to_area, c.last_message_at,"
                "       c.created_at,"
                "       array_agg(m.user_id ORDER BY m.user_id) AS members"
                " FROM conversations c JOIN conversation_members m ON m.conversation_id = c.id"
                " WHERE c.kind IN ('listing', 'service')"
                " GROUP BY c.id ORDER BY c.created_at, c.id"
            )
        )
        .mappings()
        .all()
    )
    # Per merged chat: who read up to which message, and what was asked there.
    read_marks: dict[Any, dict[Any, list[Any]]] = {}
    topics: list[dict[str, Any]] = []
    states: dict[Any, list[dict[str, Any]]] = {}

    for chat in chats:
        members = list(chat["members"])
        # A pair's key; for a chat whose other person's row is gone, a key no real
        # pair can have (a conversation's ID is never a user's).
        key = (
            _pair_key(members[0], members[1])
            if len(members) == 2
            else _pair_key(members[0], chat["id"])
        )
        target = (
            connection.execute(
                sa.text(
                    "SELECT id, state, request_sender_id, request_sender_new_to_area,"
                    "       last_message_at, last_seq FROM conversations WHERE direct_key = :k"
                ),
                {"k": key},
            )
            .mappings()
            .first()
        )

        asker = chat["created_by_id"]
        first_ask = (
            connection.execute(
                sa.text(
                    "SELECT id FROM messages WHERE conversation_id = :c AND sender_id = :u"
                    " ORDER BY seq LIMIT 1"
                ),
                {"c": chat["id"], "u": asker},
            ).scalar()
            if asker is not None
            else None
        )

        if target is None:
            # The pair's first chat: it becomes their direct chat, in place.
            connection.execute(
                sa.text("UPDATE conversations SET kind = 'direct', direct_key = :k WHERE id = :c"),
                {"k": key, "c": chat["id"]},
            )
            target_id = chat["id"]
            states[target_id] = [dict(chat)]
            _mark_reads(connection, read_marks.setdefault(target_id, {}), target_id)
        else:
            target_id = target["id"]
            marks = read_marks.setdefault(target_id, {})
            if target_id not in states:
                states[target_id] = [dict(target)]
                _mark_reads(connection, marks, target_id)
            states[target_id].append(dict(chat))
            _mark_reads(connection, marks, chat["id"])
            # Moved above the target's numbers, renumbered once all are in.
            last = int(
                connection.execute(
                    sa.text(
                        "SELECT coalesce(max(seq), 0) FROM messages WHERE conversation_id = :c"
                    ),
                    {"c": target_id},
                ).scalar()
                or 0
            )
            connection.execute(
                sa.text(
                    "UPDATE messages SET conversation_id = :t, seq = seq + :o"
                    " WHERE conversation_id = :c"
                ),
                {"t": target_id, "o": last, "c": chat["id"]},
            )
            connection.execute(
                sa.text(
                    "UPDATE notifications SET target_id = :t"
                    " WHERE target_type = 'conversation' AND target_id = :c"
                ),
                {"t": target_id, "c": chat["id"]},
            )
            connection.execute(
                sa.text(
                    "UPDATE notifications SET data = jsonb_set(data, '{conversation_id}',"
                    " to_jsonb(CAST(:t AS text))) WHERE data->>'conversation_id' = CAST(:c AS text)"
                ),
                {"t": str(target_id), "c": str(chat["id"])},
            )
            connection.execute(
                sa.text("UPDATE reviews SET conversation_id = :t WHERE conversation_id = :c"),
                {"t": target_id, "c": chat["id"]},
            )
            connection.execute(
                sa.text("DELETE FROM conversations WHERE id = :c"), {"c": chat["id"]}
            )

        if first_ask is not None:
            topics.append(
                {
                    "conversation_id": target_id,
                    "listing_id": chat["listing_id"],
                    "service_post_id": chat["service_post_id"],
                    "asked_by_id": asker,
                    "message_id": first_ask,
                    # Accepted, by a reply or by an explicit accept, was what a
                    # review needed; it now means the question was answered.
                    "answered": chat["state"] == "active",
                }
            )

    for target_id, parts in states.items():
        last_seq = _renumber(connection, target_id)
        active = [part for part in parts if part["state"] == "active"]
        declined = [part for part in parts if part["state"] == "request_declined"]
        if active:
            state, sender, new_to_area = "active", parts[0]["request_sender_id"], False
        else:
            chosen = declined[0] if declined else parts[0]
            state = chosen["state"]
            sender = chosen["request_sender_id"]
            new_to_area = bool(chosen["request_sender_new_to_area"])
        # The chat is about the post discussed most recently.
        about = max(
            (part for part in parts if part.get("listing_id") or part.get("service_post_id")),
            key=lambda part: part["last_message_at"] or part["created_at"] or _LONG_AGO,
            default=None,
        )
        connection.execute(
            sa.text(
                "UPDATE conversations SET state = :state, request_sender_id = :sender,"
                " request_sender_new_to_area = :new, last_seq = :seq,"
                " last_message_at = (SELECT max(created_at) FROM messages WHERE conversation_id = :c),"
                " listing_id = :listing, service_post_id = :service, updated_at = now()"
                " WHERE id = :c"
            ),
            {
                "state": state,
                "sender": sender,
                "new": new_to_area if state != "active" else False,
                "seq": last_seq,
                "c": target_id,
                "listing": about["listing_id"] if about else None,
                "service": about["service_post_id"] if about else None,
            },
        )
        for user_id, message_ids in read_marks.get(target_id, {}).items():
            connection.execute(
                sa.text(
                    "UPDATE conversation_members SET last_read_seq = coalesce("
                    " (SELECT max(seq) FROM messages WHERE id = ANY(:ids)), 0)"
                    " WHERE conversation_id = :c AND user_id = :u"
                ),
                {"ids": [i for i in message_ids if i is not None], "c": target_id, "u": user_id},
            )

    for topic in topics:
        connection.execute(
            sa.text(
                "INSERT INTO conversation_topics (id, conversation_id, listing_id,"
                " service_post_id, asked_by_id, asked_seq, answered_at, created_at, updated_at)"
                " SELECT gen_random_uuid(), CAST(:c AS uuid), CAST(:listing AS uuid),"
                " CAST(:service AS uuid), CAST(:asker AS uuid), m.seq,"
                " CASE WHEN CAST(:answered AS boolean) THEN now() END, m.created_at, now()"
                " FROM messages m WHERE m.id = :m"
                " ON CONFLICT DO NOTHING"
            ),
            {
                "c": topic["conversation_id"],
                "listing": topic["listing_id"],
                "service": topic["service_post_id"],
                "asker": topic["asked_by_id"],
                "m": topic["message_id"],
                "answered": topic["answered"],
            },
        )
    return len(chats)


def upgrade() -> None:
    op.create_table(
        "conversation_topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=True),
        sa.Column("service_post_id", sa.Uuid(), nullable=True),
        sa.Column("asked_by_id", sa.Uuid(), nullable=False),
        sa.Column("asked_seq", sa.BigInteger(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "num_nonnulls(listing_id, service_post_id) = 1",
            name=op.f("ck_conversation_topics_topic_about_one_post"),
        ),
        sa.ForeignKeyConstraint(
            ["asked_by_id"],
            ["users.id"],
            name=op.f("fk_conversation_topics_asked_by_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_topics_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_conversation_topics_listing_id_listings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_post_id"],
            ["service_posts.id"],
            name=op.f("fk_conversation_topics_service_post_id_service_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_topics")),
    )
    for column in ("conversation_id", "listing_id", "service_post_id", "asked_by_id"):
        op.create_index(
            op.f(f"ix_conversation_topics_{column}"), "conversation_topics", [column], unique=False
        )
    op.create_index(
        "uq_conversation_topics_conversation_id_listing_id",
        "conversation_topics",
        ["conversation_id", "listing_id"],
        unique=True,
        postgresql_where=sa.text("listing_id IS NOT NULL"),
    )
    op.create_index(
        "uq_conversation_topics_conversation_id_service_post_id",
        "conversation_topics",
        ["conversation_id", "service_post_id"],
        unique=True,
        postgresql_where=sa.text("service_post_id IS NOT NULL"),
    )

    op.add_column("conversation_members", sa.Column("pending_listing_id", sa.Uuid(), nullable=True))
    op.add_column(
        "conversation_members", sa.Column("pending_service_post_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_conversation_members_pending_listing_id_listings"),
        "conversation_members",
        "listings",
        ["pending_listing_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_conversation_members_pending_service_post_id_service_posts"),
        "conversation_members",
        "service_posts",
        ["pending_service_post_id"],
        ["id"],
        ondelete="SET NULL",
    )

    merge_post_chats(op.get_bind())

    op.drop_index(
        "uq_conversations_listing_id_created_by_id",
        table_name="conversations",
        postgresql_where=sa.text("kind = 'listing'"),
    )
    op.drop_index(
        "uq_conversations_service_post_id_created_by_id",
        table_name="conversations",
        postgresql_where=sa.text("kind = 'service'"),
    )
    _replace_check("conversations", "conversation_kind", _in("kind", KINDS_AFTER))


def downgrade() -> None:
    _replace_check("conversations", "conversation_kind", _in("kind", KINDS_BEFORE))
    op.create_index(
        "uq_conversations_service_post_id_created_by_id",
        "conversations",
        ["service_post_id", "created_by_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'service'"),
    )
    op.create_index(
        "uq_conversations_listing_id_created_by_id",
        "conversations",
        ["listing_id", "created_by_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'listing'"),
    )
    op.drop_constraint(
        op.f("fk_conversation_members_pending_service_post_id_service_posts"),
        "conversation_members",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_conversation_members_pending_listing_id_listings"),
        "conversation_members",
        type_="foreignkey",
    )
    op.drop_column("conversation_members", "pending_service_post_id")
    op.drop_column("conversation_members", "pending_listing_id")
    op.drop_index(
        "uq_conversation_topics_conversation_id_service_post_id",
        table_name="conversation_topics",
        postgresql_where=sa.text("service_post_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_conversation_topics_conversation_id_listing_id",
        table_name="conversation_topics",
        postgresql_where=sa.text("listing_id IS NOT NULL"),
    )
    for column in ("asked_by_id", "service_post_id", "listing_id", "conversation_id"):
        op.drop_index(op.f(f"ix_conversation_topics_{column}"), table_name="conversation_topics")
    op.drop_table("conversation_topics")
