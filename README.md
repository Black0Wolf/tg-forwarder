# tg-forwarder

> **Telegram channel forwarder with a glass-button in-bot config menu, modular admin permissions, and a modern React WebUI.**

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Platform: Ubuntu 22.04](https://img.shields.io/badge/Platform-Ubuntu%2022.04-E95420?logo=ubuntu&logoColor=white)](#system-requirements)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)](#system-requirements)
[![Stack: Telethon + FastAPI + React](https://img.shields.io/badge/Stack-Telethon%20%7C%20FastAPI%20%7C%20React-6366f1)](#tech-stack)

`tg-forwarder` copies every post from a source Telegram channel to a destination channel — including **every past message from the very first one** — and keeps a durable cursor in PostgreSQL so a restart never duplicates messages. It is built around two Telegram sessions: a **bot** account for the inline config menu and WebUI OTP delivery, and a **userbot** account that reads the source channel's full history and lists your 15 most recent chats for the channel picker.

---

## ✨ Features

### Core forwarder
- **Copy mode** — re-sends messages as native posts (no "Forwarded from" header, no source leak)
- **Full backfill** — on first start, walks the source channel from message id `1` upwards
- **Durable cursor** — every successful forward bumps a per-pair `last_source_msg_id` in PostgreSQL, so a crash or restart resumes from where you left off
- **Live polling** — after backfill completes, polls the source channel for new messages every 2 s
- **Multi-pair** — forward from N sources to N destinations concurrently, each with its own cursor
- **Resilient** — FloodWait-aware, automatic worker restart on errors, supervisor syncs workers with DB state

### In-bot config menu (glass-button UI)
- `/start` opens a clean inline menu: Channels, Admins, Settings, Stats, Pause/Resume
- Channel picker shows your **15 most recent channels/groups** as clickable inline buttons, plus a fallback **"Enter ID/Username manually"** button
- Every screen has a Back button — full keyboard navigation
- Per-pair management: enable/disable, change source, change destination, trigger backfill, delete

### Modular admin system (8 toggleable permissions)
Each admin has zero or more of:

| Permission | What it allows |
|------------|----------------|
| `manage_admins` | Add/remove admins, toggle their permissions |
| `edit_channels` | Create / modify / delete channel pairs |
| `edit_settings` | Change forwarder runtime settings |
| `pause_resume` | Pause/resume the forwarder without shutting down |
| `view_logs` | Access the Logs tab + `/logs` command |
| `view_history` | Access the History tab + `/stats` command |
| `backfill` | Trigger a re-scan from a chosen message id |
| `clear_logs` | Purge stored history or log entries |

Super-admins (level 9, defined in `config.yaml`) bypass all checks.

### WebUI (React + Vite)
- **Dashboard** — live stats over WebSocket: admins count, channel pairs, forwarded total, 24-hour sparkline, per-pair breakdown, recent activity feed
- **Admins** — list, add, remove, toggle each permission with a switch
- **Channels** — list/create/edit/delete pairs; channel picker reuses the same "15 most recent + manual fallback" UX as the bot
- **History** — paginated audit trail with pair/type filters
- **Logs** — live, filterable log viewer with clear-all
- **Connections** — every WebUI login and bot interaction tracked
- **Settings** — pause/resume, trigger global backfill, view runtime config
- **Dark + light themes** — toggle in one click, persisted to localStorage, respects OS preference
- **Mobile-first** — sidebar collapses to a slide-in drawer below 880 px
- **Bot OTP login** — no passwords; the bot DMs you a 6-digit code

---

## 🏗️ Tech stack

| Layer | Choice |
|-------|--------|
| Bot + userbot | **Telethon** (single library, dual sessions) |
| Backend | **FastAPI** (async, OpenAPI docs at `/api/docs`) |
| Frontend | **React 18 + Vite 5 + TypeScript** |
| Database | **PostgreSQL 14+** (async via `asyncpg` + SQLAlchemy 2.0) |
| Auth | Bot OTP — code is DM'd to your Telegram, then exchanged for a signed session cookie |
| Logging | `loguru` → stderr + rotating file + PostgreSQL (mirrored for the Logs tab) |
| Process supervisor | systemd (unit file installed by `install.sh`) |

---

## 📋 System requirements

- **OS**: Ubuntu 22.04 (also tested on 24.04 and Debian 11+)
- **Python**: 3.10 or newer (`python3 -V` to check)
- **Node.js**: 18+ (only to build the WebUI bundle; not needed at runtime)
- **PostgreSQL**: 14 or newer
- **Two Telegram accounts**:
  1. A **bot** account — create one via [@BotFather](https://t.me/BotFather)
  2. A **userbot** account — your personal Telegram account, used to read source channel history and list your recent chats. Get `api_id` and `api_hash` from <https://my.telegram.org> → *API development tools*

> The userbot account must be a member of every source channel you want to forward from, and the bot account must be an admin with "Post Messages" permission in every destination channel.

---

## 🚀 Installation (one command)

```bash
git clone https://github.com/Black0Wolf/tg-forwarder.git
cd tg-forwarder
./install.sh
```

The installer will:

1. Install system packages: Python, Node.js 20 LTS, PostgreSQL, build tools
2. Create a Python virtualenv at `.venv/` and install `requirements.txt`
3. Create a PostgreSQL role + database named `tgforwarder`
4. Run an **interactive first-time config wizard** that asks for:
   - bot token (from @BotFather)
   - Telegram `api_id` and `api_hash` (from my.telegram.org)
   - your phone number (with country code)
   - your Telegram user ID (from @userinfobot)
   - PostgreSQL password and WebUI port
5. Write `config.yaml` (mode 600)
6. Install a systemd unit at `/etc/systemd/system/tg-forwarder.service`
7. Build the React WebUI (`npm install && npm run build`)

After install, start it:

```bash
# Foreground (for first run — Telethon will prompt for the login code):
source .venv/bin/activate
python main.py

# Or as a background service:
sudo systemctl enable --now tg-forwarder
sudo journalctl -u tg-forwarder -f
```

On first run, Telethon will print a prompt in the terminal asking for the login code Telegram sends you. Enter it (and your 2FA password if enabled). After that, `userbot.session` is created and reused on every subsequent start.

### Non-interactive install (for CI / automation)

```bash
TGF_BOT_TOKEN=... TGF_API_ID=... TGF_API_HASH=... \
TGF_PHONE=... TGF_SUPER_ADMINS__0=123456789 \
./install.sh --non-interactive
```

### WebUI-only rebuild

If you only changed React code:

```bash
./install.sh --webui-only
```

---

## 🧭 Usage

### In Telegram

Send these commands to your bot:

| Command | Description |
|---------|-------------|
| `/start` | Open the inline glass-button config menu |
| `/help` | List all commands |
| `/id` | Print your Telegram user ID (handy for adding admins) |
| `/stats` | Quick stats (admins, pairs, forwarded counts, state) |
| `/logs` | Show the 15 most recent log entries |
| `/pause` | Pause the forwarder |
| `/resume` | Resume the forwarder |
| `/addadmin <user_id>` | Add an admin (requires `manage_admins`) |
| `/deladmin <user_id>` | Remove an admin (requires `manage_admins`) |
| `/perms <user_id>` | Show an admin's permission matrix |

### In the WebUI

Open `http://your-server:8000` and sign in with your Telegram user ID. The bot will DM you a 6-digit OTP. After verifying, you get an 8-hour signed session cookie.

Tabs:
- **Dashboard** — live WebSocket stats, 24h sparkline, per-pair cursors, recent activity
- **Admins** — add/remove admins, toggle each of the 8 permissions per admin
- **Channels** — create pairs via the 15-recent picker or manual ID/username entry, toggle/backfill/delete pairs
- **History** — paginated audit trail of every successful forward
- **Connections** — recent WebUI logins and bot interactions
- **Settings** — pause/resume, trigger full backfill, view runtime config
- **Logs** — live log viewer with level filter and clear-all

---

## 🗂️ Project layout

```
tg-forwarder/
├── install.sh              # one-command installer + config wizard
├── main.py                 # entry point: DB + Telethon + FastAPI
├── requirements.txt
├── config.example.yaml
├── LICENSE                 # AGPL-3.0
├── README.md
├── .gitignore
├── app/
│   ├── config.py           # config.yaml + TGF_ env overlay
│   ├── models.py           # SQLAlchemy 2.0 models + Perm enum
│   ├── telethon_client.py  # bot + userbot clients, dialog listing
│   ├── forwarder.py        # core engine: cursor tracking + workers
│   ├── admin_system.py     # 8 perms, require_perm decorator, seeding
│   ├── bot_handlers.py     # commands + glass-button inline menus
│   └── web/
│       ├── server.py       # FastAPI app + WebSocket
│       ├── deps.py         # session cookie, current admin dependency
│       ├── auth.py         # OTP request + verify
│       └── routes/
│           ├── dashboard.py
│           ├── admins.py
│           ├── channels.py
│           ├── settings.py
│           ├── logs.py
│           ├── history.py
│           └── connections.py
├── webui/                  # React + Vite frontend
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/client.ts
│       ├── hooks/useTheme.ts
│       ├── styles/global.css
│       └── pages/
│           ├── Login.tsx
│           ├── Dashboard.tsx
│           ├── Admins.tsx
│           ├── Channels.tsx
│           ├── Settings.tsx
│           ├── Logs.tsx
│           ├── History.tsx
│           └── Connections.tsx
├── data/                   # runtime: logs, session files (gitignored)
└── install.sh              # also installs /etc/systemd/system/tg-forwarder.service
```

---

## 🔐 Security notes

- The WebUI binds to `127.0.0.1` by default. **Do not expose it directly to the internet** — put it behind a TLS-terminating reverse proxy (Caddy, nginx, Traefik) and set `web.base_url` accordingly.
- Session cookies are signed with `web.secret_key` (auto-generated by the installer to 32 random bytes). If you rotate the key, all sessions are invalidated.
- OTPs are 6-digit random, single-use, expire after 5 minutes, and older unconsumed codes for the same user are invalidated on each new request.
- The `super_admins` list in `config.yaml` is reseeded on every startup, so a super-admin can never be locked out from the bot.
- Telegram session files (`bot.session`, `userbot.session`) are sensitive — they allow full account access. They are gitignored and should be backed up securely.

---

## 🛠️ Development

```bash
# Backend in one terminal (auto-reload not yet wired up):
source .venv/bin/activate
python main.py

# Frontend in another terminal (Vite dev server with /api proxy to :8000):
cd webui
npm install
npm run dev
# open http://127.0.0.1:5173
```

API docs (OpenAPI / Swagger) are available at `http://127.0.0.1:8000/api/docs` whenever the backend is running.

---

## 📜 License

Copyright © 2026 Black0Wolf. Released under the **GNU Affero General Public License v3.0**. See [LICENSE](LICENSE) for the full text.

In short: you can run, study, modify, and redistribute this software, **but** any modified version that you expose over a network (e.g., as a hosted service) must also be licensed under AGPL-3.0 and have its source code available to users.

---

## 🤝 Contributing

PRs welcome at <https://github.com/Black0Wolf/tg-forwarder>. Please open an issue first to discuss the change you'd like to make.

## 🐛 Known limitations

- Album (grouped media) messages are forwarded as individual messages — Telethon's album grouping is not preserved on copy.
- The bot account must be a member of every destination channel; it cannot post to channels it has been kicked from.
- The userbot account is the one reading source history; if it gets banned or rate-limited, all pairs stall until the session recovers.
- Per-admin manual-entry state in the bot (waiting for an ID/username reply) is keyed on Telegram user id; if two admins trigger manual entry simultaneously, the second one's state overwrites the first.

## 🗺️ Roadmap

- [ ] Alembic migrations (currently schema is auto-created via `Base.metadata.create_all`)
- [ ] Album grouping preservation
- [ ] Per-pair filter rules (include/exclude by regex, media type, sender)
- [ ] Edit-sync (mirror source message edits into destination)
- [ ] Multi-tenant mode (multiple isolated configurations from one deployment)
