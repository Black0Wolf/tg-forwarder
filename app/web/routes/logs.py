"""Logs API — recent log entries with filters."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.admin_system import require_perm_web
from app.models import LogEntry, Perm
from app.web.deps import get_current_admin

router = APIRouter(prefix="/api/logs", dependencies=[Depends(get_current_admin)])


@router.get("", dependencies=[Depends(require_perm_web(Perm.VIEW_LOGS))])
async def list_logs(
    level: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    from app.models import session
    async with session() as sess:
        q = select(LogEntry).order_by(LogEntry.id.desc()).limit(limit).offset(offset)
        if level:
            q = q.where(LogEntry.level == level.upper())
        rows = (await sess.execute(q)).scalars().all()
    return {
        "logs": [
            {
                "id": r.id,
                "level": r.level,
                "message": r.message,
                "module": r.module,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
        "offset": offset,
    }


@router.delete("", dependencies=[Depends(require_perm_web(Perm.CLEAR_LOGS))])
async def clear_logs() -> dict:
    from sqlalchemy import delete as sa_delete
    from app.models import session
    async with session() as sess:
        result = await sess.execute(sa_delete(LogEntry))
        await sess.commit()
    return {"ok": True, "deleted": result.rowcount or 0}
