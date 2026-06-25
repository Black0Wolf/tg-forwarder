"""Settings API — pause/resume, backfill, runtime config values."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.admin_system import require_perm_web
from app.config import get_settings
from app.forwarder import is_paused, set_paused, trigger_backfill
from app.models import ChannelPair, Perm, Setting, session
from app.web.deps import get_current_admin

router = APIRouter(prefix="/api/settings", dependencies=[Depends(get_current_admin)])


@router.get("")
async def get_settings_api() -> dict:
    cfg = get_settings()
    return {
        "paused": is_paused(),
        "forward_mode": cfg.forwarder.mode,
        "initial_backfill": cfg.forwarder.initial_backfill,
        "backfill_batch_size": cfg.forwarder.backfill_batch_size,
        "backfill_delay_ms": cfg.forwarder.backfill_delay_ms,
        "live_poll_interval_s": cfg.forwarder.live_poll_interval_s,
        "web_port": cfg.web.port,
        "web_base_url": cfg.web.base_url,
    }


class PauseIn(BaseModel):
    paused: bool


@router.post("/pause", dependencies=[Depends(require_perm_web(Perm.PAUSE_RESUME))])
async def set_pause(body: PauseIn) -> dict:
    await set_paused(body.paused)
    return {"ok": True, "paused": body.paused}


class BackfillIn(BaseModel):
    pair_id: int | None = None
    from_msg_id: int = 0


@router.post("/backfill", dependencies=[Depends(require_perm_web(Perm.BACKFILL))])
async def backfill(body: BackfillIn) -> dict:
    if body.pair_id is None:
        # all pairs
        async with session() as sess:
            q = await sess.execute(select(ChannelPair))
            ids = [p.id for p in q.scalars()]
        for pid in ids:
            await trigger_backfill(pid, body.from_msg_id)
        return {"ok": True, "triggered": len(ids), "pair_ids": ids}
    await trigger_backfill(body.pair_id, body.from_msg_id)
    return {"ok": True, "triggered": 1, "pair_ids": [body.pair_id]}
