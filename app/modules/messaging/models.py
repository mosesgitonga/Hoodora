"""Conversations, members, and messages.

**Ordering is a per-conversation sequence, allocated under a row lock.** A client
reconnecting after a dropped connection asks for "messages since seq N", and for
that to be safe, sequence order must equal commit order. Neither timestamps nor a
global sequence give that: a global value is handed out at insert time, so a
message numbered 42 can commit before 41, and a client that synced in between
would skip 41 forever. Incrementing `conversations.last_seq` to allocate a message's
number takes that row's lock and holds it to commit, so within a conversation, the
next number cannot be handed out until the previous message is durable.

The cost is that sends in one conversation are serialised. That is the right trade
for chat: two people typing in one thread are not a throughput problem, and the
alternative is a sync bug that loses messages silently.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, db_enum


class ConversationKind(StrEnum):
    direct = "direct"
    """Two people, whatever they talk about: there is one per pair. A chat
    started from a listing or a service post is this chat, with that post as its
    topic (decision P.1). Migration 0030 merged the old per-post chats in."""
    group = "group"


class ConversationState(StrEnum):
    active = "active"
    request_pending = "request_pending"
    """A first message from someone with no accepted conversation. The sender may
    send one message; the recipient decides."""
    request_declined = "request_declined"
    """Declined. The sender cannot send again or reopen it — which is what makes
    declining mean something."""


class MemberRole(StrEnum):
    owner = "owner"
    admin = "admin"
    member = "member"


class MemberStatus(StrEnum):
    active = "active"
    invited = "invited"
    """Added to a group chat by someone the user has no accepted conversation with.
    They see the invitation, not the messages, until they accept — otherwise a
    stranger could add anyone to a chat and message them through it, which is the
    message-request rule with a hole in it."""
    left = "left"
    removed = "removed"


class MessageKind(StrEnum):
    text = "text"
    image = "image"
    system = "system"
    """Server-written: "Wanjiku added Kamau", "Kamau left"."""


_kind = db_enum(ConversationKind, name="conversation_kind", length=20)
_state = db_enum(ConversationState, name="conversation_state", length=24)
_role = db_enum(MemberRole, name="member_role", length=16)
_member_status = db_enum(MemberStatus, name="member_status", length=16)
_message_kind = db_enum(MessageKind, name="message_kind", length=16)


def direct_key_for(first: uuid.UUID, second: uuid.UUID) -> str:
    """The canonical key for a pair, order-independent.

    A unique index on this is what guarantees two people only ever have one direct
    conversation — even if both tap "message" at the same moment.
    """
    low, high = sorted((str(first), str(second)))
    return f"{low}:{high}"


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"

    kind: Mapped[ConversationKind] = mapped_column(_kind)
    state: Mapped[ConversationState] = mapped_column(
        _state, default=ConversationState.active, server_default=ConversationState.active.value
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    request_sender_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    """Who started a message request. Kept after acceptance, since "who reached out
    first" is useful context for a moderator looking at a harassment report."""

    request_sender_new_to_area: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    """Whether the person who started the request was new to the area they wrote
    from: not yet allowed to post there. Taken when the request is sent and shown
    to the recipient (decision L.2)."""

    direct_key: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)

    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """The listing this direct chat is about now: the last one someone asked
    about in it (decision P.1). At most one of this and `service_post_id` is set.
    Every post ever asked about is a `ConversationTopic`."""
    service_post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_posts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """The service post this direct chat is about now, as for `listing_id`."""
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    """A group's linked chat. Its membership follows the group's, and cannot be
    managed from the chat."""

    last_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind <> 'direct' OR direct_key IS NOT NULL", name="conversation_direct_has_key"
        ),
        CheckConstraint(
            "kind = 'direct' OR direct_key IS NULL", name="conversation_key_only_for_direct"
        ),
        CheckConstraint(
            "kind <> 'group' OR title IS NOT NULL", name="conversation_group_has_title"
        ),
        CheckConstraint("last_seq >= 0", name="conversation_last_seq_non_negative"),
        # The sync endpoint: conversations changed since a cursor.
        Index("ix_conversations_updated_at", "updated_at"),
    )


class ConversationMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversation_members"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MemberRole] = mapped_column(
        _role, default=MemberRole.member, server_default=MemberRole.member.value
    )
    status: Mapped[MemberStatus] = mapped_column(
        _member_status, default=MemberStatus.active, server_default=MemberStatus.active.value
    )
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    last_read_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    """Read state is a high-water mark, not a row per message. One integer per
    member answers both "how many unread" and "seen up to here", and marking read
    is one UPDATE however many messages arrived."""

    visible_from_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    """Messages at or below this sequence number are not shown to this member.

    Set to the conversation's `last_seq` when someone joins a group chat, so a
    person added later does not read what was said before they arrived — the
    members who said it had no idea they would be an audience.
    """

    muted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    pending_listing_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL"), nullable=True
    )
    """The listing this member opened the chat from, until their next message
    makes it the chat's topic (decision P.1). Only they see it before then, so
    opening a chat from someone's listing tells them nothing."""
    pending_service_post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_posts.id", ondelete="SET NULL"), nullable=True
    )
    """As `pending_listing_id`, for a service post."""

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "user_id", name="uq_conversation_members_conversation_id_user_id"
        ),
        # A user's inbox: their active memberships.
        Index("ix_conversation_members_user_id_status", "user_id", "status"),
        CheckConstraint("last_read_seq >= 0", name="member_last_read_seq_non_negative"),
    )


class ConversationTopic(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A listing or service post someone asked about in a direct chat (decision P.1).

    What used to be a chat of its own per post. Reviews and "who bought it" still
    need to know who asked about what and whether they got an answer, so that is
    kept here, once per post per chat.
    """

    __tablename__ = "conversation_topics"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    service_post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_posts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    asked_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    """Who asked: never the post's owner, who cannot ask about their own post."""
    asked_seq: Mapped[int] = mapped_column(BigInteger)
    """The message that first asked about it."""
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When the owner first replied after it was asked, or accepted the request.
    What a review needs, as "accepted" did for the old per-post chats."""

    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(listing_id, service_post_id) = 1", name="topic_about_one_post"
        ),
        Index(
            "uq_conversation_topics_conversation_id_listing_id",
            "conversation_id",
            "listing_id",
            unique=True,
            postgresql_where=text("listing_id IS NOT NULL"),
        ),
        Index(
            "uq_conversation_topics_conversation_id_service_post_id",
            "conversation_id",
            "service_post_id",
            unique=True,
            postgresql_where=text("service_post_id IS NOT NULL"),
        ),
    )


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """Null only for system messages."""

    seq: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[MessageKind] = mapped_column(_message_kind)
    body: Mapped[str | None] = mapped_column(String(20_000), nullable=True)
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=True
    )
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        # Fetching by sequence, and the guarantee that numbers are not reused.
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_id_seq"),
        CheckConstraint("seq > 0", name="message_seq_positive"),
        # Deleting a message clears its content, so the content rules hold only
        # while it is live. System messages cannot be deleted.
        CheckConstraint(
            "(kind = 'text' AND (body IS NOT NULL OR deleted_at IS NOT NULL))"
            " OR (kind = 'image' AND (media_id IS NOT NULL OR deleted_at IS NOT NULL))"
            " OR (kind = 'system' AND body IS NOT NULL AND sender_id IS NULL)",
            name="message_kind_matches_content",
        ),
    )
