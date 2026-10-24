from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Account, iso
from app.security import require_admin
from app.telegram.manager import LoginError, manager
from app.telegram.peers import avatar_path

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(require_admin)])


def account_out(a: Account) -> dict:
    return {
        "id": a.id,
        "phone": a.phone,
        "tg_user_id": a.tg_user_id,
        "first_name": a.first_name,
        "last_name": a.last_name,
        "username": a.username,
        "photo_id": str(a.photo_id) if a.photo_id and avatar_path(a.photo_id).exists() else None,
        "status": a.status,
        "last_error": a.last_error,
        "created_at": iso(a.created_at),
    }


class StartIn(BaseModel):
    api_id: int = Field(gt=0)
    api_hash: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-fA-F]{32}$")
    phone: str = Field(min_length=5, max_length=20)


class CodeIn(BaseModel):
    login_id: str
    code: str = Field(min_length=3, max_length=10)


class PasswordIn(BaseModel):
    login_id: str
    password: str = Field(min_length=1)


@router.get("")
async def list_accounts(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Account).order_by(Account.id))).scalars().all()
    return [account_out(a) for a in rows]


@router.post("/login/start")
async def login_start(body: StartIn):
    try:
        login_id, delivery = await manager.start_login(body.api_id, body.api_hash.lower(), body.phone.replace(" ", ""))
    except LoginError as e:
        raise HTTPException(400, str(e)) from e
    return {"login_id": login_id, "delivery": delivery}


@router.post("/login/code")
async def login_code(body: CodeIn):
    try:
        acc = await manager.submit_code(body.login_id, body.code)
    except LoginError as e:
        raise HTTPException(400, str(e)) from e
    if acc is None:
        return {"status": "password_required"}
    return {"status": "ok", "account": account_out(acc)}


@router.post("/login/password")
async def login_password(body: PasswordIn):
    try:
        acc = await manager.submit_password(body.login_id, body.password)
    except LoginError as e:
        raise HTTPException(400, str(e)) from e
    return {"status": "ok", "account": account_out(acc)}


@router.post("/{account_id}/check")
async def check_account(account_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await manager.get_client(account_id)
    except LoginError as e:
        raise HTTPException(400, str(e)) from e
    acc = await db.get(Account, account_id)
    await db.refresh(acc)
    return account_out(acc)


@router.delete("/{account_id}")
async def delete_account(account_id: int, db: AsyncSession = Depends(get_db)):
    acc = await db.get(Account, account_id)
    if not acc:
        raise HTTPException(404, "Аккаунт не найден")
    await manager.drop(account_id)
    await db.delete(acc)
    await db.commit()
    return {"ok": True}
