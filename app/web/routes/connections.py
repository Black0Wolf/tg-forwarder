"""Connections API — recent WebUI + bot sessions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.admin_system import require_perm_web
from app.models import Connection, Perm, session
from app.web.deps import get_current_admin

router = APIRouter(prefix="/api/connections", dependencies=[Depends(get_current_admin)])


@router.get("")
async def list_connections(
    kind: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    async with session() as sess:
        q = select(Connection).order_by(Connection.id.desc()).limit(limit)
        if kind:
            q = q.where(Connection.kind == kind)
        rows = (await sess.execute(q)).scalars().all()
    return {
        "connections": [
            {
                "id": c.id,
                "kind": c.kind,
                "admin_id": c.admin_id,
                "ip": c.ip,
                "user_agent": c.user_agent,
                "detail": c.detail,
                "connected_at": c.connected_at.isoformat(),
            }
            for c in rows
        ],
        "count": len(rows),
    }
