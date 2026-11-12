#!/bin/bash
# Remote-Shell MCP + Web Terminal — Linux auto setup & run.
# Installs Python3 + cloudflared if missing, starts everything in the background,
# opens two Cloudflare quick tunnels, and prints the public URLs.
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[..]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; }

cd "$(dirname "$0")"
BASE_DIR="$(pwd)"
RUNTIME="$BASE_DIR/.runtime"
BIN_DIR="$BASE_DIR/bin"
MCP_PORT="${PORT:-1213}"
TERM_PORT="${TERMINAL_PORT:-1212}"
mkdir -p "$RUNTIME" "$BIN_DIR"

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}  Remote-Shell MCP + Web Terminal  (Linux)${NC}"
echo -e "${BLUE}==============================================${NC}"

# 1) Python 3
warn "Checking Python 3..."
if ! command -v python3 >/dev/null 2>&1; then
    warn "python3 not found — attempting install..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -y && sudo apt-get install -y python3
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y python3
    elif command -v apk >/dev/null 2>&1; then
        sudo apk add --no-cache python3
    else
        err "No supported package manager. Install Python 3.8+ manually."
        exit 1
    fi
fi
command -v python3 >/dev/null 2>&1 || { err "Python 3 still missing."; exit 1; }
ok "Python: $(python3 --version 2>&1)"

# 2) cloudflared (system-wide, else local binary — no sudo needed)
CF_BIN=""
if command -v cloudflared >/dev/null 2>&1; then
    CF_BIN="$(command -v cloudflared)"
elif [ -x "$BIN_DIR/cloudflared" ]; then
    CF_BIN="$BIN_DIR/cloudflared"
else
    warn "cloudflared not found — downloading local binary..."
    ARCH="$(uname -m)"
    case "$ARCH" in
        x86_64|amd64) CF_ARCH="amd64" ;;
        aarch64|arm64) CF_ARCH="arm64" ;;
        armv7l|armhf) CF_ARCH="arm" ;;
        *) err "Unsupported architecture: $ARCH"; exit 1 ;;
    esac
    URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$URL" -o "$BIN_DIR/cloudflared"
    else
        wget -q "$URL" -O "$BIN_DIR/cloudflared"
    fi
    chmod +x "$BIN_DIR/cloudflared"
    CF_BIN="$BIN_DIR/cloudflared"
fi
ok "cloudflared: $("$CF_BIN" --version 2>&1 | head -1)"

# 3) Stop old instances
warn "Stopping old instances..."
pkill -f "mcp_server.py" 2>/dev/null || true
pkill -f "remote_cmd.py" 2>/dev/null || true
pkill -f "mcp-server.js" 2>/dev/null || true
pkill -f "server V1.js" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://localhost:$MCP_PORT" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://localhost:$TERM_PORT" 2>/dev/null || true
sleep 1

# 4) Start servers in background
warn "Starting MCP server (port $MCP_PORT)..."
PORT="$MCP_PORT" nohup python3 "$BASE_DIR/mcp_server.py" > "$RUNTIME/mcp.log" 2>&1 & disown
warn "Starting Web Terminal (port $TERM_PORT)..."
TERMINAL_PORT="$TERM_PORT" nohup python3 "$BASE_DIR/remote_cmd.py" > "$RUNTIME/terminal.log" 2>&1 & disown
sleep 2

if ! curl -fs "http://localhost:$MCP_PORT/health" >/dev/null 2>&1; then
    err "MCP server failed to start. Last log lines:"; tail -n 10 "$RUNTIME/mcp.log"; exit 1
fi
ok "MCP server is up."

# 5+6) Start Cloudflare quick tunnels and extract URLs, with retries.
# Quick tunnels can be rate-limited (HTTP 429) when created too frequently.
extract_url() { grep -oE 'https://[a-z0-9]+(-[a-z0-9]+)+\.trycloudflare\.com' "$1" 2>/dev/null | head -1; }
start_and_wait_tunnel() { # port logfile -> echoes URL (or empty)
    local port="$1" log="$2" url="" attempt i
    for attempt in 1 2 3; do
        nohup "$CF_BIN" tunnel --url "http://localhost:$port" > "$log" 2>&1 & disown
        for i in $(seq 1 25); do
            url="$(extract_url "$log")"
            [ -n "$url" ] && { echo "$url"; return 0; }
            sleep 1
        done
        warn "Tunnel on port $port not up (attempt $attempt/3) — Cloudflare may be rate-limiting quick tunnels; retrying..." >&2
        pkill -f "cloudflared tunnel --url http://localhost:$port" 2>/dev/null || true
        sleep 5
    done
    echo ""
}
warn "Starting Cloudflare tunnels..."
MCP_URL="$(start_and_wait_tunnel "$MCP_PORT" "$RUNTIME/tunnel-mcp.log")"
TERM_URL="$(start_and_wait_tunnel "$TERM_PORT" "$RUNTIME/tunnel-terminal.log")"

TOKEN="$(cat "$RUNTIME/token" 2>/dev/null | tr -d '[:space:]')"

# 7) Optional: install the AI guide skill for Claude Code
if [ -d "$HOME/.claude" ] && [ -f "$BASE_DIR/skills/remote-shell/SKILL.md" ]; then
    mkdir -p "$HOME/.claude/skills/remote-shell"
    cp "$BASE_DIR/skills/remote-shell/SKILL.md" "$HOME/.claude/skills/remote-shell/SKILL.md"
    ok "Installed AI guide skill to ~/.claude/skills/remote-shell/"
fi

echo ""
echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}  SUCCESS — services are LIVE in background${NC}"
echo -e "${GREEN}==============================================${NC}"
if [ -n "$MCP_URL" ]; then
    echo -e "${CYAN}MCP URL (for Claude):${NC}"
    echo -e "  ${GREEN}${MCP_URL}/mcp?token=${TOKEN}${NC}"
    echo ""
    echo -e "${YELLOW}Add to Claude Code:${NC}"
    echo "  claude mcp add --transport http remote-shell \"${MCP_URL}/mcp?token=${TOKEN}\""
else
    warn "MCP tunnel failed to start. If the log shows HTTP 429 / 'failed to request', Cloudflare is"
    warn "rate-limiting quick tunnels from this IP — wait a few minutes and re-run, or use a named tunnel."
    warn "Log: tail -f $RUNTIME/tunnel-mcp.log"
fi
echo ""
if [ -n "$TERM_URL" ]; then
    echo -e "${CYAN}Web Terminal URL (for you):${NC}"
    echo -e "  ${GREEN}${TERM_URL}/vps?token=${TOKEN}${NC}"
else
    warn "Terminal tunnel URL not ready yet. Check: tail -f $RUNTIME/tunnel-terminal.log"
fi
echo ""
echo -e "${BLUE}Token file:${NC} $RUNTIME/token"
echo -e "${BLUE}Logs:${NC} $RUNTIME/{mcp,terminal,tunnel-mcp,tunnel-terminal}.log"
echo -e "${BLUE}Stop everything:${NC} bash stop.sh"
echo ""
warn "Quick-tunnel URLs change on every restart. Re-run setup.sh to get new URLs."
