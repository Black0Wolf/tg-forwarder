"""Admins API — list, add, remove, toggle permission."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.admin_system import (
    add_admin, admin_perms, list_admins, remove_admin, set_perm,
)
from app.models import ALL_PERMS, Admin, Perm, session
from app.web.deps import get_current_admin
from app.admin_system import require_perm_web

router = APIRouter(prefix="/api/admins")


class AddAdminIn(BaseModel):
    tg_user_id: int
    tg_username: str | None = None
    tg_first_name: str | None = None
    perms: list[str] = []


class TogglePermIn(BaseModel):
    perm: str
    enabled: bool


def _admin_to_dict(a: Admin, perms: dict[str, bool]) -> dict:
    return {
        "id": a.id,
        "tg_user_id": a.tg_user_id,
        "tg_username": a.tg_username,
        "tg_first_name": a.tg_first_name,
        "level": a.level,
        "is_super": a.is_super,
        "added_at": a.added_at.isoformat() if a.added_at else None,
        "perms": perms,
    }


@router.get("", dependencies=[Depends(get_current_admin)])
async def list_all() -> list[dict]:
    out = []
    for a in await list_admins():
        perms = await admin_perms(a.tg_user_id)
        out.append(_admin_to_dict(a, perms))
    return out


@router.get("/perms")
async def list_perms(_admin: Admin = Depends(get_current_admin)) -> dict:
    return {
        "perms": [
            {"value": p.value, "label": p.value.replace("_", " ").title()}
            for p in ALL_PERMS
        ]
    }


@router.post("", dependencies=[Depends(require_perm_web(Perm.MANAGE_ADMINS))])
async def add_one(body: AddAdminIn, current: Admin = Depends(get_current_admin)) -> dict:
    try:
        perms = [Perm(p) for p in body.perms]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        new_admin = await add_admin(
            body.tg_user_id,
            tg_username=body.tg_username,
            tg_first_name=body.tg_first_name,
            level=1,
            perms=perms,
            added_by=current.tg_user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _admin_to_dict(new_admin, await admin_perms(new_admin.tg_user_id))


@router.delete("/{tg_user_id}", dependencies=[Depends(require_perm_web(Perm.MANAGE_ADMINS))])
async def delete_one(tg_user_id: int) -> dict:
    try:
        ok = await remove_admin(tg_user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Admin not found")
    return {"ok": True}


@router.post("/{tg_user_id}/toggle", dependencies=[Depends(require_perm_web(Perm.MANAGE_ADMINS))])
async def toggle_perm(tg_user_id: int, body: TogglePermIn) -> dict:
    try:
        perm = Perm(body.perm)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unknown permission")
    await set_perm(tg_user_id, perm, body.enabled)
    return {"ok": True, "perms": await admin_perms(tg_user_id)}
