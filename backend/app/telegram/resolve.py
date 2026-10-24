"""Resolve a pasted link into a Telegram chat entity and classify what kind of source it is."""

from typing import Any, Literal

from telethon import TelegramClient, errors, utils
from telethon.tl import functions, types

from app.telegram.links import ChannelRef

SourceType = Literal["channel", "supergroup", "forum", "gigagroup", "group"]
TYPE_LABELS = {"channel": "Канал", "supergroup": "Супергруппа", "forum": "Форум", "gigagroup": "Гигагруппа", "group": "Группа"}


class UserFacingError(Exception):
    pass


def source_type(entity: Any) -> SourceType:
    if isinstance(entity, types.Chat):
        return "group"
    if isinstance(entity, types.Channel):
        if entity.broadcast:
            return "channel"
        if getattr(entity, "gigagroup", False):
            return "gigagroup"
        if getattr(entity, "forum", False):
            return "forum"
        return "supergroup"
    raise UserFacingError("Это не канал и не группа")


async def resolve_chat(client: TelegramClient, ref: ChannelRef) -> Any:
    """Channel / supergroup / basic group the account can read. Raises UserFacingError."""
    try:
        if ref.username:
            entity = await client.get_entity(ref.username)
        elif ref.invite_hash:
            invite = await client(functions.messages.CheckChatInviteRequest(ref.invite_hash))
            entity = getattr(invite, "chat", None)
            if entity is None:
                raise UserFacingError(f"Приватный чат «{getattr(invite, 'title', '')}»: сначала вступите в него этим аккаунтом")
        elif ref.chat_id:
            entity = await client.get_entity(types.PeerChat(ref.chat_id))
        else:
            entity = await client.get_entity(types.PeerChannel(ref.channel_id))
    except (errors.UsernameNotOccupiedError, errors.UsernameInvalidError) as e:
        raise UserFacingError(f"{ref.display} не найден") from e
    except (errors.InviteHashExpiredError, errors.InviteHashInvalidError) as e:
        raise UserFacingError("Ссылка-приглашение недействительна") from e
    except ValueError as e:
        raise UserFacingError(f"Не удалось найти {ref.display}: аккаунт не имеет к нему доступа") from e
    if isinstance(entity, (types.ChannelForbidden, types.ChatForbidden)):
        raise UserFacingError(f"{ref.display}: аккаунт заблокирован или исключён из этого чата")
    if isinstance(entity, types.User):
        raise UserFacingError(f"{ref.display} — это пользователь{' (бот)' if entity.bot else ''}, а не канал или группа")
    source_type(entity)
    return entity


async def full_info(client: TelegramClient, entity: Any) -> Any:
    """ChannelFull / ChatFull of the entity (`.full_chat` plus `.chats`)."""
    if isinstance(entity, types.Chat):
        return await client(functions.messages.GetFullChatRequest(entity.id))
    return await client(functions.channels.GetFullChannelRequest(entity))


def public_link(username: str | None, peer_id: int, msg_id: int | None = None) -> str | None:
    """Message (or chat) link: t.me/name/123 for public chats, t.me/c/<id>/123 for private supergroups."""
    if username:
        return f"https://t.me/{username}" + (f"/{msg_id}" if msg_id else "")
    if msg_id and str(peer_id).startswith("-100"):
        return f"https://t.me/c/{str(peer_id)[4:]}/{msg_id}"
    return None


async def preview(client: TelegramClient, ref: ChannelRef) -> dict[str, Any]:
    """What a link points to, for the «add source» dialog. Read-only."""
    entity = await resolve_chat(client, ref)
    kind = source_type(entity)
    full = await full_info(client, entity)
    fc = full.full_chat
    linked_id = getattr(fc, "linked_chat_id", None)
    linked = next((c for c in full.chats if c.id == linked_id), None) if linked_id else None
    members = getattr(fc, "participants_count", None)
    if members is None and isinstance(getattr(fc, "participants", None), types.ChatParticipants):
        members = len(fc.participants.participants)
    return {
        "id": utils.get_peer_id(entity),
        "type": kind,
        "type_label": TYPE_LABELS[kind],
        "title": getattr(entity, "title", None),
        "username": getattr(entity, "username", None),
        "members_count": members,
        # can the member list be read (hidden by admins in big groups)
        "members_visible": kind != "channel" and bool(getattr(fc, "can_view_participants", True))
        and not getattr(fc, "participants_hidden", False),
        "about": (getattr(fc, "about", None) or "")[:300],
        "linked_chat": {"id": utils.get_peer_id(linked), "title": linked.title, "username": linked.username,
                        "type": source_type(linked)} if linked else None,
        "is_member": not getattr(entity, "left", False),
        "tool": "comment-collector" if kind == "channel" else "chat-indexer",
    }
