#!/bin/bash
# ============================================================
# 🤖 VPS Python Terminal + MCP — Auto Setup & Run (Linux/VPS)
#    Replaces Node.js version. Runs:
#      • Web Terminal -> /vps
#      • Single MCP URL -> /mcp
#    + Cloudflare Quick Tunnel (one public URL for both)
# ============================================================

set -e

# 🎨 Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PORT="${VPS_PORT:-1212}"
REPO_RAW="https://raw.githubusercontent.com/VathanarubanShayarukshan/remote_cmd/refs/heads/main"

echo -e "${BLUE}🚀 VPS Python Terminal + MCP — Auto Setup & Run${NC}"
echo -e "${CYAN}==============================================${NC}"

check_cmd() { command -v "$1" &>/dev/null; }
print_status() { echo -e "${GREEN}✅ $1${NC}"; }
print_warn()   { echo -e "${YELLOW}⚠️ $1${NC}"; }
print_err()    { echo -e "${RED}❌ $1${NC}"; }

# 1️⃣ Check Python 3 (instead of Node.js now!)
echo -e "${YELLOW}🔍 Checking Python 3...${NC}"
if ! check_cmd python3; then
    print_warn "Python3 not found! Installing..."
    if check_cmd apt-get; then
        sudo apt-get update -y && sudo apt-get install -y python3 python3-pip
    elif check_cmd yum; then
        sudo yum install -y python3 python3-pip
    else
        print_err "No supported package manager found!"
        exit 1
    fi
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]; }; then
    print_err "Python $PY_VER too old! Need >= 3.8"
    exit 1
fi
print_status "Python $PY_VER is ready!"

# pip ensure
if ! python3 -m pip --version &>/dev/null; then
    print_warn "Installing pip..."
    if check_cmd apt-get; then
        sudo apt-get install -y python3-pip || curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3
    else
        curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3
    fi
fi

# 2️⃣ Install 'mcp' package (MCP SDK)
echo -e "${YELLOW}📦 Checking MCP python package...${NC}"
if ! python3 -c "import mcp" 2>/dev/null; then
    print_warn "Installing mcp package..."
    python3 -m pip install --upgrade mcp || \
    python3 -m pip install --break-system-packages --upgrade mcp || \
    sudo python3 -m pip install --upgrade mcp
else
    print_status "mcp package already installed!"
fi

# 3️⃣ Check Cloudflared
echo -e "${YELLOW}🔍 Checking Cloudflared...${NC}"
if ! check_cmd cloudflared; then
    print_warn "Cloudflared not found! Installing..."
    ARCH=$(uname -m)
    if [[ "$ARCH" == "x86_64" || "$ARCH" == "amd64" ]]; then
        wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
        sudo dpkg -i cloudflared-linux-amd64.deb
    elif [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
        wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
        sudo dpkg -i cloudflared-linux-arm64.deb
    else
        print_err "Unsupported architecture: $ARCH"
        exit 1
    fi
else
    print_status "Cloudflared is ready!"
fi

# 4️⃣ Setup Directory
echo -e "${YELLOW}📁 Setting up project directory...${NC}"
mkdir -p web_py && cd web_py

# 5️⃣ Download Python server code
echo -e "${YELLOW}📥 Downloading latest server.py...${NC}"
curl -L -o server.py "${REPO_RAW}/server.py"
if [ ! -s server.py ]; then
    print_err "Failed to download server.py!"
    exit 1
fi
print_status "Downloaded successfully!"

# 6️⃣ Syntax Check
echo -e "${YELLOW}✅ Checking Python syntax...${NC}"
if ! python3 -m py_compile server.py; then
    print_err "Syntax error in server.py!"
    exit 1
fi
print_status "Syntax OK!"

# 7️⃣ Kill Old Processes (node + python both)
echo -e "${YELLOW}🛑 Stopping old instances...${NC}"
pkill -f "node server.js" 2>/dev/null || true
pkill -f "python3 server.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2

# 8️⃣ Start Python Server
echo -e "${YELLOW}🚀 Starting Python server (Web + MCP)...${NC}"
nohup python3 server.py < /dev/null > output.log 2>&1 & disown
sleep 3

if pgrep -f "python3 server.py" > /dev/null; then
    print_status "Server running on port $PORT!"
else
    print_err "Server failed to start! Check output.log:"
    tail -10 output.log
    exit 1
fi

# quick self-test
if curl -s "http://localhost:$PORT/api/read" >/dev/null 2>&1; then
    print_status "API responding OK!"
fi

# 9️⃣ Start Cloudflare Tunnel
echo -e "${YELLOW}☁️ Starting Cloudflare Quick Tunnel...${NC}"
nohup cloudflared tunnel --url "http://localhost:$PORT" < /dev/null > tunnel.log 2>&1 & disown
sleep 10

# 🔟 Extract & Show SINGLE URL
TUNNEL_URL=$(grep -oE 'https://[^ ]+\.trycloudflare\.com' tunnel.log 2>/dev/null | head -1)
if [ -n "$TUNNEL_URL" ]; then
    echo -e "\n${GREEN}🎉 SUCCESS! Your VPS is LIVE!${NC}"
    echo -e "${CYAN}🌐 Web Terminal : ${TUNNEL_URL}/vps${NC}"
    echo -e "${CYAN}🤖 MCP URL (AI): ${TUNNEL_URL}/mcp${NC}"
    echo -e "${YELLOW}💡 Give the /mcp url to any AI tool (single MCP url).${NC}"
else
    print_warn "Tunnel URL not ready yet. Check tunnel.log:"
    tail -10 tunnel.log
fi

echo -e "\n${GREEN}✅ Auto-setup complete!${NC}"
echo -e "${BLUE}📁 Logs: ./output.log | ./tunnel.log${NC}"
echo -e "${BLUE}🔄 Restart: pkill -f 'python3 server.py'; pkill -f cloudflared; bash setup_python.sh${NC}"
