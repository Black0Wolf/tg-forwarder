"""tg-forwarder — single-process entry point.

Starts:
  1. PostgreSQL connection pool + schema creation
  2. Telethon bot + userbot clients (interactive login on first run)
  3. Forwarder supervisor (one asyncio task per enabled channel pair)
  4. FastAPI WebUI (uvicorn, in-process)
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from contextlib import suppress
from pathlib import Path

import uvicorn
from loguru import logger

from app.admin_system import seed_super_admins
from app.bot_handlers import register_handlers
from app.config import get_settings
from app.forwarder import start_forwarder, stop_forwarder
from app.models import init_db, dispose_db
from app.telethon_client import (
    db_log, get_bot_client, get_user_client, stop_clients,
)
from app.web.server import create_app


# ----- logging setup -------------------------------------------------------
class DbSink:
    """Mirror loguru records into PostgreSQL (best-effort, non-blocking).

    Loguru calls sinks synchronously from whatever thread emitted the record.
    If we're on the asyncio event loop thread, schedule a fire-and-forget
    task; otherwise just drop the record (the file/stderr sinks still get it).
    """
    def __call__(self, message):
        record = message.record
        level = record["level"].name
        if level == "DEBUG":
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(db_log(level, record["message"], record["module"]))
        except RuntimeError:
            # no running loop — skip DB persistence
            pass


def setup_logging() -> None:
    Path("data").mkdir(exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <cyan>{module}</cyan> | {message}")
    logger.add("data/tg-forwarder.log", rotation="10 MB", retention="7 days", level="DEBUG")
    logger.add(DbSink(), level="INFO")


# ----- main coroutine ------------------------------------------------------
async def main() -> None:
    cfg = get_settings()
    setup_logging()
    logger.info("tg-forwarder starting up…")

    # 1. Database
    await init_db(cfg.db_url)
    logger.info("Database initialised.")
    await seed_super_admins()
    logger.info(f"Super-admins seeded: {cfg.super_admins}")

    # 2. Telethon clients
    bot = await get_bot_client()
    me = await bot.get_me()
    logger.info(f"Bot logged in as @{me.username} (id={me.id})")

    user = await get_user_client()
    ume = await user.get_me()
    logger.info(f"Userbot logged in as {ume.first_name} (id={ume.id})")

    # 3. Register bot handlers
    register_handlers(bot)

    # 4. Start forwarder supervisor
    await start_forwarder()
    logger.info("Forwarder supervisor running.")

    # 5. Start FastAPI in-process
    app = create_app()
    config = uvicorn.Config(
        app,
        host=cfg.web.host,
        port=cfg.web.port,
        log_level="warning",   # let loguru handle the formatting
        access_log=False,
    )
    server = uvicorn.Server(config)

    # 6. Run forever until Ctrl-C
    stop_event = asyncio.Event()

    def _stop(*_):
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)

    server_task = asyncio.create_task(server.serve())
    stop_waiter = asyncio.create_task(stop_event.wait())

    logger.info(f"WebUI listening on http://{cfg.web.host}:{cfg.web.port}")
    logger.info("Send /start to your bot in Telegram to open the config menu.")
    logger.info("Press Ctrl-C to stop.")

    try:
        await asyncio.wait({server_task, stop_waiter}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        logger.info("Shutting down…")
        await stop_forwarder()
        await server.shutdown()
        await stop_clients()
        await dispose_db()
        logger.info("Bye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
