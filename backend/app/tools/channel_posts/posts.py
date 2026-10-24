"""Posts of a channel: text, views, forwards, where a post was forwarded from, links and ad marking.

Two ways, chosen per run: through the Telegram account (any channel it can read, exact counters) or
through the public t.me/s/ web preview (public channels only, no account and no Telegram limits spent).
"""

import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from telethon import errors, utils
from telethon.tl import types

from app.db import SessionLocal
from app.jobs.runner import JobContext
from app.models import ChannelPost, TgPeer, utcnow
from app.telegram.access import save_access
from app.telegram.contacts import ad_marking
from app.telegram.links import LinkError, parse_channel_link
from app.telegram.peers import upsert_peers
from app.telegram.resolve import UserFacingError, full_info, resolve_chat
from app.telegram.web_preview import PreviewUnavailable, WebPost, fetch_page, parse_page
from app.tools.base import Tool, register
from app.tools.comment_collector.aggregate import forwarded_from

TOOL_ID = "channel-posts"
BATCH = 300
WEB_PAGE_DELAY = 1.5  # seconds between t.me/s pages: polite, and keeps clear of its rate limit


class PostsInput(BaseModel):
    channel: str = Field(min_length=1, max_length=256)
    via: Literal["account", "web"] = "account"
    limit: int = Field(1000, ge=1, le=100_000)  # newest N posts
    since: date | None = None  # stop at posts older than this day

    @field_validator("channel")
    @classmethod
    def _valid_link(cls, v: str) -> str:
        try:
            parse_channel_link(v)
        except LinkError as e:
            raise ValueError(str(e)) from e
        return v.strip()


def post_row(key: str, channel_id: int | None, username: str | None, via: str, *, post_id: int, date, text, views,
             forwards, replies, media: bool, links: list[str], fwd_from, fwd_name, fwd_username) -> dict[str, Any]:
    ad = ad_marking(text, links) or {}
    return {"channel_key": key, "post_id": post_id, "channel_id": channel_id, "username": (username or "").lower() or None,
            "date": date, "text": text, "views": views, "forwards": forwards, "replies": replies, "media": media,
            "links": links, "fwd_from": fwd_from, "fwd_from_name": fwd_name, "fwd_from_username": fwd_username,
            "erid": ad.get("erid"), "advertiser": ad.get("advertiser"), "advertiser_inn": ad.get("inn"),
            "via": via, "collected_at": utcnow()}


async def save_posts(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with SessionLocal() as db:
        for i in range(0, len(rows), BATCH):
            stmt = sqlite_insert(ChannelPost).values(rows[i:i + BATCH])
            await db.execute(stmt.on_conflict_do_update(
                index_elements=["channel_key", "post_id"],
                set_={c: stmt.excluded[c] for c in rows[0] if c not in ("channel_key", "post_id")}))
        await db.commit()


def _message_links(msg: Any) -> list[str]:
    links = [e.url for e in (getattr(msg, "entities", None) or []) if isinstance(e, types.MessageEntityTextUrl)]
    markup = getattr(msg, "reply_markup", None)
    for row in getattr(markup, "rows", None) or []:
        links += [b.url for b in row.buttons if isinstance(b, types.KeyboardButtonUrl)]
    return list(dict.fromkeys(links))


class ChannelPosts(Tool):
    id = TOOL_ID
    title = "Посты каналов"
    description = "Посты канала с просмотрами, репостами, ссылками и маркировкой рекламы — через аккаунт или без него"
    Input = PostsInput

    async def run(self, ctx: JobContext, params: PostsInput) -> dict[str, Any]:
        started = time.monotonic()
        since = datetime.combine(params.since, datetime.min.time(), UTC) if params.since else None
        if params.via == "web":
            stats = await self._web(ctx, params, since)
        else:
            stats = await self._account(ctx, params, since)
        return stats | {"via": params.via, "duration_sec": round(time.monotonic() - started, 1)}

    async def _account(self, ctx: JobContext, params: PostsInput, since) -> dict[str, Any]:
        client = await ctx.client()
        await ctx.update(force=True, phase="resolve")
        entity = await resolve_chat(client, parse_channel_link(params.channel))
        if not (isinstance(entity, types.Channel) and entity.broadcast):
            raise UserFacingError("Это не канал: у чатов нет постов — проиндексируйте его как чат")
        full = await full_info(client, entity)
        cid = utils.get_peer_id(entity)
        async with SessionLocal() as db:
            await upsert_peers(db, [entity])
            await save_access(db, [entity])
            await db.execute(TgPeer.__table__.update().where(TgPeer.id == cid).values(about=getattr(full.full_chat, "about", None) or None))
            await db.commit()
        info = {"id": cid, "title": entity.title, "username": entity.username,
                "subscribers": getattr(full.full_chat, "participants_count", None)}
        await ctx.set_source(cid)
        total = min((await client.get_messages(entity, limit=0)).total, params.limit)
        await ctx.update(force=True, phase="scan", channel=info, posts_total=total, posts_done=0)

        rows: list[dict[str, Any]] = []
        fwd_entities: dict[int, Any] = {}
        done = ads = 0
        offset = 0
        while True:
            try:
                async for msg in client.iter_messages(entity, limit=params.limit - done, offset_id=offset, wait_time=0):
                    offset = msg.id
                    if since and msg.date < since:
                        break
                    done += 1
                    if not isinstance(msg, types.Message):
                        continue
                    fwd = getattr(msg, "fwd_from", None)
                    chat = getattr(getattr(msg, "forward", None), "chat", None) if fwd else None
                    if isinstance(chat, types.Channel):
                        fwd_entities[utils.get_peer_id(chat)] = chat
                    row = post_row(str(cid), cid, entity.username, "account", post_id=msg.id, date=msg.date,
                                   text=msg.message or None, views=msg.views, forwards=msg.forwards,
                                   replies=getattr(getattr(msg, "replies", None), "replies", None),
                                   media=msg.media is not None and not isinstance(msg.media, types.MessageMediaWebPage),
                                   links=_message_links(msg), fwd_from=forwarded_from(msg),
                                   fwd_name=(getattr(fwd, "from_name", None) or getattr(chat, "title", None)) if fwd else None,
                                   fwd_username=getattr(chat, "username", None) if chat else None)
                    ads += bool(row["erid"] or row["advertiser_inn"])
                    rows.append(row)
                    if len(rows) >= BATCH:
                        await save_posts(rows)
                        rows.clear()
                        await ctx.update(posts_done=done, ads=ads)
                break
            except errors.FloodWaitError as e:
                until = datetime.now(UTC) + timedelta(seconds=e.seconds)
                await ctx.update(force=True, flood_wait_until=until.isoformat())
                await asyncio.sleep(e.seconds + 1)
                await ctx.update(force=True, flood_wait_until=None)
            finally:
                await save_posts(rows)
                rows.clear()
        if fwd_entities:
            async with SessionLocal() as db:
                await upsert_peers(db, list(fwd_entities.values()))
                await save_access(db, list(fwd_entities.values()))
                await db.commit()
        await ctx.update(force=True, posts_done=done, ads=ads)
        return {"channel": info, "posts": done, "ads": ads, "forwarded_from": len(fwd_entities)}

    async def _web(self, ctx: JobContext, params: PostsInput, since) -> dict[str, Any]:
        ref = parse_channel_link(params.channel)
        if not ref.username:
            raise UserFacingError("Без аккаунта читаются только публичные каналы с @username")
        username = ref.username
        await ctx.update(force=True, phase="resolve")
        done = ads = pages = 0
        info: dict[str, Any] = {}
        before: int | None = None
        async with httpx.AsyncClient() as http:
            while done < params.limit:
                try:
                    html = await fetch_page(http, username, before)
                    page_info, posts = parse_page(html, username)
                except PreviewUnavailable as e:
                    if pages:
                        break  # rate-limited half way: keep what we have
                    raise UserFacingError(str(e)) from e
                pages += 1
                if not info:
                    info = page_info
                    info["id"] = info["id"] or None
                    await self._save_web_channel(info)
                    if info["id"]:
                        await ctx.set_source(info["id"])
                    await ctx.update(force=True, phase="scan", channel=info, posts_total=params.limit, posts_done=0)
                posts = sorted(posts, key=lambda p: p.post_id, reverse=True)
                if not posts:
                    break
                stop = False
                rows = []
                for p in posts:
                    if (since and p.date and p.date < since) or done >= params.limit:
                        stop = True
                        break
                    rows.append(self._web_row(info, p))
                    ads += bool(rows[-1]["erid"] or rows[-1]["advertiser_inn"])
                    done += 1
                await save_posts(rows)
                await ctx.update(posts_done=done, ads=ads, pages=pages)
                nxt = min(p.post_id for p in posts)
                if stop or nxt <= 1 or nxt == before:
                    break
                before = nxt
                await asyncio.sleep(WEB_PAGE_DELAY)
        await ctx.update(force=True, posts_done=done, ads=ads)
        return {"channel": info, "posts": done, "ads": ads, "pages": pages}

    @staticmethod
    def _web_row(info: dict[str, Any], p: WebPost) -> dict[str, Any]:
        cid = info.get("id")
        return post_row(str(cid) if cid else f"@{info['username'].lower()}", cid, info["username"], "web",
                        post_id=p.post_id, date=p.date, text=p.text, views=p.views, forwards=None, replies=None,
                        media=p.media, links=p.links, fwd_from=None, fwd_name=p.fwd_name, fwd_username=p.fwd_username)

    @staticmethod
    async def _save_web_channel(info: dict[str, Any]) -> None:
        """Keep the channel in tg_peers when the page gave its id, so it shows up like any other peer."""
        if not info.get("id"):
            return
        async with SessionLocal() as db:
            stmt = sqlite_insert(TgPeer).values(id=info["id"], kind="channel", title=info["title"], username=info["username"],
                                                usernames=[info["username"]], about=info.get("about"))
            await db.execute(stmt.on_conflict_do_update(index_elements=["id"], set_={
                "title": stmt.excluded.title, "username": stmt.excluded.username,
                "about": func.coalesce(stmt.excluded.about, TgPeer.about)}))
            await db.commit()


register(ChannelPosts())
