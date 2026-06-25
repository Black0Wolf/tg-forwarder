"""Shared FastAPI dependencies: current admin, OTP, sessions."""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta
from typing import Any

from fastapi import Cookie, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import get_settings
from app.models import Admin, OtpCode, session, select


# ---------------------------------------------------------------------------
#  Session cookie
# ---------------------------------------------------------------------------
SESSION_COOKIE = "tgf_session"
SESSION_TTL = 60 * 60 * 8  # 8 hours


def _serializer() -> URLSafeTimedSerializer:
    cfg = get_settings()
    return URLSafeTimedSerializer(cfg.web.secret_key.get_secret_value(), salt="tgf-session")


def make_session_cookie(admin: Admin) -> str:
    payload = {"uid": admin.tg_user_id, "ts": int(time.time())}
    return _serializer().dumps(payload)


def parse_session_cookie(cookie: str) -> dict[str, Any] | None:
    try:
        return _serializer().loads(cookie, max_age=SESSION_TTL)
    except BadSignature:
        return None


# ---------------------------------------------------------------------------
#  Current admin dependency
# ---------------------------------------------------------------------------
async def get_current_admin(
    request: Request,
    tgf_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Admin:
    if tgf_session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = parse_session_cookie(tgf_session)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    uid = int(payload.get("uid", 0))
    if uid == 0:
        raise HTTPException(status_code=401, detail="Malformed session")
    async with session() as sess:
        q = await sess.execute(select(Admin).where(Admin.tg_user_id == uid))
        admin = q.scalar_one_or_none()
    if admin is None:
        raise HTTPException(status_code=403, detail="Admin no longer exists")
    return admin


async def get_admin_optional(
    tgf_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Admin | None:
    if tgf_session is None:
        return None
    payload = parse_session_cookie(tgf_session)
    if payload is None:
        return None
    uid = int(payload.get("uid", 0))
    if uid == 0:
        return None
    async with session() as sess:
        q = await sess.execute(select(Admin).where(Admin.tg_user_id == uid))
        return q.scalar_one_or_none()
