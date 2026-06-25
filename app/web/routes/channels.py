"""Channels API — list/create/update/delete pairs + resolve IDs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.admin_system import require_perm_web
from app.models import ChannelPair, ForwardCursor, Perm, session
from app.telethon_client import list_recent_dialogs, resolve_peer
from app.web.deps import get_current_admin

router = APIRouter(prefix="/api/channels")


class PairIn(BaseModel):
    source: str           # id or @username
    dest: str
    name: str = "default"
    enabled: bool = True


class PairUpdate(BaseModel):
    source: str | None = None
    dest: str | None = None
    name: str | None = None
    enabled: bool | None = None


class ResolveIn(BaseModel):
    value: str


@router.get("/recent", dependencies=[Depends(get_current_admin)])
async def recent() -> dict:
    """Return the userbot's 15 most recent channels/groups."""
    dialogs = await list_recent_dialogs(limit=15)
    return {"dialogs": dialogs}


@router.post("/resolve", dependencies=[Depends(get_current_admin)])
async def resolve(body: ResolveIn) -> dict:
    info = await resolve_peer(body.value)
    if info is None:
        raise HTTPException(status_code=404, detail="Could not resolve that channel/username")
    return info


@router.get("", dependencies=[Depends(get_current_admin)])
async def list_pairs() -> list[dict]:
    async with session() as sess:
        q = await sess.execute(select(ChannelPair).order_by(ChannelPair.id))
        pairs = list(q.scalars())
        out = []
        for p in pairs:
            cur_q = await sess.execute(select(ForwardCursor).where(ForwardCursor.pair_id == p.id))
            cur = cur_q.scalar_one_or_none()
            out.append({
                "id": p.id,
                "name": p.name,
                "source_id": p.source_id,
                "source_title": p.source_title,
                "source_username": p.source_username,
                "dest_id": p.dest_id,
                "dest_title": p.dest_title,
                "dest_username": p.dest_username,
                "enabled": p.enabled,
                "last_source_msg_id": cur.last_source_msg_id if cur else 0,
                "backfill_complete": cur.backfill_complete if cur else False,
                "last_forwarded_at": (cur.last_forwarded_at.isoformat() if cur and cur.last_forwarded_at else None),
            })
    return out


@router.post("", dependencies=[Depends(require_perm_web(Perm.EDIT_CHANNELS))])
async def create_pair(body: PairIn) -> dict:
    src = await resolve_peer(body.source)
    dst = await resolve_peer(body.dest)
    if src is None:
        raise HTTPException(status_code=400, detail=f"Cannot resolve source '{body.source}'")
    if dst is None:
        raise HTTPException(status_code=400, detail=f"Cannot resolve destination '{body.dest}'")
    async with session() as sess:
        p = ChannelPair(
            name=body.name,
            source_id=src["id"],
            source_title=src["title"],
            source_username=src.get("username"),
            dest_id=dst["id"],
            dest_title=dst["title"],
            dest_username=dst.get("username"),
            enabled=body.enabled,
        )
        sess.add(p)
        await sess.commit()
        await sess.refresh(p)
        return {
            "id": p.id,
            "name": p.name,
            "source_id": p.source_id,
            "source_title": p.source_title,
            "dest_id": p.dest_id,
            "dest_title": p.dest_title,
            "enabled": p.enabled,
        }


@router.patch("/{pair_id}", dependencies=[Depends(require_perm_web(Perm.EDIT_CHANNELS))])
async def update_pair(pair_id: int, body: PairUpdate) -> dict:
    async with session() as sess:
        p = await sess.get(ChannelPair, pair_id)
        if p is None:
            raise HTTPException(status_code=404, detail="Pair not found")
        if body.source is not None:
            info = await resolve_peer(body.source)
            if info is None:
                raise HTTPException(status_code=400, detail="Cannot resolve source")
            p.source_id = info["id"]
            p.source_title = info["title"]
            p.source_username = info.get("username")
        if body.dest is not None:
            info = await resolve_peer(body.dest)
            if info is None:
                raise HTTPException(status_code=400, detail="Cannot resolve destination")
            p.dest_id = info["id"]
            p.dest_title = info["title"]
            p.dest_username = info.get("username")
        if body.name is not None:
            p.name = body.name
        if body.enabled is not None:
            p.enabled = body.enabled
        await sess.commit()
        await sess.refresh(p)
    return {
        "id": p.id, "name": p.name,
        "source_id": p.source_id, "source_title": p.source_title,
        "dest_id": p.dest_id, "dest_title": p.dest_title,
        "enabled": p.enabled,
    }


@router.delete("/{pair_id}", dependencies=[Depends(require_perm_web(Perm.EDIT_CHANNELS))])
async def delete_pair(pair_id: int) -> dict:
    async with session() as sess:
        p = await sess.get(ChannelPair, pair_id)
        if p is None:
            raise HTTPException(status_code=404, detail="Pair not found")
        await sess.delete(p)
        await sess.commit()
    return {"ok": True}
