"""Telethon clients: bot + userbot.

The bot account handles admin commands and inline config menus.
The userbot account reads full channel history (including past messages
the bot account would never see) and lists the user's recent
chats/channels for the inline channel picker.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User
from telethon.errors import FloodWaitError

from app.config import get_settings
from app.models import session, LogEntry
from datetime import datetime

if TYPE_CHECKING:
    pass


# Singleton clients, lazily created
_bot_client: TelegramClient | None = None
_user_client: TelegramClient | None = None


def _make_bot_client() -> TelegramClient:
    cfg = get_settings()
    client = TelegramClient(
        "bot",               # session file: bot.session
        cfg.api_id,
        cfg.api_hash.get_secret_value(),
    )
    return client


def _make_user_client() -> TelegramClient:
    cfg = get_settings()
    client = TelegramClient(
        cfg.session_name,    # session file: userbot.session
        cfg.api_id,
        cfg.api_hash.get_secret_value(),
    )
    return client


async def get_bot_client() -> TelegramClient:
    """Lazily create and start the bot client."""
    global _bot_client
    if _bot_client is None:
        cfg = get_settings()
        _bot_client = _make_bot_client()
        await _bot_client.start(bot_token=cfg.bot_token.get_secret_value())
    return _bot_client


async def get_user_client() -> TelegramClient:
    """Lazily create and start the userbot client.

    On first run Telethon will prompt the console for the login code and
    2FA password if needed. After that the session file is reused.
    """
    global _user_client
    if _user_client is None:
        cfg = get_settings()
        _user_client = _make_user_client()
        await _user_client.start(phone=cfg.phone)
    return _user_client


async def stop_clients() -> None:
    global _bot_client, _user_client
    for c in (_bot_client, _user_client):
        if c is not None:
            await c.disconnect()
    _bot_client = None
    _user_client = None


# ---------------------------------------------------------------------------
#  Chat / channel listing helpers
# ---------------------------------------------------------------------------
async def list_recent_dialogs(limit: int = 15) -> list[dict[str, Any]]:
    """Return the user's ``limit`` most recent channels/groups (excluding
    private DMs). Used by the inline channel picker.

    Output: list of dicts ``{id, title, username, type}``.
    """
    client = await get_user_client()
    out: list[dict[str, Any]] = []
    async for d in client.iter_dialogs(limit=limit * 4):  # over-fetch, filter
        if d.is_user:
            continue
        ent = d.entity
        if isinstance(ent, (Channel, Chat, User)):
            out.append({
                "id": ent.id,
                "title": getattr(ent, "title", None) or getattr(ent, "first_name", "?"),
                "username": getattr(ent, "username", None),
                "type": "channel" if isinstance(ent, Channel) and getattr(ent, "megagroup", False) is False and getattr(ent, "broadcast", False) is True
                        else ("supergroup" if isinstance(ent, Channel) else "group"),
            })
        if len(out) >= limit:
            break
    return out


async def resolve_peer(value: str | int) -> dict[str, Any] | None:
    """Resolve a username / numeric id to ``{id, title, username, type}``."""
    client = await get_user_client()
    try:
        if isinstance(value, str) and value.lstrip("-").isdigit():
            value = int(value)
        ent = await client.get_entity(value)
    except Exception:
        return None
    return {
        "id": ent.id,
        "title": getattr(ent, "title", None) or getattr(ent, "first_name", "?"),
        "username": getattr(ent, "username", None),
        "type": "channel" if isinstance(ent, Channel) else ("group" if isinstance(ent, Chat) else "user"),
    }


async def get_chat_info(peer_id: int) -> dict[str, Any] | None:
    """Fetch title/username for a known chat id."""
    client = await get_user_client()
    try:
        ent = await client.get_entity(peer_id)
    except Exception:
        return None
    return {
        "id": ent.id,
        "title": getattr(ent, "title", None) or getattr(ent, "first_name", "?"),
        "username": getattr(ent, "username", None),
        "type": "channel" if isinstance(ent, Channel) else ("group" if isinstance(ent, Chat) else "user"),
    }


async def db_log(level: str, message: str, module: str | None = None) -> None:
    """Persist a log entry to PostgreSQL (for WebUI Logs tab)."""
    try:
        async with session() as sess:
            sess.add(LogEntry(level=level, message=message, module=module))
            await sess.commit()
    except Exception:
        # Never let logging failure crash the bot
        pass
