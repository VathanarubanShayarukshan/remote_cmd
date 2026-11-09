# ⚡ VPS Web Terminal + MCP (Python)

> 🌐 Cloudflare Tunnel + **Python** + Web UI + **MCP Server** = Remote Terminal & AI Access from Anywhere!  
> 📱 Mobile Friendly | 🔑 Simple UI | 📁 File Upload/Download | 🔄 Auto-complete  
> 🤖 **Single MCP URL for AI** — terminal + files with 777 permission

---

## 🆕 Python Version + MCP (new!)

| File | Purpose |
|------|---------|
| `server.py` | Full Python conversion of `server V1.js` — runs Web UI (`/vps`) **and** MCP server (`/mcp`) on ONE port (1212) |
| `setup_python.sh` | Single bash file for Linux/VPS — auto installs Python + mcp + cloudflared, downloads code, starts server + tunnel |
| `setup.bat` | Windows batch file — same automation for Windows PCs |

### 🚀 Run on VPS (one command)
```bash
curl -O https://raw.githubusercontent.com/VathanarubanShayarukshan/remote_cmd/refs/heads/main/setup_python.sh
chmod +x setup_python.sh && ./setup_python.sh
```

### 🪟 Run on Windows
Double-click `setup.bat` (or run it in cmd).

### 🤖 Single MCP URL for AI
After the script prints your tunnel URL, give AI tools this **one** url:
```
https://<your-tunnel>.trycloudflare.com/mcp
```
Example Claude Desktop / client config:
```json
{
  "mcpServers": {
    "vps": { "type": "url", "url": "https://<your-tunnel>.trycloudflare.com/mcp" }
  }
}
```

### 🛠️ MCP Tools exposed to AI (777 access)
- `run_command` — shell commands, CWD persists (cd works across calls)
- `interrupt_command` — Ctrl+C the running process group
- `get_terminal_status` — cwd / running state / live output
- `read_file`, `write_file`, `list_directory`
- `upload_file` (base64), `download_file` (base64)
- `set_permission` — chmod anything (default 777)

🔒 Optional security: set `VPS_TOKEN` env var → every request needs `X-API-Token` header.

---

## Legacy Node.js version (old)

> 🌐 Cloudflare Tunnel + Node.js + Web UI = Remote Terminal Access from Anywhere!

![Status](https://img.shields.io/badge/Status-Active-brightgreen)
![Node.js](https://img.shields.io/badge/Node.js-v14+-green)
![Cloudflare](https://img.shields.io/badge/Cloudflare-Tunnel-orange)
![License](https://img.shields.io/badge/License-MIT-blue)

> 💡 **Pro Tip**: GitHub adds a **📋 Copy button** to every code block! Just hover over any ```bash block and click the copy icon in the top-right corner! ✨

---

### 🔹 Step 1: Download Setup Script
```bash
curl -O https://raw.githubusercontent.com/VathanarubanShayarukshan/remote_cmd/refs/heads/main/setup.sh
chmod +x setup.sh
./setup.sh
