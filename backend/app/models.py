from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    """SQLite drops tzinfo on read; every stored datetime is UTC, so restore it before serializing."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


class Account(Base):
    """A Telegram user account the panel acts as (MTProto session)."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    phone: Mapped[str] = mapped_column(String(32))
    api_id: Mapped[int] = mapped_column(Integer)
    api_hash_enc: Mapped[str] = mapped_column(Text)
    session_enc: Mapped[str] = mapped_column(Text)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger)
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64))
    photo_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | error
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tool: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|done|failed|cancelled
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    # Marked peer id of the chat the job collected from; groups jobs of the same channel.
    source_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TgPeer(Base):
    """Cache of Telegram users/channels seen by any tool. `id` is Telethon's marked peer id
    (users: positive, channels: -100…), so users and channels never collide."""

    __tablename__ = "tg_peers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))  # user | channel | chat
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    usernames: Mapped[list[str]] = mapped_column(JSON, default=list)
    photo_id: Mapped[int | None] = mapped_column(BigInteger)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_scam: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    # users, filled by the channel finder from the full profile
    about: Mapped[str | None] = mapped_column(Text)
    personal_channel_id: Mapped[int | None] = mapped_column(BigInteger)  # marked id of the channel shown in the profile
    profile_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PeerAccess(Base):
    """access_hash of a peer as seen by one account: lets later requests address the peer
    directly (the Telethon session cache is in memory only)."""

    __tablename__ = "peer_access"

    account_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    peer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    access_hash: Mapped[int] = mapped_column(BigInteger)


class FoundChannel(Base):
    """Channel or chat discovered through the people in the base: the channel in their profile,
    links and @mentions in their bio, or a channel they comment as."""

    __tablename__ = "found_channels"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)  # marked peer id, or "+<invite hash>"
    peer_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    type: Mapped[str | None] = mapped_column(String(16))  # source types; None while unknown
    title: Mapped[str | None] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(64))
    invite_hash: Mapped[str | None] = mapped_column(String(64))
    members_count: Mapped[int | None] = mapped_column(Integer)
    about: Mapped[str | None] = mapped_column(Text)
    photo_id: Mapped[int | None] = mapped_column(BigInteger)
    private: Mapped[bool] = mapped_column(Boolean, default=False)  # invite only: the account must join first
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FoundChannelLink(Base):
    """Who points to a found channel and how (personal | bio | sender)."""

    __tablename__ = "found_channel_links"

    key: Mapped[str] = mapped_column(ForeignKey("found_channels.key", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    via: Mapped[str] = mapped_column(String(16), primary_key=True)


class UsernameLookup(Base):
    """What a @username from a bio turned out to be, so it is resolved once (ResolveUsername is
    one of the most rate-limited calls)."""

    __tablename__ = "username_lookups"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)  # lower case
    kind: Mapped[str] = mapped_column(String(16))  # channel | chat | user | none
    peer_id: Mapped[int | None] = mapped_column(BigInteger)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Comment(Base):
    __tablename__ = "comments"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    msg_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # id inside the discussion group
    post_id: Mapped[int] = mapped_column(Integer)  # id of the channel post
    sender_id: Mapped[int] = mapped_column(BigInteger)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[str | None] = mapped_column(Text)
    # Group msg id this comment answers, when it answers another comment (not the post itself).
    reply_to: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        Index("ix_comments_job_sender", "job_id", "sender_id"),
        Index("ix_comments_job_post", "job_id", "post_id"),
    )


class JobParticipant(Base):
    __tablename__ = "job_participants"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    peer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    posts: Mapped[int] = mapped_column(Integer, default=0)
    first_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # chats: in the member list (people who never wrote have comments = 0)
    member: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    role: Mapped[str | None] = mapped_column(String(16))  # creator | admin | member

    __table_args__ = (Index("ix_participants_job_comments", "job_id", "comments"),)


class SourceMember(Base):
    """Member list of a group as last seen by the chat indexer (merged into its participants)."""

    __tablename__ = "source_members"

    source_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    peer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str] = mapped_column(String(16), default="member")
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PeerNote(Base):
    """User-assigned tags / notes / star on any peer, shared across all tools."""

    __tablename__ = "peer_notes"

    peer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    # people: left out of lists, graphs and notifications; channels: hidden from analytics
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ThreadRoot(Base):
    """Discussion-group message that starts the comment thread of a channel post.
    Remembered so incremental runs can attribute new comments on old posts."""

    __tablename__ = "thread_roots"

    source_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    root_msg_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(Integer)


class Monitor(Base):
    """Periodic incremental re-collection of one source (channel comments or a chat)."""

    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    channel: Mapped[str] = mapped_column(String(256))
    tool: Mapped[str] = mapped_column(String(64), default="comment-collector", server_default="comment-collector")
    # extra tool input for each run, e.g. {"collect_members": false}
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    title: Mapped[str | None] = mapped_column(String(255))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_job_id: Mapped[int | None] = mapped_column(Integer)
    last_status: Mapped[str | None] = mapped_column(String(16))  # running | done | failed | cancelled
    last_error: Mapped[str | None] = mapped_column(Text)
    last_new_users: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Event(Base):
    """Notification shown in the panel (and optionally delivered to Telegram)."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # new_users | watch | job_failed | info
    title: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    job_id: Mapped[int | None] = mapped_column(Integer)
    monitor_id: Mapped[int | None] = mapped_column(Integer)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    delivery: Mapped[str | None] = mapped_column(String(16))  # sent | error | None (panel only)
    delivery_error: Mapped[str | None] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
