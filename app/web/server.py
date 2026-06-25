"""FastAPI app factory + WebSocket for live dashboard stats.

Serves the built React WebUI from ``webui/dist`` if present (production)
and falls back to a "build the WebUI first" placeholder page.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.config import get_settings
from app.forwarder import is_paused
from app.models import (
    Admin, ChannelPair, ForwardCursor, HistoryEntry, LogEntry, session,
)
from app.web.auth import router as auth_router
from app.web.routes import (
    admins_router, channels_router, connections_router,
    dashboard_router, history_router, logs_router, settings_router,
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WEBUI_DIST = REPO_ROOT / "webui" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="tg-forwarder",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # ----- API routers -----
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(admins_router)
    app.include_router(channels_router)
    app.include_router(settings_router)
    app.include_router(logs_router)
    app.include_router(history_router)
    app.include_router(connections_router)

    # ----- WebSocket for live dashboard stats -----
    @app.websocket("/api/ws/dashboard")
    async def ws_dashboard(ws: WebSocket) -> None:
        await ws.accept()
        try:
            while True:
                payload = await _build_ws_payload()
                await ws.send_text(json.dumps(payload, default=str))
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            return
        except Exception:
            return

    # ----- Static assets (built React app) -----
    if WEBUI_DIST.exists():
        # serve assets/* directly
        assets_dir = WEBUI_DIST / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{path:path}")
        async def spa_fallback(path: str):
            # try to serve a real file first
            candidate = WEBUI_DIST / path
            if candidate.is_file():
                return FileResponse(str(candidate))
            # otherwise return index.html for client-side routing
            return FileResponse(str(WEBUI_DIST / "index.html"))
    else:
        @app.get("/{path:path}")
        async def placeholder(path: str):
            return HTMLResponse(_PLACEHOLDER_HTML, status_code=200)

    return app


async def _build_ws_payload() -> dict:
    now = datetime.utcnow()
    cutoff_1h = now - timedelta(hours=1)
    cutoff_24h = now - timedelta(hours=24)
    async with session() as sess:
        admins = (await sess.execute(select(func.count(Admin.id)))).scalar_one()
        pairs = (await sess.execute(select(func.count(ChannelPair.id)))).scalar_one()
        active = (await sess.execute(
            select(func.count(ChannelPair.id)).where(ChannelPair.enabled == True)
        )).scalar_one()
        total = (await sess.execute(select(func.count(HistoryEntry.id)))).scalar_one()
        h24 = (await sess.execute(
            select(func.count(HistoryEntry.id)).where(HistoryEntry.forwarded_at >= cutoff_24h)
        )).scalar_one()
        h1 = (await sess.execute(
            select(func.count(HistoryEntry.id)).where(HistoryEntry.forwarded_at >= cutoff_1h)
        )).scalar_one()
        cursors_q = await sess.execute(select(ForwardCursor))
        cursors = list(cursors_q.scalars())
        pairs_q = await sess.execute(select(ChannelPair))
        pair_rows = list(pairs_q.scalars())
    return {
        "ts": now.isoformat(),
        "paused": is_paused(),
        "admins": admins,
        "pairs": pairs,
        "active_pairs": active,
        "forwarded_total": total,
        "forwarded_24h": h24,
        "forwarded_1h": h1,
        "cursors": [
            {
                "pair_id": c.pair_id,
                "last_source_msg_id": c.last_source_msg_id,
                "backfill_complete": c.backfill_complete,
            }
            for c in cursors
        ],
        "pair_titles": {p.id: (p.source_title or p.source_id, p.dest_title or p.dest_id) for p in pair_rows},
    }


_PLACEHOLDER_HTML = """<!doctype html>
<html><head><title>tg-forwarder WebUI</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
.box{max-width:640px;padding:2rem;border:1px solid #334155;border-radius:12px;
background:#1e293b}
code{background:#0f172a;padding:2px 6px;border-radius:4px;color:#38bdf8}
.btn{display:inline-block;margin-top:1rem;padding:.6rem 1rem;background:#0ea5e9;color:#fff;
text-decoration:none;border-radius:6px;font-weight:600}
</style></head>
<body><div class="box">
<h1>tg-forwarder WebUI</h1>
<p>The React frontend has not been built yet. Run:</p>
<pre><code>cd webui &amp;&amp; npm install &amp;&amp; npm run build</code></pre>
<p>or use the installer:</p>
<pre><code>./install.sh --webui-only</code></pre>
<p>API docs are still available at <a href="/api/docs" style="color:#38bdf8">/api/docs</a>.</p>
</div></body></html>
"""
