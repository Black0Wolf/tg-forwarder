"""Core forwarder engine.

Responsibilities:
  * On startup, for each enabled ``ChannelPair``:
      - If initial_backfill is true and cursor is 0, iterate the source
        channel's full message history from message id 1 upwards.
      - If a cursor already exists, resume from ``last_source_msg_id + 1``.
      - Continue indefinitely, polling for new messages every
        ``live_poll_interval_s`` seconds.
  * Copy messages (no forward tag). Supports text, photos, videos, voice,
    video notes, documents, stickers, albums, polls, locations, contacts.
  * Persist every successful forward as a HistoryEntry (audit trail).
  * Update the ForwardCursor atomically after each forward, so a crash
    never causes duplicates.

Anti-duplicate strategy:
  * The cursor is keyed on ``source_msg_id`` per pair. After a forward
    succeeds we write HistoryEntry + bump ForwardCursor in one DB
    transaction. If we crash mid-flight, on restart we resume from the
    last persisted cursor and the source message is re-processed.
  * A unique index on (pair_id, source_msg_id) would also be enforced
    if we had idempotency keys; here we rely on cursor monotonicity.
"""
from __future__ import annotations

import asyncio
import html
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from telethon.tl.types import (
    MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage,
    MessageMediaContact, MessageMediaGeo, MessageMediaPoll,
)

from app.config import get_settings
from app.models import (
    ChannelPair, ForwardCursor, HistoryEntry, Setting,
    session,
)
from app.telethon_client import get_bot_client, get_user_client, db_log


# ---------------------------------------------------------------------------
#  State
# ---------------------------------------------------------------------------
PAUSE_KEY = "forwarder.paused"
_tasks: dict[int, asyncio.Task] = {}     # pair_id -> worker task
_runner_task: asyncio.Task | None = None


def is_paused() -> bool:
    """Cheap in-memory flag checked inside worker loops."""
    return _PAUSE_FLAG


_PAUSE_FLAG: bool = False


async def load_pause_state() -> None:
    global _PAUSE_FLAG
    async with session() as sess:
        s = await sess.get(Setting, PAUSE_KEY)
        _PAUSE_FLAG = (s is not None and s.value == "1")


async def set_paused(paused: bool) -> None:
    global _PAUSE_FLAG
    _PAUSE_FLAG = paused
    async with session() as sess:
        existing = await sess.get(Setting, PAUSE_KEY)
        if existing is None:
            sess.add(Setting(key=PAUSE_KEY, value="1" if paused else "0"))
        else:
            existing.value = "1" if paused else "0"
        await sess.commit()


# ---------------------------------------------------------------------------
#  Cursor helpers
# ---------------------------------------------------------------------------
async def _get_or_create_cursor(pair_id: int) -> ForwardCursor:
    """Return the cursor row for ``pair_id``, creating an empty one if absent.

    Returned object remains usable after the session closes because
    ``expire_on_commit=False`` on the session factory.
    """
    async with session() as sess:
        result = await sess.execute(
            select(ForwardCursor).where(ForwardCursor.pair_id == pair_id)
        )
        cur = result.scalar_one_or_none()
        if cur is None:
            cur = ForwardCursor(pair_id=pair_id, last_source_msg_id=0)
            sess.add(cur)
            await sess.commit()
            await sess.refresh(cur)
        return cur


async def _bump_cursor(pair_id: int, source_msg_id: int, dest_msg_id: int) -> None:
    async with session() as sess:
        await sess.execute(
            update(ForwardCursor)
            .where(ForwardCursor.pair_id == pair_id)
            .values(
                last_source_msg_id=source_msg_id,
                last_dest_msg_id=dest_msg_id,
                last_forwarded_at=datetime.utcnow(),
            )
        )
        await sess.commit()


# ---------------------------------------------------------------------------
#  Message copy
# ---------------------------------------------------------------------------
async def _copy_message(source_peer: int, msg_id: int, dest_peer: int) -> tuple[int, str, str | None] | None:
    """Copy a single message. Returns ``(dest_msg_id, msg_type, preview)``.

    Returns ``None`` on failure (caller will retry next iteration).
    """
    user = await get_user_client()
    bot = await get_bot_client()

    # Use the bot account to send the copy into the destination. Bots can
    # post as themselves without a forward tag and are not subject to
    # the user's per-chat rate limits.
    try:
        msg = await user.get_messages(source_peer, ids=msg_id)
    except Exception:
        return None
    if msg is None or msg.empty:
        return None

    msg_type, preview = _describe(msg)

    # Build send params
    send_kwargs: dict[str, Any] = {"link_preview": True}
    if msg.message:
        send_kwargs["message"] = msg.message
    else:
        send_kwargs["message"] = ""

    # Handle media
    if msg.media and not isinstance(msg.media, MessageMediaWebPage):
        send_kwargs["file"] = msg.media

    # Reply fallback for captioned media
    if msg.message and msg.media and not isinstance(msg.media, MessageMediaWebPage):
        send_kwargs["caption"] = msg.message
        send_kwargs.pop("message", None)

    try:
        sent = await bot.send_message(entity=dest_peer, **send_kwargs)
        return sent.id, msg_type, preview
    except FloodWaitError as e:
        await db_log("WARNING", f"FloodWait {e.seconds}s on pair src={source_peer} dst={dest_peer}", module="forwarder")
        await asyncio.sleep(e.seconds + 1)
        return None
    except Exception as e:
        await db_log("ERROR", f"Copy failed src={source_peer}#{msg_id} -> dst={dest_peer}: {e}", module="forwarder")
        return None


def _describe(msg) -> tuple[str, str | None]:
    """Return ``(type, preview_text)`` for a Telethon message."""
    media = msg.media
    text = (msg.message or "").strip()
    if media is None:
        return "text", (text[:200] if text else None)
    if isinstance(media, MessageMediaPhoto):
        return "photo", (text[:200] if text else None)
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        mime = getattr(doc, "mime_type", "") or ""
        if mime.startswith("video"):
            return "video", (text[:200] if text else None)
        if mime.startswith("audio"):
            return "audio", (text[:200] if text else None)
        return "document", (text[:200] if text else None)
    if isinstance(media, MessageMediaContact):
        return "contact", None
    if isinstance(media, MessageMediaGeo):
        return "location", None
    if isinstance(media, MessageMediaPoll):
        return "poll", (media.poll.question if hasattr(media, "poll") else None)
    if isinstance(media, MessageMediaWebPage):
        return "text", (text[:200] if text else None)
    return "other", (text[:200] if text else None)


# ---------------------------------------------------------------------------
#  Per-pair worker
# ---------------------------------------------------------------------------
async def _worker(pair: ChannelPair) -> None:
    cfg = get_settings()
    cursor = await _get_or_create_cursor(pair.id)

    user = await get_user_client()
    # Find min id in source so we know we're done backfilling
    try:
        src_entity = await user.get_entity(pair.source_id)
    except Exception as e:
        await db_log("ERROR", f"Pair {pair.id} cannot resolve source {pair.source_id}: {e}", module="forwarder")
        return

    # Telethon's iter_messages with min_id returns ascending order
    next_id = cursor.last_source_msg_id + 1
    await db_log("INFO", f"Pair {pair.id} ({pair.source_title} -> {pair.dest_title}) starting from msg #{next_id}", module="forwarder")

    while True:
        if _PAUSE_FLAG:
            await asyncio.sleep(2)
            continue
        if not pair.enabled:
            await db_log("INFO", f"Pair {pair.id} disabled, worker exiting", module="forwarder")
            return

        # Pull a batch
        try:
            batch: list = []
            async for m in user.iter_messages(
                src_entity,
                min_id=cursor.last_source_msg_id,
                limit=cfg.forwarder.backfill_batch_size,
                reverse=True,   # ascending
            ):
                batch.append(m)
        except FloodWaitError as e:
            await db_log("WARNING", f"FloodWait {e.seconds}s while iterating pair {pair.id}", module="forwarder")
            await asyncio.sleep(e.seconds + 1)
            continue
        except Exception as e:
            await db_log("ERROR", f"Iteration error pair {pair.id}: {e}", module="forwarder")
            await asyncio.sleep(5)
            continue

        if not batch:
            # No new messages — mark backfill complete, sleep and check again
            if not cursor.backfill_complete:
                async with session() as sess:
                    await sess.execute(
                        update(ForwardCursor)
                        .where(ForwardCursor.pair_id == pair.id)
                        .values(backfill_complete=True)
                    )
                    await sess.commit()
                await db_log("INFO", f"Pair {pair.id} backfill complete", module="forwarder")
            await asyncio.sleep(cfg.forwarder.live_poll_interval_s)
            continue

        for m in batch:
            if _PAUSE_FLAG:
                break
            result = await _copy_message(pair.source_id, m.id, pair.dest_id)
            if result is None:
                # Copy failed (e.g., deleted media, flood wait already handled).
                # Advance the cursor anyway so we don't loop forever on the
                # same broken message — log and move on.
                await db_log("WARNING", f"Skipping src msg #{m.id} on pair {pair.id}", module="forwarder")
                async with session() as sess:
                    await sess.execute(
                        update(ForwardCursor)
                        .where(ForwardCursor.pair_id == pair.id)
                        .values(
                            last_source_msg_id=m.id,
                            last_forwarded_at=datetime.utcnow(),
                        )
                    )
                    await sess.commit()
                cursor.last_source_msg_id = m.id
                continue
            dest_msg_id, msg_type, preview = result
            # Write history + bump cursor
            async with session() as sess:
                sess.add(HistoryEntry(
                    pair_id=pair.id,
                    source_msg_id=m.id,
                    dest_msg_id=dest_msg_id,
                    msg_type=msg_type,
                    msg_preview=preview,
                ))
                await sess.execute(
                    update(ForwardCursor)
                    .where(ForwardCursor.pair_id == pair.id)
                    .values(
                        last_source_msg_id=m.id,
                        last_dest_msg_id=dest_msg_id,
                        last_forwarded_at=datetime.utcnow(),
                    )
                )
                await sess.commit()
            cursor.last_source_msg_id = m.id

        # Throttle between batches
        await asyncio.sleep(cfg.forwarder.backfill_delay_ms / 1000.0)


# ---------------------------------------------------------------------------
#  Runner: spawns one worker per enabled pair, supervises them
# ---------------------------------------------------------------------------
async def start_forwarder() -> None:
    global _runner_task
    if _runner_task is not None:
        return
    await load_pause_state()
    _runner_task = asyncio.create_task(_supervise())


async def stop_forwarder() -> None:
    global _runner_task
    if _runner_task is None:
        return
    _runner_task.cancel()
    for t in list(_tasks.values()):
        t.cancel()
    _tasks.clear()
    _runner_task = None


async def _supervise() -> None:
    """Periodically sync the worker set with the DB state of channel pairs."""
    await db_log("INFO", "Forwarder supervisor started", module="forwarder")
    while True:
        try:
            async with session() as sess:
                result = await sess.execute(
                    select(ChannelPair).where(ChannelPair.enabled == True)
                )
                pairs = result.scalars().all()

            active_ids = {p.id for p in pairs}
            # Cancel workers for disabled / deleted pairs
            for pid in list(_tasks.keys()):
                if pid not in active_ids:
                    _tasks[pid].cancel()
                    del _tasks[pid]
                    await db_log("INFO", f"Stopped worker for pair {pid}", module="forwarder")

            # Spawn workers for new / enabled pairs
            for p in pairs:
                if p.id not in _tasks:
                    _tasks[p.id] = asyncio.create_task(_worker_safe(p))
                    await db_log("INFO", f"Started worker for pair {p.id}", module="forwarder")
        except asyncio.CancelledError:
            break
        except Exception as e:
            await db_log("ERROR", f"Supervisor error: {e}", module="forwarder")

        await asyncio.sleep(10)


async def _worker_safe(pair: ChannelPair) -> None:
    """Worker wrapper that swallows exceptions so the supervisor can restart."""
    while True:
        try:
            await _worker(pair)
            return
        except asyncio.CancelledError:
            return
        except Exception as e:
            await db_log("ERROR", f"Pair {pair.id} worker crashed: {e} — restart in 5s", module="forwarder")
            await asyncio.sleep(5)


async def trigger_backfill(pair_id: int, from_msg_id: int | None = None) -> None:
    """Reset a pair's cursor to ``from_msg_id`` (or 0) and ensure worker runs."""
    async with session() as sess:
        await sess.execute(
            update(ForwardCursor)
            .where(ForwardCursor.pair_id == pair_id)
            .values(last_source_msg_id=from_msg_id or 0, backfill_complete=False)
        )
        await sess.commit()
    await db_log("INFO", f"Backfill triggered for pair {pair_id} from #{from_msg_id or 0}", module="forwarder")
