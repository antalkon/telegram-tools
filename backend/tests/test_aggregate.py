from datetime import UTC, datetime, timedelta

from telethon.tl import types

from app.tools.comment_collector.aggregate import CommentAggregator

CHANNEL = 1001
GROUP = 2002
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def root(msg_id, post_id, channel=CHANNEL):
    return types.Message(
        id=msg_id,
        peer_id=types.PeerChannel(GROUP),
        date=T0,
        message="post",
        from_id=types.PeerChannel(channel),
        fwd_from=types.MessageFwdHeader(
            date=T0,
            from_id=types.PeerChannel(channel),
            channel_post=post_id,
            saved_from_peer=types.PeerChannel(channel),
            saved_from_msg_id=post_id,
        ),
    )


def reply(msg_id, sender, to, top=None, minutes=0, sender_channel=False):
    return types.Message(
        id=msg_id,
        peer_id=types.PeerChannel(GROUP),
        date=T0 + timedelta(minutes=minutes),
        message=f"comment {msg_id}",
        from_id=types.PeerChannel(sender) if sender_channel else types.PeerUser(sender) if sender else None,
        reply_to=types.MessageReplyHeader(reply_to_msg_id=to, reply_to_top_id=top),
    )


def chat(msg_id, sender):
    return types.Message(id=msg_id, peer_id=types.PeerChannel(GROUP), date=T0, message="hi", from_id=types.PeerUser(sender))


def test_counts_comments_and_replies_to_comments():
    agg = CommentAggregator(CHANNEL)
    for m in [
        root(10, 1),
        reply(11, 500, to=10, minutes=1),
        reply(12, 501, to=11, top=10, minutes=2),  # reply to a comment, same thread
        root(20, 2),
        reply(21, 500, to=20, minutes=5),
        reply(22, 500, to=20, minutes=6),
    ]:
        agg.feed_group_message(m)

    assert agg.total == 4
    assert agg.posts_with_comments == {1, 2}
    u = agg.participants[500]
    assert (u.comments, len(u.posts)) == (3, 2)
    assert u.first_at == T0 + timedelta(minutes=1)
    assert u.last_at == T0 + timedelta(minutes=6)
    assert agg.participants[501].comments == 1


def test_ignores_plain_chat_and_service_messages():
    agg = CommentAggregator(CHANNEL)
    agg.feed_group_message(root(10, 1))
    agg.feed_group_message(chat(11, 700))  # ordinary group chat
    agg.feed_group_message(reply(12, 701, to=11))  # reply inside ordinary chat
    agg.feed_group_message(types.MessageService(id=13, peer_id=types.PeerChannel(GROUP), date=T0,
                                                action=types.MessageActionChatJoinedByLink(inviter_id=1)))
    assert agg.total == 0
    assert agg.orphaned == 1


def test_forward_from_another_channel_is_not_a_root():
    agg = CommentAggregator(CHANNEL)
    agg.feed_group_message(root(10, 1, channel=9999))
    agg.feed_group_message(reply(11, 500, to=10))
    assert agg.total == 0


def test_reply_seen_before_root_is_resolved():
    agg = CommentAggregator(CHANNEL)
    agg.feed_group_message(reply(11, 500, to=10))
    assert agg.total == 0
    agg.feed_group_message(root(10, 1))
    assert agg.total == 1
    assert agg.orphaned == 0


def test_channel_and_anonymous_senders():
    agg = CommentAggregator(CHANNEL)
    agg.feed_group_message(root(10, 1))
    agg.feed_group_message(reply(11, 3333, to=10, sender_channel=True))  # "send as" channel
    agg.feed_group_message(reply(12, None, to=10))  # anonymous admin -> the group itself
    assert set(agg.participants) == {-1000000003333, -1000000002002}


def test_per_post_dedup_and_drain():
    agg = CommentAggregator(CHANNEL)
    m = reply(11, 500, to=10)
    agg.feed_post_comment(m, 1)
    agg.feed_post_comment(m, 1)
    assert agg.total == 1
    drained = agg.drain_new()
    assert [(c.msg_id, c.post_id, c.sender_id) for c in drained] == [(11, 1, 500)]
    assert agg.drain_new() == []
