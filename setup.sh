#!/bin/bash
# 🤖 VPS Web Terminal - Fully Automated Setup & Run Script
# Auto-checks Node.js, installs cloudflared, downloads code, validates, runs server + tunnel

set -e

# 🎨 Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}🚀 VPS Web Terminal - Auto Setup & Run${NC}"
echo -e "${CYAN}========================================${NC}"

# 🔍 Helper Functions
check_cmd() {
    command -v "$1" &>/dev/null
}

print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warn() {
    echo -e "${YELLOW}⚠️ $1${NC}"
}

print_err() {
    echo -e "${RED}❌ $1${NC}"
}

# 1️⃣ Check Node.js Version
echo -e "${YELLOW}🔍 Checking Node.js...${NC}"
if ! check_cmd node; then
    print_warn "Node.js not found! Installing v20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
    sudo apt-get install -y nodejs
else
    NODE_MAJOR=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
    if [ "$NODE_MAJOR" -lt 14 ]; then
        print_err "Node.js v$NODE_MAJOR is too old! Minimum v14 required."
        print_warn "Upgrading to Node.js 20..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
        sudo apt-get install -y nodejs
    else
        print_status "Node.js $(node -v) is ready!"
    fi
fi

# 2️⃣ Check Cloudflared
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
    print_status "Cloudflared $(cloudflared --version) is ready!"
fi

# 3️⃣ Setup Directory
echo -e "${YELLOW}📁 Setting up project directory...${NC}"
mkdir -p ~/web && cd ~/web

# 4️⃣ Download Server Code
echo -e "${YELLOW}📥 Downloading latest server.js...${NC}"
curl -L -o server.js "https://raw.githubusercontent.com/VathanarubanShayarukshan/remote_cmd/refs/heads/main/server%20V1.js"
if [ $? -ne 0 ] || [ ! -s server.js ]; then
    print_err "Failed to download server.js!"
    exit 1
fi
print_status "Downloaded successfully!"

# 5️⃣ Syntax Check
echo -e "${YELLOW}✅ Checking JavaScript syntax...${NC}"
if ! node --check server.js; then
    print_err "Syntax error in server.js! Check the code before running."
    exit 1
fi
print_status "Syntax OK!"

# 6️⃣ Kill Old Processes
echo -e "${YELLOW}🛑 Stopping old instances...${NC}"
pkill -f "node server.js" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2

# 7️⃣ Start Server
echo -e "${YELLOW}🚀 Starting Node.js server...${NC}"
nohup node server.js < /dev/null > output.log 2>&1 & disown
sleep 2

if pgrep -f "node server.js" > /dev/null; then
    print_status "Server running on port 1212!"
else
    print_err "Server failed to start! Check output.log:"
    tail -5 output.log
    exit 1
fi

# 8️⃣ Start Cloudflare Tunnel
echo -e "${YELLOW}☁️ Starting Cloudflare Quick Tunnel...${NC}"
nohup cloudflared tunnel --url http://localhost:1212 < /dev/null > tunnel.log 2>&1 & disown
sleep 5

# 9️⃣ Extract & Show URL
TUNNEL_URL=$(grep -oE 'https://[^ ]+\.(cfargotunnel|trycloudflare)\.com' tunnel.log 2>/dev/null | head -1)
if [ -n "$TUNNEL_URL" ]; then
    echo -e "\n${GREEN}🎉 SUCCESS! Your VPS Terminal is LIVE!${NC}"
    echo -e "${CYAN}🔗 Public URL: ${TUNNEL_URL}${NC}"
    echo -e "${YELLOW}💡 Tip: Use Ctrl+Shift+R in browser for hard refresh.${NC}"
else
    print_warn "Tunnel URL not ready yet. Check tunnel.log:"
    tail -10 tunnel.log
fi

echo -e "\n${GREEN}✅ Auto-setup complete!${NC}"
echo -e "${BLUE}📁 Logs: ~/web/output.log | ~/web/tunnel.log${NC}"
echo -e "${BLUE}🔄 Restart: pkill -f 'node server.js'; pkill -f 'cloudflared'; bash ~/web/auto-setup.sh${NC}"
