"""SQLAlchemy 2.0 models.

All state lives in PostgreSQL. Models:

  * Admin           — one row per Telegram user with bot access
  * PermissionFlag  — many-to-many: admin <-> permission name
  * ChannelPair     — one source -> destination link with its own cursor
  * ForwardCursor   — last successfully forwarded message id per pair
  * HistoryEntry    — every forwarded message (audit trail)
  * LogEntry        — application log mirrored to DB for the WebUI Logs tab
  * Setting         — key/value runtime settings (pause state, filters, etc.)
  * Connection      — recent WebUI/Telegram sessions for the Connections tab
  * OtpCode         — short-lived login codes for WebUI auth

The schema is created on startup via ``init_db()``; Alembic is wired up
in ``deploy/alembic.ini`` for production migrations.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import AsyncIterator

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, select, update, delete,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


# ----- permissions enum ---------------------------------------------------
class Perm(str, Enum):
    """Granular admin permissions. Super-admins (level 9) bypass all checks."""
    MANAGE_ADMINS   = "manage_admins"
    EDIT_CHANNELS   = "edit_channels"
    EDIT_SETTINGS   = "edit_settings"
    PAUSE_RESUME    = "pause_resume"
    VIEW_LOGS       = "view_logs"
    VIEW_HISTORY    = "view_history"
    BACKFILL        = "backfill"
    CLEAR_LOGS      = "clear_logs"

ALL_PERMS: list[Perm] = list(Perm)


# ----- base -----------------------------------------------------------------
class Base(DeclarativeBase):
    pass


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    tg_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tg_first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=1)  # 1 = regular admin, 9 = super
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    flags: Mapped[list["PermissionFlag"]] = relationship(
        back_populates="admin", cascade="all, delete-orphan"
    )

    @property
    def is_super(self) -> bool:
        return self.level >= 9

    def has_perm(self, perm: Perm) -> bool:
        if self.is_super:
            return True
        return any(f.name == perm.value for f in self.flags)


class PermissionFlag(Base):
    __tablename__ = "permission_flags"
    __table_args__ = (UniqueConstraint("admin_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))

    admin: Mapped[Admin] = relationship(back_populates="flags")


class ChannelPair(Base):
    """A source -> destination forwarding link."""
    __tablename__ = "channel_pairs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="default")
    source_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dest_id: Mapped[int] = mapped_column(BigInteger, index=True)
    dest_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    dest_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    cursor: Mapped["ForwardCursor | None"] = relationship(
        back_populates="pair", uselist=False, cascade="all, delete-orphan"
    )


class ForwardCursor(Base):
    """Tracks the highest source message id we have already copied."""
    __tablename__ = "forward_cursors"
    __table_args__ = (UniqueConstraint("pair_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("channel_pairs.id", ondelete="CASCADE"))
    last_source_msg_id: Mapped[int] = mapped_column(BigInteger, default=0)
    last_dest_msg_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_forwarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    backfill_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    pair: Mapped[ChannelPair] = relationship(back_populates="cursor")


class HistoryEntry(Base):
    """Audit trail: every successful forward."""
    __tablename__ = "history_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("channel_pairs.id", ondelete="CASCADE"), index=True)
    source_msg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    dest_msg_id: Mapped[int] = mapped_column(BigInteger)
    msg_type: Mapped[str] = mapped_column(String(32))     # text|photo|video|document|...
    msg_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    forwarded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class LogEntry(Base):
    """Mirror of loguru log entries for the WebUI Logs tab."""
    __tablename__ = "log_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text)
    module: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class Setting(Base):
    """Key/value runtime settings."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Connection(Base):
    """Tracks WebUI and Telegram bot sessions."""
    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))   # web|bot
    admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(256), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class OtpCode(Base):
    """Short-lived WebUI login codes."""
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)


# ----- engine / session helpers --------------------------------------------
_engine = None
_SessionLocal: async_sessionmaker[AsyncSession] | None = None


async def init_db(db_url: str) -> None:
    """Create engine, session factory, and all tables (idempotent)."""
    global _engine, _SessionLocal
    _engine = create_async_engine(db_url, pool_pre_ping=True, echo=False)
    _SessionLocal = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def session() -> AsyncSession:
    """Return a fresh AsyncSession. Caller is responsible for ``await sess.close()``.

    Recommended pattern::

        async with session() as sess:
            ...
    """
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    return _SessionLocal()
