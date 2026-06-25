"""Auth routes: request OTP, verify OTP, logout."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.models import Admin, Connection, OtpCode, session
from app.telethon_client import get_bot_client, db_log
from app.web.deps import SESSION_COOKIE, get_current_admin, make_session_cookie

router = APIRouter(prefix="/api/auth")


class LoginRequest(BaseModel):
    tg_user_id: int


class VerifyRequest(BaseModel):
    tg_user_id: int
    code: str


@router.post("/request")
async def request_otp(req: LoginRequest, request: Request) -> dict:
    """Generate a 6-digit OTP and DM it to the user via the bot account.

    The user must already be a registered admin. The OTP is single-use
    and expires after 5 minutes.
    """
    async with session() as sess:
        q = await sess.execute(select(Admin).where(Admin.tg_user_id == req.tg_user_id))
        admin = q.scalar_one_or_none()
    if admin is None:
        # don't leak who's an admin
        return {"sent": True}

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = datetime.utcnow() + timedelta(minutes=5)
    async with session() as sess:
        sess.add(OtpCode(
            tg_user_id=req.tg_user_id,
            code=code,
            expires_at=expires,
        ))
        # invalidate older unconsumed codes
        existing_q = await sess.execute(
            select(OtpCode).where(
                OtpCode.tg_user_id == req.tg_user_id,
                OtpCode.consumed == False,
            )
        )
        for old in existing_q.scalars():
            old.consumed = True
        await sess.commit()

    # DM the code
    try:
        bot = await get_bot_client()
        await bot.send_message(req.tg_user_id, (
            f"🔐 **tg-forwarder login code**\n\n"
            f"`{code}`\n\n"
            f"Expires in 5 minutes. If you didn't request this, ignore this message."
        ), link_preview=False)
    except Exception as e:
        await db_log("ERROR", f"Failed to send OTP to {req.tg_user_id}: {e}", module="web.auth")
        raise HTTPException(status_code=503, detail="Could not deliver OTP. Have you started the bot?")

    # log the connection attempt
    async with session() as sess:
        sess.add(Connection(
            kind="web",
            admin_id=req.tg_user_id,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:256],
            detail="otp-request",
        ))
        await sess.commit()

    return {"sent": True}


@router.post("/verify")
async def verify_otp(req: VerifyRequest, request: Request, response: Response) -> dict:
    """Verify the OTP and set a session cookie."""
    async with session() as sess:
        q = await sess.execute(
            select(OtpCode).where(
                OtpCode.tg_user_id == req.tg_user_id,
                OtpCode.code == req.code.strip(),
                OtpCode.consumed == False,
                OtpCode.expires_at > datetime.utcnow(),
            ).order_by(OtpCode.id.desc())
        )
        otp = q.scalar_one_or_none()
        if otp is None:
            raise HTTPException(status_code=401, detail="Invalid or expired code")
        otp.consumed = True
        await sess.commit()

        admin_q = await sess.execute(select(Admin).where(Admin.tg_user_id == req.tg_user_id))
        admin = admin_q.scalar_one_or_none()
        if admin is None:
            raise HTTPException(status_code=403, detail="Not an admin")

        sess.add(Connection(
            kind="web",
            admin_id=admin.tg_user_id,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:256],
            detail="otp-verify-success",
        ))
        await sess.commit()

    cookie = make_session_cookie(admin)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=cookie,
        httponly=True,
        samesite="lax",
        max_age=8 * 3600,
        secure=False,  # set True behind HTTPS reverse proxy
    )
    return {
        "ok": True,
        "admin": {
            "tg_user_id": admin.tg_user_id,
            "tg_username": admin.tg_username,
            "tg_first_name": admin.tg_first_name,
            "level": admin.level,
            "is_super": admin.is_super,
        },
    }


@router.post("/logout")
async def logout(response: Response, _admin: Admin = Depends(get_current_admin)) -> dict:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(admin: Admin = Depends(get_current_admin)) -> dict:
    return {
        "tg_user_id": admin.tg_user_id,
        "tg_username": admin.tg_username,
        "tg_first_name": admin.tg_first_name,
        "level": admin.level,
        "is_super": admin.is_super,
    }
