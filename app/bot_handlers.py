"""Telegram bot command + inline button handlers.

Glass-button inline menus are implemented using Telethon's
``InlineBuilder`` / ``button.inline`` with a callback-data router. Each
menu screen has a route prefix in the callback data so we can dispatch
without bloating one giant if/elif chain.
"""
from __future__ import annotations

import asyncio
import html
import json
from typing import Any

from sqlalchemy import select
from telethon import Button, events
from telethon.tl.custom import InlineBuilder

from app.admin_system import (
    add_admin, admin_perms, get_admin, list_admins, remove_admin,
    require_perm, seed_super_admins, set_perm,
)
from app.config import get_settings
from app.forwarder import is_paused, set_paused, trigger_backfill
from app.models import (
    Admin, ALL_PERMS, ChannelPair, ForwardCursor, HistoryEntry, LogEntry,
    Perm, session,
)
from app.telethon_client import (
    db_log, get_bot_client, get_user_client, list_recent_dialogs,
    resolve_peer,
)


# Router: maps callback data prefix -> handler
_callbacks: dict[str, Any] = {}


def cb_route(prefix: str):
    def deco(fn):
        _callbacks[prefix] = fn
        return fn
    return deco


# ---------------------------------------------------------------------------
#  Helpers for building keyboards
# ---------------------------------------------------------------------------
def _glass_button(text: str, data: str) -> Button:
    """A 'glassy' button — Telethon inline buttons are uniformly styled;
    we keep labels short and prefix them with an icon-like glyph to give
    the menu a clean, minimal look."""
    return Button.inline(text, data=data)


def _main_menu_kb():
    return [
        [_glass_button("📡 Channels", "menu:channels")],
        [_glass_button("👮 Admins", "menu:admins")],
        [_glass_button("⚙️ Settings", "menu:settings")],
        [_glass_button("📊 Stats", "menu:stats")],
        [_glass_button("⏸ Pause" if not is_paused() else "▶ Resume", "menu:toggle_pause")],
    ]


# ---------------------------------------------------------------------------
#  Commands
# ---------------------------------------------------------------------------
async def cmd_start(event, admin: Admin):
    await event.reply(
        f"👋 **tg-forwarder control panel**\n\n"
        f"Welcome, **{admin.tg_first_name or admin.tg_username or admin.tg_user_id}**.\n"
        f"Level: **{'super-admin' if admin.is_super else 'admin'}**\n\n"
        f"Tap a button below to manage the bot.",
        buttons=_main_menu_kb(),
        link_preview=False,
    )


async def cmd_help(event, admin: Admin):
    text = (
        "**tg-forwarder** — commands\n\n"
        "/start — open the config menu\n"
        "/help  — this message\n"
        "/stats — quick stats\n"
        "/logs  — recent log entries\n"
        "/pause — pause the forwarder\n"
        "/resume — resume the forwarder\n"
        "/addadmin <user_id> — add an admin (requires manage_admins)\n"
        "/deladmin <user_id> — remove an admin\n"
        "/perms <user_id> — show permissions for an admin\n"
        "/id    — show your Telegram user ID\n"
    )
    await event.reply(text, link_preview=False)


async def cmd_id(event, admin: Admin):
    await event.reply(f"Your Telegram user ID: `{event.sender_id}`")


async def cmd_stats(event, admin: Admin):
    s = await _stats_payload()
    text = (
        "**📊 Stats**\n\n"
        f"👥 Admins: **{s['admins']}**\n"
        f"🔗 Pairs: **{s['pairs']}** (active: {s['active_pairs']})\n"
        f"✅ Forwarded: **{s['forwarded_total']}**\n"
        f"📝 Last 24h: **{s['forwarded_24h']}**\n"
        f"🟢 State: **{'paused' if is_paused() else 'running'}**\n"
    )
    await event.reply(text, link_preview=False)


async def cmd_logs(event, admin: Admin):
    async with session() as sess:
        q = await sess.execute(
            select(LogEntry).order_by(LogEntry.id.desc()).limit(15)
        )
        rows = list(q.scalars())
    if not rows:
        await event.reply("_No log entries yet._")
        return
    text = "**Recent logs:**\n\n"
    for r in rows:
        text += f"`{r.created_at:%Y-%m-%d %H:%M:%S}` [{r.level}] {r.message}\n"
    await event.reply(text, link_preview=False)


async def cmd_pause(event, admin: Admin):
    await set_paused(True)
    await event.reply("⏸ Forwarder paused.")


async def cmd_resume(event, admin: Admin):
    await set_paused(False)
    await event.reply("▶ Forwarder resumed.")


async def cmd_addadmin(event, admin: Admin):
    parts = event.raw_text.split()
    if len(parts) < 2:
        await event.reply("Usage: `/addadmin <user_id>`")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await event.reply("user_id must be a number.")
        return
    try:
        new_admin = await add_admin(uid, added_by=admin.tg_user_id)
    except ValueError as e:
        await event.reply(str(e))
        return
    await event.reply(f"✅ Added admin `{uid}` (id=#{new_admin.id}). Use /perms to set permissions.")


async def cmd_deladmin(event, admin: Admin):
    parts = event.raw_text.split()
    if len(parts) < 2:
        await event.reply("Usage: `/deladmin <user_id>`")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await event.reply("user_id must be a number.")
        return
    try:
        ok = await remove_admin(uid)
    except ValueError as e:
        await event.reply(str(e))
        return
    await event.reply("✅ Removed." if ok else "Admin not found.")


async def cmd_perms(event, admin: Admin):
    parts = event.raw_text.split()
    if len(parts) < 2:
        await event.reply("Usage: `/perms <user_id>`")
        return
    try:
        uid = int(parts[1])
    except ValueError:
        await event.reply("user_id must be a number.")
        return
    perms = await admin_perms(uid)
    text = f"**Permissions for `{uid}`:**\n\n"
    for p in ALL_PERMS:
        text += f"{'✅' if perms[p.value] else '❌'}  `{p.value}`\n"
    await event.reply(text, link_preview=False)


# ---------------------------------------------------------------------------
#  Inline menu: channels
# ---------------------------------------------------------------------------
@cb_route("menu:channels")
async def _menu_channels(event):
    async with session() as sess:
        q = await sess.execute(select(ChannelPair).order_by(ChannelPair.id))
        pairs = list(q.scalars())
    if not pairs:
        text = "No channel pairs yet. Tap **Add pair** to create one."
    else:
        text = "**Channel pairs:**\n\n"
        for p in pairs:
            text += f"#{p.id} `{p.source_title or p.source_id}` → `{p.dest_title or p.dest_id}` {'🟢' if p.enabled else '🔴'}\n"
    buttons = [
        [_glass_button(f"#{p.id} {p.source_title or p.source_id}", f"pair:view:{p.id}") for p in pairs[:5]],
        [_glass_button("➕ Add pair", "pair:new:src")],
        [_glass_button("🔙 Back", "menu:root")],
    ]
    await event.edit(text, buttons=buttons, link_preview=False)


@cb_route("pair:view")
async def _pair_view(event, pair_id: int):
    async with session() as sess:
        p = await sess.get(ChannelPair, pair_id)
        if p is None:
            await event.answer("Pair not found", alert=True)
            return
        cur_q = await sess.execute(select(ForwardCursor).where(ForwardCursor.pair_id == pair_id))
        cur = cur_q.scalar_one_or_none()
    cursor_text = "no cursor"
    if cur:
        cursor_text = f"last src msg: **{cur.last_source_msg_id}**, backfill complete: {cur.backfill_complete}"
    text = (
        f"**Pair #{p.id}**\n\n"
        f"Source: `{p.source_title or p.source_id}` ({p.source_username or '—'})\n"
        f"Destination: `{p.dest_title or p.dest_id}` ({p.dest_username or '—'})\n"
        f"Enabled: {'yes' if p.enabled else 'no'}\n"
        f"Cursor: {cursor_text}\n"
    )
    buttons = [
        [_glass_button("🔄 Change source", f"pair:new:src:{p.id}")],
        [_glass_button("🔄 Change destination", f"pair:new:dst:{p.id}")],
        [_glass_button("♻️ Backfill from start", f"pair:backfill:{p.id}")],
        [_glass_button("🟢 Disable" if p.enabled else "🔴 Enable", f"pair:toggle:{p.id}")],
        [_glass_button("🗑 Delete", f"pair:delete:{p.id}")],
        [_glass_button("🔙 Back", "menu:channels")],
    ]
    await event.edit(text, buttons=buttons, link_preview=False)


@cb_route("pair:new:src")
async def _pair_new_src(event, pair_id: int | None = None):
    """Show recent 15 dialogs as candidate sources."""
    try:
        dialogs = await list_recent_dialogs(limit=15)
    except Exception as e:
        await event.answer(f"Error: {e}", alert=True)
        return
    if not dialogs:
        await event.answer("No channels/groups found in your userbot account.", alert=True)
        return
    text = "**Pick a source channel** (your 15 most recent):"
    buttons = []
    for d in dialogs:
        label = f"{d['title']} ({d['type']})"
        if len(label) > 60:
            label = label[:57] + "..."
        buttons.append([_glass_button(label, f"pair:pick:src:{d['id']}:{pair_id or 0}")])
    buttons.append([_glass_button("⌨️ Enter ID/Username manually", f"pair:manual:src:{pair_id or 0}")])
    buttons.append([_glass_button("🔙 Back", "menu:channels")])
    await event.edit(text, buttons=buttons, link_preview=False)


@cb_route("pair:pick:src")
async def _pair_pick_src(event, source_id: int, pair_id: int):
    info = await resolve_peer(source_id)
    if info is None:
        await event.answer("Could not resolve that channel.", alert=True)
        return
    # If pair_id == 0 we are creating a new pair; stash source and move to dst
    state_key = f"pair:{event.query_id}:src"
    # We can't easily stash per-user state server-side without a session;
    # instead, encode source id into the next step's callback data.
    if pair_id == 0:
        text = f"Source picked: **{info['title']}** (`{info['id']}`)\nNow pick the destination."
        buttons = [
            [_glass_button("📡 Pick destination", f"pair:new:dst:0:{source_id}")],
            [_glass_button("⌨️ Enter destination manually", f"pair:manual:dst:0:{source_id}")],
            [_glass_button("🔙 Back", "pair:new:src")],
        ]
        await event.edit(text, buttons=buttons, link_preview=False)
    else:
        # updating existing pair source
        async with session() as sess:
            p = await sess.get(ChannelPair, pair_id)
            if p is None:
                await event.answer("Pair not found", alert=True)
                return
            p.source_id = info["id"]
            p.source_title = info["title"]
            p.source_username = info.get("username")
            await sess.commit()
        await event.answer("Source updated ✅")
        await _pair_view(event, pair_id)


@cb_route("pair:new:dst")
async def _pair_new_dst(event, pair_id: int, source_id: int):
    """Show recent 15 dialogs as candidate destinations."""
    try:
        dialogs = await list_recent_dialogs(limit=15)
    except Exception as e:
        await event.answer(f"Error: {e}", alert=True)
        return
    text = "**Pick a destination channel** (your 15 most recent):"
    buttons = []
    for d in dialogs:
        label = f"{d['title']} ({d['type']})"
        if len(label) > 60:
            label = label[:57] + "..."
        buttons.append([_glass_button(label, f"pair:pick:dst:{d['id']}:{source_id}:{pair_id}")])
    buttons.append([_glass_button("⌨️ Enter ID/Username manually", f"pair:manual:dst:{pair_id}:{source_id}")])
    buttons.append([_glass_button("🔙 Back", "pair:new:src")])
    await event.edit(text, buttons=buttons, link_preview=False)


@cb_route("pair:pick:dst")
async def _pair_pick_dst(event, dest_id: int, source_id: int, pair_id: int):
    info = await resolve_peer(dest_id)
    if info is None:
        await event.answer("Could not resolve that channel.", alert=True)
        return
    if pair_id == 0:
        async with session() as sess:
            p = ChannelPair(
                source_id=source_id,
                source_title=None,
                dest_id=info["id"],
                dest_title=info["title"],
                dest_username=info.get("username"),
                enabled=True,
            )
            src_info = await resolve_peer(source_id)
            if src_info:
                p.source_title = src_info["title"]
                p.source_username = src_info.get("username")
            sess.add(p)
            await sess.commit()
            await sess.refresh(p)
            new_id = p.id
        await event.answer("Pair created ✅")
        await _pair_view(event, new_id)
    else:
        async with session() as sess:
            p = await sess.get(ChannelPair, pair_id)
            if p is None:
                await event.answer("Pair not found", alert=True)
                return
            p.dest_id = info["id"]
            p.dest_title = info["title"]
            p.dest_username = info.get("username")
            await sess.commit()
        await event.answer("Destination updated ✅")
        await _pair_view(event, pair_id)


@cb_route("pair:manual:src")
async def _pair_manual_src(event, pair_id: int):
    """Tell user we'll wait for their next message as the ID/username."""
    await event.edit(
        f"⌨️ **Manual source entry**\n\n"
        f"Reply to this message with the channel ID or @username.\n\n"
        f"(I'll pick up the next message you send me as the source for pair #{pair_id or 'new'})",
        buttons=[[_glass_button("🔙 Cancel", "menu:channels")]],
        link_preview=False,
    )
    # Stash expectation in a per-user state store
    _awaiting_manual[event.sender_id] = {
        "kind": "src",
        "pair_id": pair_id,
        "expires": asyncio.get_event_loop().time() + 120,
    }


@cb_route("pair:manual:dst")
async def _pair_manual_dst(event, pair_id: int, source_id: int):
    await event.edit(
        f"⌨️ **Manual destination entry**\n\n"
        f"Reply to this message with the channel ID or @username.\n\n"
        f"(pair #{pair_id or 'new'}, source_id={source_id})",
        buttons=[[_glass_button("🔙 Cancel", "menu:channels")]],
        link_preview=False,
    )
    _awaiting_manual[event.sender_id] = {
        "kind": "dst",
        "pair_id": pair_id,
        "source_id": source_id,
        "expires": asyncio.get_event_loop().time() + 120,
    }


# In-memory manual-entry state, keyed on sender (Telegram user id).
# Each entry expires after 120 s; safe for multi-admin scenarios.
_awaiting_manual: dict[int, dict[str, Any]] = {}


@cb_route("pair:toggle")
async def _pair_toggle(event, pair_id: int):
    async with session() as sess:
        p = await sess.get(ChannelPair, pair_id)
        if p is None:
            await event.answer("Pair not found", alert=True)
            return
        p.enabled = not p.enabled
        await sess.commit()
    await event.answer("Toggled ✅")
    await _pair_view(event, pair_id)


@cb_route("pair:backfill")
async def _pair_backfill(event, pair_id: int):
    await trigger_backfill(pair_id, from_msg_id=0)
    await event.answer("Backfill triggered from start ✅")


@cb_route("pair:delete")
async def _pair_delete(event, pair_id: int):
    async with session() as sess:
        p = await sess.get(ChannelPair, pair_id)
        if p is None:
            await event.answer("Pair not found", alert=True)
            return
        await sess.delete(p)
        await sess.commit()
    await event.answer("Deleted ✅")
    await _menu_channels(event)


# ---------------------------------------------------------------------------
#  Inline menu: admins
# ---------------------------------------------------------------------------
@cb_route("menu:admins")
async def _menu_admins(event):
    admins = await list_admins()
    text = "**Admins:**\n\n"
    for a in admins:
        text += f"{'👑' if a.is_super else '👤'} `{a.tg_user_id}` — {a.tg_username or a.tg_first_name or '?'} (level {a.level})\n"
    buttons = []
    for a in admins[:10]:
        buttons.append([_glass_button(f"{'👑' if a.is_super else '👤'} {a.tg_user_id}", f"admin:view:{a.tg_user_id}")])
    buttons.append([_glass_button("➕ Add admin (via /addadmin)", "menu:root")])
    buttons.append([_glass_button("🔙 Back", "menu:root")])
    await event.edit(text, buttons=buttons, link_preview=False)


@cb_route("admin:view")
async def _admin_view(event, tg_user_id: int):
    perms = await admin_perms(tg_user_id)
    text = f"**Permissions for `{tg_user_id}`:**\n\n"
    for p in ALL_PERMS:
        text += f"{'✅' if perms[p.value] else '❌'}  `{p.value}`\n"
    buttons = []
    # one toggle button per permission
    for p in ALL_PERMS:
        on = perms[p.value]
        buttons.append([_glass_button(f"{'✅' if on else '❌'} {p.value}", f"admin:toggle:{tg_user_id}:{p.value}")])
    buttons.append([_glass_button("🔙 Back", "menu:admins")])
    await event.edit(text, buttons=buttons, link_preview=False)


@cb_route("admin:toggle")
async def _admin_toggle(event, tg_user_id: int, perm_value: str):
    try:
        perm = Perm(perm_value)
    except ValueError:
        await event.answer("Unknown permission", alert=True)
        return
    perms = await admin_perms(tg_user_id)
    await set_perm(tg_user_id, perm, not perms[perm_value])
    await event.answer("Toggled ✅")
    await _admin_view(event, tg_user_id)


# ---------------------------------------------------------------------------
#  Inline menu: settings / stats / pause
# ---------------------------------------------------------------------------
@cb_route("menu:settings")
async def _menu_settings(event):
    text = (
        "**Settings:**\n\n"
        f"• Pause state: **{'paused' if is_paused() else 'running'}**\n"
        "• Forward mode: **copy (no forward tag)**\n"
        f"• Super-admins: {len(get_settings().super_admins)}\n\n"
        "WebUI is available at the URL shown in your terminal / config.yaml."
    )
    buttons = [
        [_glass_button("⏸ Pause" if not is_paused() else "▶ Resume", "menu:toggle_pause")],
        [_glass_button("♻️ Trigger full backfill (all pairs)", "menu:backfill_all")],
        [_glass_button("🔙 Back", "menu:root")],
    ]
    await event.edit(text, buttons=buttons, link_preview=False)


@cb_route("menu:toggle_pause")
async def _menu_toggle_pause(event):
    await set_paused(not is_paused())
    await event.answer("Toggled ✅")
    await _menu_settings(event)


@cb_route("menu:backfill_all")
async def _menu_backfill_all(event):
    async with session() as sess:
        q = await sess.execute(select(ChannelPair))
        pairs = list(q.scalars())
    for p in pairs:
        await trigger_backfill(p.id, 0)
    await event.answer(f"Backfill triggered on {len(pairs)} pairs ✅")


@cb_route("menu:stats")
async def _menu_stats(event):
    s = await _stats_payload()
    text = (
        "**📊 Stats**\n\n"
        f"👥 Admins: **{s['admins']}**\n"
        f"🔗 Pairs: **{s['pairs']}** (active: {s['active_pairs']})\n"
        f"✅ Forwarded total: **{s['forwarded_total']}**\n"
        f"📝 Forwarded (24h): **{s['forwarded_24h']}**\n"
        f"🟢 State: **{'paused' if is_paused() else 'running'}**\n"
    )
    buttons = [[_glass_button("🔙 Back", "menu:root")]]
    await event.edit(text, buttons=buttons, link_preview=False)


@cb_route("menu:root")
async def _menu_root(event):
    await event.edit(
        "**tg-forwarder control panel**\n\nTap a button to begin.",
        buttons=_main_menu_kb(),
        link_preview=False,
    )


# ---------------------------------------------------------------------------
#  Stats payload (shared with WebUI)
# ---------------------------------------------------------------------------
async def _stats_payload() -> dict[str, Any]:
    from datetime import datetime, timedelta
    async with session() as sess:
        admins_q = await sess.execute(select(Admin))
        admins = list(admins_q.scalars())
        pairs_q = await sess.execute(select(ChannelPair))
        pairs = list(pairs_q.scalars())
        cursors_q = await sess.execute(select(ForwardCursor))
        cursors = list(cursors_q.scalars())
        hist_q = await sess.execute(select(HistoryEntry))
        hist = list(hist_q.scalars())
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=24)
        hist_24_q = await sess.execute(
            select(HistoryEntry).where(HistoryEntry.forwarded_at >= cutoff)
        )
        hist_24 = list(hist_24_q.scalars())
    return {
        "admins": len(admins),
        "pairs": len(pairs),
        "active_pairs": sum(1 for p in pairs if p.enabled),
        "forwarded_total": len(hist),
        "forwarded_24h": len(hist_24),
        "cursors": [
            {
                "pair_id": c.pair_id,
                "last_source_msg_id": c.last_source_msg_id,
                "last_dest_msg_id": c.last_dest_msg_id,
                "backfill_complete": c.backfill_complete,
                "last_forwarded_at": c.last_forwarded_at.isoformat() if c.last_forwarded_at else None,
            }
            for c in cursors
        ],
    }


# ---------------------------------------------------------------------------
#  Register handlers
# ---------------------------------------------------------------------------
async def register_handlers(client):
    """Wire every command + callback into the bot client."""

    @client.on(events.NewMessage(pattern=r"^/start"))
    async def _h_start(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            await event.reply("⛔ You are not an admin. Ask a super-admin to add you via /addadmin.")
            return
        await cmd_start(event, admin)

    @client.on(events.NewMessage(pattern=r"^/help"))
    async def _h_help(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            return
        await cmd_help(event, admin)

    @client.on(events.NewMessage(pattern=r"^/id"))
    async def _h_id(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            return
        await cmd_id(event, admin)

    @client.on(events.NewMessage(pattern=r"^/stats"))
    async def _h_stats(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            return
        if not admin.has_perm(Perm.VIEW_HISTORY):
            await event.reply("⛔ Missing permission: view_history")
            return
        await cmd_stats(event, admin)

    @client.on(events.NewMessage(pattern=r"^/logs"))
    async def _h_logs(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            return
        if not admin.has_perm(Perm.VIEW_LOGS):
            await event.reply("⛔ Missing permission: view_logs")
            return
        await cmd_logs(event, admin)

    @client.on(events.NewMessage(pattern=r"^/pause"))
    async def _h_pause(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            return
        if not admin.has_perm(Perm.PAUSE_RESUME):
            await event.reply("⛔ Missing permission: pause_resume")
            return
        await cmd_pause(event, admin)

    @client.on(events.NewMessage(pattern=r"^/resume"))
    async def _h_resume(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            return
        if not admin.has_perm(Perm.PAUSE_RESUME):
            await event.reply("⛔ Missing permission: pause_resume")
            return
        await cmd_resume(event, admin)

    @client.on(events.NewMessage(pattern=r"^/addadmin"))
    async def _h_addadmin(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            return
        if not admin.has_perm(Perm.MANAGE_ADMINS):
            await event.reply("⛔ Missing permission: manage_admins")
            return
        await cmd_addadmin(event, admin)

    @client.on(events.NewMessage(pattern=r"^/deladmin"))
    async def _h_deladmin(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            return
        if not admin.has_perm(Perm.MANAGE_ADMINS):
            await event.reply("⛔ Missing permission: manage_admins")
            return
        await cmd_deladmin(event, admin)

    @client.on(events.NewMessage(pattern=r"^/perms"))
    async def _h_perms(event):
        admin = await get_admin(event.sender_id)
        if admin is None:
            return
        if not admin.has_perm(Perm.MANAGE_ADMINS):
            await event.reply("⛔ Missing permission: manage_admins")
            return
        await cmd_perms(event, admin)

    # ----- callback router -----
    @client.on(events.CallbackQuery())
    async def _h_callback(event):
        # Permission gate: must be an admin
        admin = await get_admin(event.sender_id)
        if admin is None:
            await event.answer("Not an admin", alert=True)
            return
        data = event.data.decode("utf-8") if isinstance(event.data, bytes) else event.data
        # find longest matching prefix
        for prefix in sorted(_callbacks.keys(), key=len, reverse=True):
            if data.startswith(prefix):
                rest = data[len(prefix):].lstrip(":")
                args = [a for a in rest.split(":") if a]
                handler = _callbacks[prefix]
                try:
                    # Coerce numeric args
                    coerced = []
                    for a in args:
                        try:
                            coerced.append(int(a))
                        except ValueError:
                            coerced.append(a)
                    # If handler takes a single int (pair id), pass that
                    import inspect
                    sig = inspect.signature(handler)
                    n_params = len([p for p in sig.parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)])
                    if n_params == 1 and len(coerced) == 1:
                        await handler(event, coerced[0])
                    else:
                        await handler(event, *coerced)
                except Exception as e:
                    await db_log("ERROR", f"Callback {data} failed: {e}", module="bot")
                    await event.answer(f"Error: {e}", alert=True)
                return
        await event.answer("Unknown menu action", alert=True)

    # ----- manual-entry message catcher -----
    @client.on(events.NewMessage())
    async def _h_manual_catch(event):
        # Skip command messages
        if event.raw_text.startswith("/"):
            return
        sender_id = event.sender_id
        state = _awaiting_manual.get(sender_id)
        if state is None:
            return
        now = asyncio.get_event_loop().time()
        if state["expires"] < now:
            del _awaiting_manual[sender_id]
            return
        try:
            kind = state["kind"]
            text = event.raw_text.strip()
            info = await resolve_peer(text)
            if info is None:
                await event.reply(f"❌ Could not resolve `{text}`. Try again or send /cancel.")
                return
            if kind == "src":
                pair_id = state["pair_id"]
                if pair_id == 0:
                    # New pair — go straight to destination picker
                    await event.reply(f"✅ Source: **{info['title']}** (`{info['id']}`). Now pick the destination.")
                    bot = await get_bot_client()
                    await bot.send_message(
                        event.chat_id,
                        "**Pick destination** (your 15 most recent):",
                        buttons=await _build_dst_picker(0, info["id"]),
                        link_preview=False,
                    )
                else:
                    async with session() as sess:
                        p = await sess.get(ChannelPair, pair_id)
                        if p:
                            p.source_id = info["id"]
                            p.source_title = info["title"]
                            p.source_username = info.get("username")
                            await sess.commit()
                    await event.reply(f"✅ Source updated to **{info['title']}** (`{info['id']}`).")
            elif kind == "dst":
                pair_id = state["pair_id"]
                source_id = state["source_id"]
                if pair_id == 0:
                    src_info = await resolve_peer(source_id)
                    async with session() as sess:
                        p = ChannelPair(
                            source_id=source_id,
                            source_title=src_info["title"] if src_info else None,
                            source_username=src_info.get("username") if src_info else None,
                            dest_id=info["id"],
                            dest_title=info["title"],
                            dest_username=info.get("username"),
                            enabled=True,
                        )
                        sess.add(p)
                        await sess.commit()
                        await sess.refresh(p)
                        new_id = p.id
                    await event.reply(f"✅ Pair #{new_id} created.")
                else:
                    async with session() as sess:
                        p = await sess.get(ChannelPair, pair_id)
                        if p:
                            p.dest_id = info["id"]
                            p.dest_title = info["title"]
                            p.dest_username = info.get("username")
                            await sess.commit()
                    await event.reply(f"✅ Destination updated to **{info['title']}** (`{info['id']}`).")
            del _awaiting_manual[sender_id]
        except Exception as e:
            await db_log("ERROR", f"Manual entry failed: {e}", module="bot")
            await event.reply(f"❌ Error: {e}")


async def _build_dst_picker(pair_id: int, source_id: int):
    dialogs = await list_recent_dialogs(limit=15)
    buttons = []
    for d in dialogs:
        label = f"{d['title']} ({d['type']})"
        if len(label) > 60:
            label = label[:57] + "..."
        buttons.append([_glass_button(label, f"pair:pick:dst:{d['id']}:{source_id}:{pair_id}")])
    buttons.append([_glass_button("⌨️ Enter ID/Username manually", f"pair:manual:dst:{pair_id}:{source_id}")])
    buttons.append([_glass_button("🔙 Cancel", "menu:channels")])
    return buttons
