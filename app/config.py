"""Configuration loader.

Reads ``config.yaml`` (next to the repo root) and overlays environment
variables prefixed with ``TGF_``. Nested keys use double underscores in
env vars, e.g. ``TGF_WEB__PORT=9000`` overrides ``web.port``.

Usage::

    from app.config import settings
    print(settings.bot_token)
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator


REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"
ENV_PREFIX = "TGF_"


class WebConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    base_url: str = "http://127.0.0.1:8000"
    secret_key: SecretStr = SecretStr("change-me")


class ForwarderConfig(BaseModel):
    mode: str = "copy"
    initial_backfill: bool = True
    backfill_batch_size: int = 100
    backfill_delay_ms: int = 250
    live_poll_interval_s: int = 2
    catch_up_on_start: bool = True


class Settings(BaseModel):
    bot_token: SecretStr
    api_id: int
    api_hash: SecretStr
    phone: str
    session_name: str = "userbot"
    db_url: str
    web: WebConfig = Field(default_factory=WebConfig)
    forwarder: ForwarderConfig = Field(default_factory=ForwarderConfig)
    super_admins: list[int] = Field(default_factory=list)

    @field_validator("bot_token", "api_hash", "db_url")
    @classmethod
    def _non_empty(cls, v: Any) -> Any:
        if isinstance(v, SecretStr):
            if not v.get_secret_value():
                raise ValueError("must not be empty")
        elif isinstance(v, str) and not v:
            raise ValueError("must not be empty")
        return v


def _deep_update(target: dict, source: dict) -> dict:
    for k, v in source.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_update(target[k], v)
        else:
            target[k] = v
    return target


def _env_overlays() -> dict:
    """Return a dict built from TGF_FOO__BAR env vars."""
    out: dict[str, Any] = {}
    pat = re.compile(rf"^{ENV_PREFIX}(.+)$")
    for key, value in os.environ.items():
        m = pat.match(key)
        if not m:
            continue
        parts = m.group(1).lower().split("__")
        cursor = out
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        # try to coerce to int / bool
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        else:
            try:
                value = int(value)
            except ValueError:
                pass
        cursor[parts[-1]] = value
    return out


def _load_yaml() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw = _load_yaml()
    _deep_update(raw, _env_overlays())
    if not raw:
        raise RuntimeError(
            f"No configuration found. Copy config.example.yaml to "
            f"{CONFIG_PATH} or run ./install.sh."
        )
    return Settings(**raw)


# NOTE: callers should use ``get_settings()`` (cached) rather than a
# module-level singleton so that import never crashes when config.yaml
# is missing (e.g. during fresh checkouts, tests, or `--help` runs).
