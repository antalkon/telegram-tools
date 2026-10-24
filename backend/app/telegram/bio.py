"""Find channel / chat references in free text such as a profile bio."""

import re
from dataclasses import dataclass

from app.telegram.links import LinkError, parse_channel_link

_NAME = r"[A-Za-z][A-Za-z0-9_]{3,31}"
_URL = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(?:s/)?(?:\+|joinchat/)?[A-Za-z0-9_\-]+"
    rf"|(?:https?://)?{_NAME}\.t\.me\b"
    rf"|tg://resolve\?domain={_NAME}"
    r"|tg://join\?invite=[A-Za-z0-9_\-]+",
    re.I,
)
# @name not glued to a word (e-mails) or a URL path
_MENTION = re.compile(rf"(?<![\w@/.])@({_NAME})\b")


@dataclass(frozen=True)
class Ref:
    username: str | None = None
    invite: str | None = None

    @property
    def key(self) -> str:
        """Lookup-cache key: lower-cased username or "+hash"."""
        return f"+{self.invite}" if self.invite else self.username.lower()


def extract_refs(text: str | None) -> list[Ref]:
    """Usernames and invite hashes mentioned in text, in order, without duplicates. Names ending in
    "bot" are skipped: those are bots, never channels."""
    if not text:
        return []
    out: dict[str, Ref] = {}
    for m in _URL.finditer(text):
        raw = m.group(0)
        if raw.lower().startswith("tg://join"):
            ref = Ref(invite=raw.split("=", 1)[1])
        else:
            try:
                r = parse_channel_link(raw)
            except LinkError:
                continue
            if r.invite_hash:
                ref = Ref(invite=r.invite_hash)
            elif r.username:
                ref = Ref(username=r.username)
            else:
                continue
        out.setdefault(ref.key, ref)
    for m in _MENTION.finditer(text):
        ref = Ref(username=m.group(1))
        out.setdefault(ref.key, ref)
    return [r for r in out.values() if not (r.username and r.username.lower().endswith("bot"))]
