"""Owns the live TelegramClient per connected account and the multi-step login flow."""

import asyncio
import secrets
import time
from dataclasses import dataclass, field

from sqlalchemy import select
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from app.db import SessionLocal
from app.models import Account
from app.security import decrypt, encrypt
from app.telegram.peers import download_avatar

PENDING_TTL = 15 * 60


class LoginError(Exception):
    pass


@dataclass
class PendingLogin:
    client: TelegramClient
    phone: str
    api_id: int
    api_hash: str
    phone_code_hash: str
    created: float = field(default_factory=time.monotonic)


def _new_client(session: str, api_id: int, api_hash: str) -> TelegramClient:
    return TelegramClient(
        StringSession(session),
        api_id,
        api_hash,
        flood_sleep_threshold=60,
        device_model="TG Toolkit",
        app_version="1.0",
        system_version="Web",
    )


class AccountManager:
    def __init__(self) -> None:
        self._clients: dict[int, TelegramClient] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._pending: dict[str, PendingLogin] = {}

    # ---------- live clients ----------

    async def get_client(self, account_id: int) -> TelegramClient:
        lock = self._locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            client = self._clients.get(account_id)
            if client and client.is_connected():
                return client
            async with SessionLocal() as db:
                acc = await db.get(Account, account_id)
                if not acc:
                    raise LoginError("Аккаунт не найден")
                client = _new_client(decrypt(acc.session_enc), acc.api_id, decrypt(acc.api_hash_enc))
                await client.connect()
                if not await client.is_user_authorized():
                    acc.status, acc.last_error = "error", "Сессия больше не авторизована — подключите аккаунт заново"
                    await db.commit()
                    await client.disconnect()
                    raise LoginError(acc.last_error)
                if acc.status != "active":
                    acc.status, acc.last_error = "active", None
                    await db.commit()
            self._clients[account_id] = client
            return client

    async def drop(self, account_id: int) -> None:
        client = self._clients.pop(account_id, None)
        if client:
            await client.disconnect()

    async def shutdown(self) -> None:
        for client in list(self._clients.values()) + [p.client for p in self._pending.values()]:
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()
        self._pending.clear()

    # ---------- login flow ----------

    def _gc_pending(self) -> None:
        now = time.monotonic()
        for key, p in list(self._pending.items()):
            if now - p.created > PENDING_TTL:
                self._pending.pop(key)
                asyncio.create_task(p.client.disconnect())

    def _take(self, login_id: str) -> PendingLogin:
        self._gc_pending()
        p = self._pending.get(login_id)
        if not p:
            raise LoginError("Сессия входа истекла — начните заново")
        return p

    async def start_login(self, api_id: int, api_hash: str, phone: str) -> tuple[str, str]:
        self._gc_pending()
        client = _new_client("", api_id, api_hash)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
        except errors.ApiIdInvalidError as e:
            await client.disconnect()
            raise LoginError("Неверные api_id / api_hash") from e
        except errors.PhoneNumberInvalidError as e:
            await client.disconnect()
            raise LoginError("Неверный номер телефона") from e
        except errors.FloodWaitError as e:
            await client.disconnect()
            raise LoginError(f"Слишком много попыток, подождите {e.seconds} с") from e
        login_id = secrets.token_urlsafe(16)
        self._pending[login_id] = PendingLogin(client, phone, api_id, api_hash, sent.phone_code_hash)
        delivery = type(sent.type).__name__.removeprefix("SentCodeType").lower()  # app | sms | call …
        return login_id, delivery

    async def submit_code(self, login_id: str, code: str) -> Account | None:
        """Returns the saved Account, or None when a 2FA password is required."""
        p = self._take(login_id)
        try:
            await p.client.sign_in(p.phone, code.strip(), phone_code_hash=p.phone_code_hash)
        except errors.SessionPasswordNeededError:
            return None
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError) as e:
            raise LoginError("Неверный код") from e
        except errors.PhoneCodeExpiredError as e:
            raise LoginError("Код истёк — начните заново") from e
        return await self._finish(login_id)

    async def submit_password(self, login_id: str, password: str) -> Account:
        p = self._take(login_id)
        try:
            await p.client.sign_in(password=password)
        except errors.PasswordHashInvalidError as e:
            raise LoginError("Неверный пароль 2FA") from e
        return await self._finish(login_id)

    async def _finish(self, login_id: str) -> Account:
        p = self._pending.pop(login_id)
        me = await p.client.get_me()
        try:
            await download_avatar(p.client, me)
        except Exception:
            pass
        async with SessionLocal() as db:
            existing = (await db.execute(select(Account).where(Account.tg_user_id == me.id))).scalar_one_or_none()
            acc = existing or Account()
            acc.phone = p.phone
            acc.api_id = p.api_id
            acc.api_hash_enc = encrypt(p.api_hash)
            acc.session_enc = encrypt(p.client.session.save())
            acc.tg_user_id = me.id
            acc.first_name, acc.last_name, acc.username = me.first_name, me.last_name, me.username
            acc.photo_id = getattr(me.photo, "photo_id", None)
            acc.status, acc.last_error = "active", None
            if not existing:
                db.add(acc)
            await db.commit()
            await db.refresh(acc)
        await self.drop(acc.id)
        self._clients[acc.id] = p.client
        return acc


manager = AccountManager()
