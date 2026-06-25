#!/usr/bin/env bash
# ===========================================================================
#  tg-forwarder — one-command installer + first-time configuration wizard
#  Target OS: Ubuntu 22.04 (also works on 24.04 / Debian 11+)
#  Repo:      https://github.com/Black0Wolf/tg-forwarder
#  License:   AGPL-3.0
# ---------------------------------------------------------------------------
#  Usage:
#     ./install.sh            # full install + interactive wizard
#     ./install.sh --non-interactive   # CI mode, requires env vars to be set
#     ./install.sh --webui-only        # only build the React WebUI bundle
# ===========================================================================
set -Eeuo pipefail

# ----- colors --------------------------------------------------------------
if [[ -t 1 ]]; then
  C_RESET="\033[0m"; C_BOLD="\033[1m"; C_DIM="\033[2m"
  C_RED="\033[31m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"
  C_BLUE="\033[34m"; C_MAGENTA="\033[35m"; C_CYAN="\033[36m"
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""
  C_BLUE=""; C_MAGENTA=""; C_CYAN=""
fi

log()  { printf "${C_BOLD}${C_BLUE}▸${C_RESET} %s\n" "$*"; }
ok()   { printf "${C_BOLD}${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn() { printf "${C_BOLD}${C_YELLOW}!${C_RESET} %s\n" "$*" >&2; }
die()  { printf "${C_BOLD}${C_RED}✗${C_RESET} %s\n" "$*" >&2; exit 1; }

# ----- paths & flags -------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

INTERACTIVE=1
WEBUI_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --non-interactive) INTERACTIVE=0 ;;
    --webui-only)      WEBUI_ONLY=1 ;;
    -h|--help)
      sed -n '2,15p' "$0"; exit 0 ;;
    *) die "Unknown flag: $arg" ;;
  esac
done

# ----- detect OS -----------------------------------------------------------
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  : "${ID:=unknown}"; : "${VERSION_ID:=unknown}"
  if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
    warn "Detected OS '$ID $VERSION_ID' — this script targets Ubuntu 22.04."
    warn "It will still try to run, but YMMV."
  fi
else
  warn "/etc/os-release not found. Continuing as if on Ubuntu 22.04."
fi

# ===========================================================================
#  STEP 1 — System packages
# ===========================================================================
install_system_deps() {
  log "Installing system packages (Python, Node.js, PostgreSQL, build tools)…"
  if ! command -v apt-get >/dev/null 2>&1; then
    die "apt-get not found. This installer expects a Debian-family Linux."
  fi

  sudo apt-get update -y
  sudo apt-get install -y \
    python3 python3-venv python3-pip python3-dev \
    build-essential libffi-dev libssl-dev \
    git curl \
    postgresql postgresql-contrib libpq-dev \
    ca-certificates

  # Node.js 20 LTS (only needed to build the React WebUI)
  if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null | cut -d. -f1 | tr -d v)" -lt 18 ]]; then
    log "Installing Node.js 20 LTS via NodeSource…"
    if [[ ! -f /etc/apt/keyrings/nodesource.gpg ]]; then
      curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
      echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        | sudo tee /etc/apt/sources.list.d/nodesource.list >/dev/null
      sudo apt-get update -y
    fi
    sudo apt-get install -y nodejs
  fi
  ok "System packages installed."
}

# ===========================================================================
#  STEP 2 — Python virtualenv
# ===========================================================================
create_venv() {
  log "Creating Python virtualenv at .venv/…"
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install --upgrade pip wheel setuptools >/dev/null
  pip install -r requirements.txt
  ok "Virtualenv ready."
}

# ===========================================================================
#  STEP 3 — PostgreSQL database
# ===========================================================================
setup_postgres() {
  log "Configuring PostgreSQL database…"
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='tgforwarder'" | grep -q 1; then
    sudo -u postgres psql -c "CREATE USER tgforwarder WITH PASSWORD 'tgforwarder';"
  else
    warn "PostgreSQL role 'tgforwarder' already exists — skipping create."
  fi
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='tgforwarder'" | grep -q 1; then
    sudo -u postgres createdb -O tgforwarder tgforwarder
  else
    warn "PostgreSQL database 'tgforwarder' already exists — skipping create."
  fi
  sudo systemctl enable --now postgresql >/dev/null 2>&1 || true
  ok "PostgreSQL ready (user=tgforwarder db=tgforwarder)."
}

# ===========================================================================
#  STEP 4 — Interactive config wizard
# ===========================================================================
ask() {
  # ask "prompt" "default" -> echoes user input or default
  local prompt="$1" default="${2:-}"
  local reply
  if [[ $INTERACTIVE -eq 1 ]]; then
    printf "${C_BOLD}${C_CYAN}?${C_RESET} %s " "$prompt"
    [[ -n "$default" ]] && printf "${C_DIM}[%s]${C_RESET} " "$default"
    read -r reply
    echo "${reply:-$default}"
  else
    echo "$default"
  fi
}

ask_secret() {
  # ask_secret "prompt" -> reads silently
  local prompt="$1"
  if [[ $INTERACTIVE -eq 1 ]]; then
    printf "${C_BOLD}${C_CYAN}?${C_RESET} %s " "$prompt"
    read -rs reply
    echo; echo "$reply"
  else
    echo "${TGF_BOT_TOKEN:-}"
  fi
}

run_wizard() {
  log "Starting first-time configuration wizard…"

  echo
  printf "${C_BOLD}╔════════════════════════════════════════════════════════════╗${C_RESET}\n"
  printf "${C_BOLD}║  tg-forwarder — first-time configuration wizard            ║${C_RESET}\n"
  printf "${C_BOLD}║  You will need:                                            ║${C_RESET}\n"
  printf "${C_BOLD}║   • a bot token from @BotFather                            ║${C_RESET}\n"
  printf "${C_BOLD}║   • api_id + api_hash from https://my.telegram.org          ║${C_RESET}\n"
  printf "${C_BOLD}║   • your phone number (with country code)                  ║${C_RESET}\n"
  printf "${C_BOLD}║   • your Telegram user ID (via @userinfobot)               ║${C_RESET}\n"
  printf "${C_BOLD}╚════════════════════════════════════════════════════════════╝${C_RESET}\n"
  echo

  local bot_token api_id api_hash phone super_admin db_pass web_port web_secret

  bot_token="$(ask "Bot token (from @BotFather):" "")"
  [[ -z "$bot_token" ]] && die "Bot token is required."

  api_id="$(ask "Telegram api_id (from my.telegram.org):" "")"
  [[ -z "$api_id" ]] && die "api_id is required."

  api_hash="$(ask "Telegram api_hash (from my.telegram.org):" "")"
  [[ -z "$api_hash" ]] && die "api_hash is required."

  phone="$(ask "Your phone (+country code):" "")"
  [[ -z "$phone" ]] && die "phone is required."

  super_admin="$(ask "Your Telegram user ID (numeric, from @userinfobot):" "")"
  [[ -z "$super_admin" ]] && die "super_admin user ID is required."

  db_pass="$(ask "PostgreSQL password for 'tgforwarder' user" "tgforwarder")"
  web_port="$(ask "WebUI port" "8000")"
  web_secret="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p | head -c 32)"

  # update postgres password
  sudo -u postgres psql -c "ALTER USER tgforwarder WITH PASSWORD '${db_pass}';" >/dev/null

  cat > config.yaml <<YAML
# Auto-generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Edit freely — restart the service to apply.

bot_token: "${bot_token}"
api_id: ${api_id}
api_hash: "${api_hash}"
phone: "${phone}"
session_name: "userbot"

db_url: "postgresql+asyncpg://tgforwarder:${db_pass}@localhost:5432/tgforwarder"

web:
  host: "127.0.0.1"
  port: ${web_port}
  base_url: "http://127.0.0.1:${web_port}"
  secret_key: "${web_secret}"

forwarder:
  mode: "copy"
  initial_backfill: true
  backfill_batch_size: 100
  backfill_delay_ms: 250
  live_poll_interval_s: 2
  catch_up_on_start: true

super_admins:
  - ${super_admin}
YAML
  chmod 600 config.yaml
  ok "config.yaml written (mode 600)."

  # install systemd service
  install_systemd_service "$web_port"

  cat <<EOF

${C_BOLD}${C_GREEN}═══════════════════════════════════════════════════════════════${C_RESET}
${C_BOLD}  Configuration complete!${C_RESET}
${C_BOLD}${C_GREEN}═══════════════════════════════════════════════════════════════${C_RESET}

Next steps:

  1. Start everything (foreground, for testing):
       ${C_DIM}source .venv/bin/activate${C_RESET}
       ${C_DIM}python main.py${C_RESET}

  2. Or start as a background service:
       ${C_DIM}sudo systemctl enable --now tg-forwarder${C_RESET}
       ${C_DIM}sudo systemctl status tg-forwarder${C_RESET}

  3. The Telethon userbot will ask for a login code on first run.
     Enter it in the terminal where the service is running.
     After that the session file (userbot.session) is reused.

  4. Open the WebUI at:
       ${C_DIM}http://127.0.0.1:${web_port}${C_RESET}

  5. In Telegram, send /start to your bot to open the config menu.

Logs:
       ${C_DIM}sudo journalctl -u tg-forwarder -f${C_RESET}

EOF
}

# ===========================================================================
#  STEP 5 — systemd service
# ===========================================================================
install_systemd_service() {
  local port="$1"
  log "Installing systemd service…"
  local svc_path="/etc/systemd/system/tg-forwarder.service"
  sudo tee "$svc_path" >/dev/null <<UNIT
[Unit]
Description=tg-forwarder (Telegram forwarder bot + WebUI)
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${SCRIPT_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${SCRIPT_DIR}/.venv/bin/python ${SCRIPT_DIR}/main.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload
  ok "systemd unit installed at ${svc_path}."
}

# ===========================================================================
#  STEP 6 — Build the React WebUI
# ===========================================================================
build_webui() {
  log "Building React WebUI (npm install + vite build)…"
  if ! command -v node >/dev/null 2>&1; then
    die "Node.js is not installed. Run install.sh without --webui-only first."
  fi
  pushd webui >/dev/null
  if [[ ! -d node_modules ]]; then
    npm install
  fi
  npm run build
  popd >/dev/null
  ok "WebUI bundle built at webui/dist/."
}

# ===========================================================================
#  main
# ===========================================================================
main() {
  log "Welcome to the tg-forwarder installer."
  echo

  if [[ $WEBUI_ONLY -eq 1 ]]; then
    build_webui
    exit 0
  fi

  install_system_deps
  create_venv
  setup_postgres

  if [[ ! -f config.yaml ]]; then
    run_wizard
  else
    warn "config.yaml already exists — skipping wizard."
    install_systemd_service "$(grep -E '^\s*port:' config.yaml | head -1 | awk '{print $2}' | tr -d '\"')"
  fi

  build_webui

  ok "All done. Read the next-steps message above."
}

main "$@"
