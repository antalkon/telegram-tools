import pytest

from app.telegram.links import ChannelRef, LinkError, parse_channel_link


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("@durov", ChannelRef(username="durov")),
        ("durov", ChannelRef(username="durov")),
        ("t.me/durov", ChannelRef(username="durov")),
        ("https://t.me/durov", ChannelRef(username="durov")),
        ("https://t.me/durov/123", ChannelRef(username="durov")),
        ("https://t.me/durov/123?comment=5", ChannelRef(username="durov")),
        ("https://t.me/s/durov", ChannelRef(username="durov")),
        ("http://telegram.me/durov/", ChannelRef(username="durov")),
        ("https://durov.t.me", ChannelRef(username="durov")),
        ("tg://resolve?domain=durov", ChannelRef(username="durov")),
        ("https://t.me/+AbCdEf123_-x", ChannelRef(invite_hash="AbCdEf123_-x")),
        ("https://t.me/joinchat/AbCdEf", ChannelRef(invite_hash="AbCdEf")),
        ("https://t.me/c/1234567890/55", ChannelRef(channel_id=1234567890)),
        ("  https://t.me/durov  ", ChannelRef(username="durov")),
    ],
)
def test_parse(raw, expected):
    assert parse_channel_link(raw) == expected


@pytest.mark.parametrize("raw", ["", "https://example.com/durov", "t.me/", "@ab", "t.me/joinchat", "hello world"])
def test_invalid(raw):
    with pytest.raises(LinkError):
        parse_channel_link(raw)
