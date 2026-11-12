# ⚡ Remote-Shell MCP + Web Terminal (Python)

> 🌐 **One URL** gives Claude AI full shell + file access to your machine, from anywhere,
> through a Cloudflare tunnel. Plus a browser web terminal for you.
> 🐍 Pure Python (standard library only) · 🪟 Windows + 🐧 Linux · 🔑 Token-protected · 🔄 Runs in the background.

---

## What's inside

| File | What it does |
|------|--------------|
| `mcp_server.py` | **Single-URL MCP server** (Streamable HTTP) on port `1213`. Shell + full file access for Claude / any MCP client. |
| `remote_cmd.py` | **Web terminal** on port `1212` (the old `server V1.js`, ported to Python). Persistent cwd, upload/download, autocomplete. |
| `setup.sh` / `setup.bat` | Auto-install Python + cloudflared, start **everything in the background**, open Cloudflare tunnels, print the public URLs. |
| `stop.sh` / `stop.bat` | Stop the servers and tunnels. |
| `skills/remote-shell/SKILL.md` | AI guide skill that teaches Claude how to use the MCP tools. |
| `mcp-server.js`, `server V1.js` | Legacy Node.js versions (kept for reference; not used by the Python setup). |

Everything is **Python standard library only** — no `pip install`, no `node_modules`.

---

## 🚀 Quick start

### 🐧 Linux / VPS
```bash
chmod +x setup.sh stop.sh
./setup.sh
```

### 🪟 Windows
```bat
setup.bat
```

The setup script will:
1. Check / install **Python 3** and **cloudflared** (local binary, no admin needed).
2. Stop any old instances (including the legacy Node servers).
3. Start the MCP server, the web terminal, and **two Cloudflare quick tunnels** — all in the background.
4. Print your public URLs and save them to `.runtime/connection.txt`.

You'll get two links:

```
MCP URL (for Claude):   https://<random>.trycloudflare.com/mcp?token=<TOKEN>
Web Terminal (for you): https://<random>.trycloudflare.com/vps?token=<TOKEN>
```

> ⚠️ Quick-tunnel URLs are random and **change on every restart**. Re-run setup to get fresh URLs.
> The **token stays the same** (stored in `.runtime/token`).

---

## 🤖 Connect Claude

**Claude Code (CLI):**
```bash
claude mcp add --transport http remote-shell "https://<random>.trycloudflare.com/mcp?token=<TOKEN>"
```

**Any MCP client (Streamable HTTP):** point it at the MCP URL above. Auth also works
as a header: `Authorization: Bearer <TOKEN>`.

**Install the AI guide skill** (so Claude knows the rules — cwd, binary files, safety):
- The setup scripts auto-copy it to `~/.claude/skills/remote-shell/` (or `%USERPROFILE%\.claude\skills\remote-shell\`) when that folder exists.
- Or copy `skills/remote-shell/SKILL.md` there manually.

---

## 🧰 MCP tools

| Tool | Description |
|------|-------------|
| `system_info` | OS, arch, hostname, user, home, Python version. **Call this first.** |
| `run_command` | Run a shell command (bash on Linux, cmd.exe on Windows). `cwd`, `timeout_ms` (≤600s). |
| `read_file` | Read text (1 MB cap) or `base64` binary (4 MB cap); `offset`/`limit` for paging. |
| `write_file` | Write/append; creates parent dirs; `base64` for binary. |
| `list_directory` | List entries, directories first (max 2000). |
| `file_info` | Existence, type, size, mode, symlink, timestamps. |
| `make_directory` | `mkdir -p`. |
| `move_path` | Move/rename, cross-drive safe. |
| `delete_path` | Delete file/dir (`recursive` for non-empty). **Destructive.** |

**Key rule:** `run_command` does **not** keep `cwd` between calls — pass `cwd` or use absolute paths.

---

## 🛑 Stop / restart

```bash
./stop.sh        # Linux
stop.bat         :: Windows
```
Re-run `setup.sh` / `setup.bat` to start again (you'll get new tunnel URLs).

**Logs** live in `.runtime/`: `mcp.log`, `terminal.log`, `tunnel-mcp.log`, `tunnel-terminal.log`.

---

## ⚙️ Configuration (environment variables)

| Variable | Default | Meaning |
|----------|---------|---------|
| `PORT` | `1213` | MCP server port |
| `TERMINAL_PORT` | `1212` | Web terminal port |
| `HOST` | `127.0.0.1` | Bind address (tunnel connects locally) |
| `MCP_TOKEN` | auto | Override the auth token (else `.runtime/token`) |

---

## 🔒 Security notes

- Both services are **token-gated** (192-bit random token). Anyone with the URL **and** token gets full shell + file access — keep them private.
- The server binds to `127.0.0.1`; only the Cloudflare tunnel exposes it. No open inbound port on your router.
- This is intended for **your own machines**. Don't share the token publicly.
- For a stable URL, replace the quick tunnel with a named Cloudflare tunnel (`cloudflared tunnel login` + a config) — the servers don't change.

---

## 📁 Project layout

```
Remote-cmd-with-mcp/
├── mcp_server.py          # MCP server (Python)
├── remote_cmd.py          # Web terminal (Python)
├── setup.sh / setup.bat   # Install + run in background + tunnel
├── stop.sh  / stop.bat    # Stop everything
├── skills/remote-shell/SKILL.md
├── .runtime/              # token, logs, connection.txt (auto-created)
├── bin/                   # local cloudflared (auto-downloaded if needed)
└── mcp-server.js, server V1.js   # legacy Node versions
```

License: MIT