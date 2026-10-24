"""Pure counting logic for the comment collector — no network, so it is unit-testable.

How comments live in Telegram: a channel's posts are auto-forwarded into its linked discussion
supergroup. The forwarded copy is the thread root (fwd_from.channel_post = post id). A comment is a
group message whose reply header points at that root (reply_to_top_id for replies-to-replies,
reply_to_msg_id for direct comments). Everything else in the group is ordinary chat.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from telethon import utils
from telethon.tl import types

TEXT_LIMIT = 500


@dataclass
class CommentRec:
    msg_id: int
    post_id: int
    sender_id: int
    date: datetime
    text: str | None
    reply_to: int | None = None  # comment this one answers (None = answers the post)
    fwd_from: int | None = None  # channel/chat the message was forwarded from


@dataclass
class ParticipantStats:
    comments: int = 0
    posts: set[int] = field(default_factory=set)
    first_at: datetime | None = None
    last_at: datetime | None = None

    def add(self, post_id: int, date: datetime) -> None:
        self.comments += 1
        self.posts.add(post_id)
        if self.first_at is None or date < self.first_at:
            self.first_at = date
        if self.last_at is None or date > self.last_at:
            self.last_at = date


def thread_root_post(msg: Any, channel_id: int) -> int | None:
    """If `msg` (in the discussion group) is the auto-forwarded copy of a post of `channel_id`,
    return the post id."""
    fwd = getattr(msg, "fwd_from", None)
    if not fwd:
        return None
    saved_peer = getattr(fwd, "saved_from_peer", None)
    if isinstance(saved_peer, types.PeerChannel) and saved_peer.channel_id == channel_id and fwd.saved_from_msg_id:
        return fwd.saved_from_msg_id
    from_id = getattr(fwd, "from_id", None)
    if isinstance(from_id, types.PeerChannel) and from_id.channel_id == channel_id and fwd.channel_post:
        return fwd.channel_post
    return None


def reply_top_id(msg: Any) -> int | None:
    rt = getattr(msg, "reply_to", None)
    if not isinstance(rt, types.MessageReplyHeader):
        return None
    return rt.reply_to_top_id or rt.reply_to_msg_id


def reply_target(msg: Any) -> int | None:
    """Id of the comment `msg` answers; None when it answers the post (thread root) itself."""
    rt = getattr(msg, "reply_to", None)
    if isinstance(rt, types.MessageReplyHeader) and rt.reply_to_top_id and rt.reply_to_msg_id != rt.reply_to_top_id:
        return rt.reply_to_msg_id
    return None


def sender_peer_id(msg: Any) -> int:
    """Marked peer id of whoever wrote the message. Anonymous admins have no from_id and
    appear as the group itself."""
    peer = getattr(msg, "from_id", None) or msg.peer_id
    return utils.get_peer_id(peer)


def forwarded_from(msg: Any) -> int | None:
    """Marked id of the channel or chat a message was forwarded from (None for users and hidden senders)."""
    fwd = getattr(msg, "fwd_from", None)
    peer = getattr(fwd, "from_id", None) if fwd else None
    return utils.get_peer_id(peer) if isinstance(peer, (types.PeerChannel, types.PeerChat)) else None


def _text(msg: Any) -> str | None:
    text = getattr(msg, "message", None)
    return text[:TEXT_LIMIT] if text else None


class CommentAggregator:
    def __init__(self, channel_id: int) -> None:
        self.channel_id = channel_id
        self.roots: dict[int, int] = {}  # root msg id in group -> channel post id
        self._pending: dict[int, list[Any]] = {}  # replies seen before their root
        self.participants: dict[int, ParticipantStats] = {}
        self.posts_with_comments: set[int] = set()
        self.total = 0
        self._new: list[CommentRec] = []
        self._seen: set[int] = set()
        self.fwd_sources: set[int] = set()  # channels comments were forwarded from (their entities are kept)

    # --- group-history strategy: feed every message of the discussion group ---

    def feed_group_message(self, msg: Any) -> None:
        if not isinstance(msg, types.Message):
            return  # service messages (joins, pins, …)
        post_id = thread_root_post(msg, self.channel_id)
        if post_id is not None:
            self.roots[msg.id] = post_id
            for reply in self._pending.pop(msg.id, ()):
                self._record(reply, post_id)
            return
        top = reply_top_id(msg)
        if top is None:
            return
        if top in self.roots:
            self._record(msg, self.roots[top])
        else:
            self._pending.setdefault(top, []).append(msg)

    # --- per-post strategy: comments already known to belong to `post_id` ---

    def feed_post_comment(self, msg: Any, post_id: int) -> None:
        if isinstance(msg, types.Message):
            self._record(msg, post_id)

    def _record(self, msg: Any, post_id: int) -> None:
        if msg.id in self._seen:
            return
        self._seen.add(msg.id)
        sender = sender_peer_id(msg)
        self.participants.setdefault(sender, ParticipantStats()).add(post_id, msg.date)
        self.posts_with_comments.add(post_id)
        self.total += 1
        fwd = forwarded_from(msg)
        if fwd is not None:
            self.fwd_sources.add(fwd)
        self._new.append(CommentRec(msg.id, post_id, sender, msg.date, _text(msg), reply_target(msg), fwd))

    def drain_new(self) -> list[CommentRec]:
        """Comments recorded since the previous call (for batched DB inserts)."""
        out, self._new = self._new, []
        return out

    def unresolved_tops(self) -> list[int]:
        """Thread roots referenced by replies but not seen yet (older than the scanned range)."""
        return list(self._pending)

    @property
    def orphaned(self) -> int:
        """Replies whose root never showed up: ordinary chat replies or threads of deleted posts."""
        return sum(len(v) for v in self._pending.values())
