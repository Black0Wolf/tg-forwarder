"""Modular admin system.

Each Telegram user that needs bot/WebUI access is an ``Admin`` row.
Each admin has:
  * a ``level`` (1 = regular, 9 = super-admin; super-admins bypass all
    permission checks),
  * zero or more ``PermissionFlag`` rows named after values of the
    ``Perm`` enum.

The super_admins list in ``config.yaml`` is automatically seeded as
level-9 admins on first startup. Anyone else must be added by an
existing admin with the ``MANAGE_ADMINS`` permission.

The ``require_perm`` decorator wraps bot command handlers and FastAPI
endpoints to enforce permissions.
"""
from __future__ import annotations

import asyncio
import functools
from typing import Awaitable, Callable

from sqlalchemy import delete, select
from telethon.tl.custom import Message as TgMessage

from app.config import get_settings
from app.models import Admin, ALL_PERMS, PermissionFlag, Perm, session
from app.telethon_client import db_log


# ---------------------------------------------------------------------------
#  Bootstrap
# ---------------------------------------------------------------------------
async def seed_super_admins() -> None:
    """Upsert every id in ``config.super_admins`` as a level-9 admin."""
    cfg = get_settings()
    if not cfg.super_admins:
        return
    async with session() as sess:
        for tg_id in cfg.super_admins:
            existing_q = await sess.execute(
                select(Admin).where(Admin.tg_user_id == tg_id)
            )
            existing = existing_q.scalar_one_or_none()
            if existing is None:
                sess.add(Admin(
                    tg_user_id=tg_id,
                    level=9,
                    tg_username=None,
                    tg_first_name=None,
                    added_by=0,
                ))
            else:
                existing.level = 9
        await sess.commit()


# ---------------------------------------------------------------------------
#  Lookup helpers
# ---------------------------------------------------------------------------
async def get_admin(tg_user_id: int) -> Admin | None:
    async with session() as sess:
        q = await sess.execute(select(Admin).where(Admin.tg_user_id == tg_user_id))
        return q.scalar_one_or_none()


async def list_admins() -> list[Admin]:
    async with session() as sess:
        q = await sess.execute(select(Admin).order_by(Admin.level.desc(), Admin.tg_username))
        return list(q.scalars().all())


async def add_admin(
    tg_user_id: int,
    *,
    tg_username: str | None = None,
    tg_first_name: str | None = None,
    level: int = 1,
    perms: list[Perm] | None = None,
    added_by: int | None = None,
) -> Admin:
    async with session() as sess:
        existing_q = await sess.execute(select(Admin).where(Admin.tg_user_id == tg_user_id))
        existing = existing_q.scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"Admin {tg_user_id} already exists")
        admin = Admin(
            tg_user_id=tg_user_id,
            tg_username=tg_username,
            tg_first_name=tg_first_name,
            level=level,
            added_by=added_by,
        )
        sess.add(admin)
        await sess.flush()  # get admin.id
        for p in (perms or []):
            sess.add(PermissionFlag(admin_id=admin.id, name=p.value))
        await sess.commit()
        await sess.refresh(admin)
        return admin


async def remove_admin(tg_user_id: int) -> bool:
    async with session() as sess:
        q = await sess.execute(select(Admin).where(Admin.tg_user_id == tg_user_id))
        admin = q.scalar_one_or_none()
        if admin is None:
            return False
        if admin.is_super:
            raise ValueError("Cannot remove a super-admin via API. Edit config.yaml.")
        await sess.delete(admin)
        await sess.commit()
        return True


async def set_perm(tg_user_id: int, perm: Perm, enabled: bool) -> None:
    async with session() as sess:
        q = await sess.execute(select(Admin).where(Admin.tg_user_id == tg_user_id))
        admin = q.scalar_one_or_none()
        if admin is None:
            raise ValueError("Admin not found")
        if admin.is_super:
            return  # super admins implicitly have all perms; no flags needed
        existing_q = await sess.execute(
            select(PermissionFlag).where(
                PermissionFlag.admin_id == admin.id,
                PermissionFlag.name == perm.value,
            )
        )
        existing = existing_q.scalar_one_or_none()
        if enabled and existing is None:
            sess.add(PermissionFlag(admin_id=admin.id, name=perm.value))
        elif not enabled and existing is not None:
            await sess.delete(existing)
        await sess.commit()


async def admin_perms(tg_user_id: int) -> dict[str, bool]:
    """Return a ``{perm_value: bool}`` dict for every Perm, suitable for UI."""
    admin = await get_admin(tg_user_id)
    if admin is None:
        return {p.value: False for p in ALL_PERMS}
    if admin.is_super:
        return {p.value: True for p in ALL_PERMS}
    return {p.value: (p.value in [f.name for f in admin.flags]) for p in ALL_PERMS}


# ---------------------------------------------------------------------------
#  Decorator: require_perm
# ---------------------------------------------------------------------------
def require_perm(perm: Perm) -> Callable:
    """Decorator for async bot handlers.

    Expects the handler signature ``async def handler(event, admin: Admin)``.
    The decorator looks up the sender's Admin row; if missing or without
    permission, it replies with a short error and skips the call.
    """
    def deco(fn: Callable[..., Awaitable]):
        @functools.wraps(fn)
        async def wrapper(event, *args, **kwargs):
            sender_id = event.sender_id
            if sender_id is None:
                return
            admin = await get_admin(sender_id)
            if admin is None:
                await event.reply("⛔ You are not registered as an admin.")
                return
            if not admin.has_perm(perm):
                await event.reply(f"⛔ Missing permission: `{perm.value}`")
                return
            return await fn(event, admin, *args, **kwargs)
        return wrapper
    return deco


def require_perm_web(perm: Perm):
    """Decorator for FastAPI dependency injection.

    Usage::

        @router.get("/foo", dependencies=[Depends(require_perm_web(Perm.VIEW_LOGS))])
        async def foo(): ...
    """
    from fastapi import Depends, HTTPException
    from app.web.deps import get_current_admin

    def _dep(admin: Admin = Depends(get_current_admin)) -> Admin:
        if not admin.has_perm(perm):
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm.value}")
        return admin
    return _dep
