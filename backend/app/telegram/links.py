"""Parse the many ways people paste a Telegram channel reference."""

import re
from dataclasses import dataclass

_USERNAME = r"[A-Za-z][A-Za-z0-9_]{3,31}"
_RESERVED = {"joinchat", "addstickers", "share", "proxy", "socks", "addlist", "s", "c", "iv", "login"}


@dataclass(frozen=True)
class ChannelRef:
    username: str | None = None  # public @username
    invite_hash: str | None = None  # t.me/+HASH or t.me/joinchat/HASH
    channel_id: int | None = None  # t.me/c/<id>/<msg> (private link, bare channel id)
    chat_id: int | None = None  # basic group, only as a numeric id (-123456)

    @property
    def display(self) -> str:
        if self.username:
            return f"@{self.username}"
        if self.invite_hash:
            return f"t.me/+{self.invite_hash}"
        if self.chat_id:
            return f"чат {-self.chat_id}"
        return f"t.me/c/{self.channel_id}"


class LinkError(ValueError):
    pass


def parse_channel_link(raw: str) -> ChannelRef:
    s = raw.strip()
    if not s:
        raise LinkError("Пустая ссылка")

    # numeric peer ids as Telegram clients and bots show them
    if m := re.fullmatch(r"-100(\d{5,})", s):
        return ChannelRef(channel_id=int(m.group(1)))
    if m := re.fullmatch(r"-(\d{3,12})", s):
        return ChannelRef(chat_id=int(m.group(1)))
    if m := re.fullmatch(rf"@({_USERNAME})", s):
        return ChannelRef(username=m.group(1))
    if m := re.fullmatch(r"tg://resolve\?domain=(" + _USERNAME + r")(?:&.*)?", s):
        return ChannelRef(username=m.group(1))

    s = re.sub(r"^(?:https?://)?(?:www\.)?", "", s, flags=re.I)
    s = re.sub(r"^(?:telegram\.me|telegram\.dog|t\.me)/", "t.me/", s, flags=re.I)

    if s.startswith("t.me/"):
        path = s[len("t.me/"):].split("?")[0].split("#")[0].strip("/")
        parts = path.split("/")
        head = parts[0] if parts else ""
        if head.startswith("+") and len(head) > 1:
            return ChannelRef(invite_hash=head[1:])
        if head == "joinchat" and len(parts) > 1:
            return ChannelRef(invite_hash=parts[1])
        if head == "c" and len(parts) > 1 and parts[1].isdigit():
            return ChannelRef(channel_id=int(parts[1]))
        if head == "s" and len(parts) > 1:
            head = parts[1]
        if re.fullmatch(_USERNAME, head) and head.lower() not in _RESERVED:
            return ChannelRef(username=head)
        raise LinkError("Не удалось распознать ссылку на канал или чат")

    # https://name.t.me
    if m := re.fullmatch(rf"({_USERNAME})\.t\.me/?", s, flags=re.I):
        return ChannelRef(username=m.group(1))
    # bare username
    if re.fullmatch(_USERNAME, s):
        return ChannelRef(username=s)
    raise LinkError("Не удалось распознать ссылку на канал или чат")
