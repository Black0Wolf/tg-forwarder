"""History API — every successful forward (audit trail)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.admin_system import require_perm_web
from app.models import ChannelPair, HistoryEntry, Perm, session
from app.web.deps import get_current_admin

router = APIRouter(prefix="/api/history", dependencies=[Depends(get_current_admin)])


@router.get("", dependencies=[Depends(require_perm_web(Perm.VIEW_HISTORY))])
async def list_history(
    pair_id: int | None = Query(default=None),
    msg_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    async with session() as sess:
        q = select(HistoryEntry).order_by(HistoryEntry.id.desc()).limit(limit).offset(offset)
        if pair_id is not None:
            q = q.where(HistoryEntry.pair_id == pair_id)
        if msg_type:
            q = q.where(HistoryEntry.msg_type == msg_type)
        rows = (await sess.execute(q)).scalars().all()

        # total count for pagination
        cnt_q = select(func.count(HistoryEntry.id))
        if pair_id is not None:
            cnt_q = cnt_q.where(HistoryEntry.pair_id == pair_id)
        if msg_type:
            cnt_q = cnt_q.where(HistoryEntry.msg_type == msg_type)
        total = (await sess.execute(cnt_q)).scalar_one()

        # pair lookup map
        pairs_q = await sess.execute(select(ChannelPair))
        pair_titles = {p.id: (p.source_title or p.source_id, p.dest_title or p.dest_id) for p in pairs_q.scalars()}

    return {
        "history": [
            {
                "id": h.id,
                "pair_id": h.pair_id,
                "source_title": pair_titles.get(h.pair_id, ("?", "?"))[0],
                "dest_title": pair_titles.get(h.pair_id, ("?", "?"))[1],
                "source_msg_id": h.source_msg_id,
                "dest_msg_id": h.dest_msg_id,
                "msg_type": h.msg_type,
                "msg_preview": h.msg_preview,
                "forwarded_at": h.forwarded_at.isoformat(),
            }
            for h in rows
        ],
        "count": len(rows),
        "total": total,
        "offset": offset,
    }


@router.delete("", dependencies=[Depends(require_perm_web(Perm.CLEAR_LOGS))])
async def clear_history() -> dict:
    from sqlalchemy import delete as sa_delete
    async with session() as sess:
        result = await sess.execute(sa_delete(HistoryEntry))
        await sess.commit()
    return {"ok": True, "deleted": result.rowcount or 0}
