"""Dashboard stats — overall numbers + per-pair breakdown + recent activity."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.admin_system import require_perm_web
from app.config import get_settings
from app.forwarder import is_paused
from app.models import (
    Admin, ChannelPair, ForwardCursor, HistoryEntry, LogEntry, Perm,
    session,
)
from app.web.deps import get_current_admin

router = APIRouter(prefix="/api/dashboard", dependencies=[Depends(get_current_admin)])


@router.get("")
async def dashboard() -> dict:
    now = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_1h = now - timedelta(hours=1)
    cutoff_7d = now - timedelta(days=7)

    async with session() as sess:
        admins_count = (await sess.execute(select(func.count(Admin.id)))).scalar_one()
        pairs_count = (await sess.execute(select(func.count(ChannelPair.id)))).scalar_one()
        active_pairs = (await sess.execute(
            select(func.count(ChannelPair.id)).where(ChannelPair.enabled == True)
        )).scalar_one()
        forwarded_total = (await sess.execute(select(func.count(HistoryEntry.id)))).scalar_one()
        forwarded_24h = (await sess.execute(
            select(func.count(HistoryEntry.id)).where(HistoryEntry.forwarded_at >= cutoff_24h)
        )).scalar_one()
        forwarded_1h = (await sess.execute(
            select(func.count(HistoryEntry.id)).where(HistoryEntry.forwarded_at >= cutoff_1h)
        )).scalar_one()
        forwarded_7d = (await sess.execute(
            select(func.count(HistoryEntry.id)).where(HistoryEntry.forwarded_at >= cutoff_7d)
        )).scalar_one()

        # per-pair stats
        pair_rows = (await sess.execute(select(ChannelPair).order_by(ChannelPair.id))).scalars().all()
        pairs = []
        for p in pair_rows:
            cur_q = await sess.execute(select(ForwardCursor).where(ForwardCursor.pair_id == p.id))
            cur = cur_q.scalar_one_or_none()
            total_q = await sess.execute(
                select(func.count(HistoryEntry.id)).where(HistoryEntry.pair_id == p.id)
            )
            total = total_q.scalar_one()
            last_q = await sess.execute(
                select(HistoryEntry)
                .where(HistoryEntry.pair_id == p.id)
                .order_by(HistoryEntry.forwarded_at.desc())
                .limit(1)
            )
            last = last_q.scalar_one_or_none()
            pairs.append({
                "id": p.id,
                "name": p.name,
                "source_id": p.source_id,
                "source_title": p.source_title,
                "dest_id": p.dest_id,
                "dest_title": p.dest_title,
                "enabled": p.enabled,
                "last_source_msg_id": cur.last_source_msg_id if cur else 0,
                "backfill_complete": cur.backfill_complete if cur else False,
                "last_forwarded_at": (cur.last_forwarded_at.isoformat() if cur and cur.last_forwarded_at else None),
                "forwarded_total": total,
                "last_msg_type": last.msg_type if last else None,
                "last_msg_preview": last.msg_preview if last else None,
            })

        # recent activity (last 30 forwards)
        recent_q = await sess.execute(
            select(HistoryEntry)
            .order_by(HistoryEntry.forwarded_at.desc())
            .limit(30)
        )
        recent = [
            {
                "id": h.id,
                "pair_id": h.pair_id,
                "source_msg_id": h.source_msg_id,
                "dest_msg_id": h.dest_msg_id,
                "msg_type": h.msg_type,
                "msg_preview": h.msg_preview,
                "forwarded_at": h.forwarded_at.isoformat(),
            }
            for h in recent_q.scalars()
        ]

        # 24h sparkline: count per hour
        sparkline = []
        for h_offset in range(24, 0, -1):
            hour_start = now - timedelta(hours=h_offset)
            hour_end = now - timedelta(hours=h_offset - 1)
            cnt_q = await sess.execute(
                select(func.count(HistoryEntry.id)).where(
                    HistoryEntry.forwarded_at >= hour_start,
                    HistoryEntry.forwarded_at < hour_end,
                )
            )
            sparkline.append({
                "hour": hour_start.strftime("%H:00"),
                "count": cnt_q.scalar_one(),
            })

    return {
        "admins": admins_count,
        "pairs": pairs_count,
        "active_pairs": active_pairs,
        "forwarded_total": forwarded_total,
        "forwarded_24h": forwarded_24h,
        "forwarded_1h": forwarded_1h,
        "forwarded_7d": forwarded_7d,
        "paused": is_paused(),
        "forward_mode": "copy",
        "pairs_detail": pairs,
        "recent_activity": recent,
        "sparkline_24h": sparkline,
    }
