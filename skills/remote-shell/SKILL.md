---
name: remote-shell
description: Guide for using the Remote-Shell MCP server (single-URL Streamable HTTP) that gives Claude full shell + file access to a remote Linux or Windows machine over a Cloudflare tunnel. Use when the user asks to run commands, read/write/move/delete files, inspect a system, or manage a remote box through the remote-shell MCP tools (run_command, read_file, write_file, list_directory, file_info, delete_path, move_path, make_directory, system_info).
---

# Remote-Shell MCP — AI Usage Guide

This skill tells you how to drive the **Remote-Shell MCP server**: a single-URL
(Streamable HTTP) endpoint that exposes a shell and full file access on a remote
machine, published through a Cloudflare quick tunnel.

## 1. Connect

The server is one URL. Auth is a token, accepted either as a query param or a
Bearer header.

```
https://<tunnel-host>/mcp?token=<TOKEN>
```

Add it to Claude Code once:

```bash
claude mcp add --transport http remote-shell "https://<tunnel-host>/mcp?token=<TOKEN>"
```

- The URL and token are printed by `setup.sh` / `setup.bat` and saved in
  `.runtime/connection.txt` on the host.
- Quick-tunnel URLs change every restart. If calls fail with a network/DNS error,
  ask the user to re-run setup and give you the new URL.
- A `401` means the token is missing or wrong — re-check it.

## 2. Always start with `system_info`

Before doing anything else, call `system_info`. It returns `platform`
(`win32` / `linux` / `darwin`), `arch`, `hostname`, `user`, `home`, and
`python_version`. **The platform decides every command you write next.**

- `linux` / `darwin` → commands run in **bash**.
- `win32` → commands run in **cmd.exe** (not PowerShell). Use cmd syntax:
  `dir`, `type`, `copy`, `del`, `cd /d D:\path`, `%VAR%`. For PowerShell, wrap it:
  `powershell -NoProfile -Command "..."`.

## 3. The golden rule: cwd does NOT persist

Each `run_command` starts fresh in `cwd` (default: the home directory). A `cd`
inside one call is forgotten by the next call.

- Pass `cwd` explicitly on every call that needs a specific directory, **or**
- Use absolute paths, **or**
- Chain in one call: `cd /path && make && ./run`.

```json
{ "command": "git status", "cwd": "/home/user/project" }
```

(The separate web terminal at `/vps` *does* keep cwd between commands — that one
is for humans, not for you.)

## 4. Tool reference

| Tool | Purpose | Key args |
|------|---------|----------|
| `system_info` | OS / arch / user / home. Call first. | — |
| `run_command` | Run a shell command. | `command`, `cwd`, `timeout_ms` |
| `read_file` | Read a file (text or base64). | `path`, `encoding`, `offset`, `limit` |
| `write_file` | Write/append a file; makes parent dirs. | `path`, `content`, `encoding`, `append` |
| `list_directory` | List entries (dirs first). | `path` |
| `file_info` | Stat: exists, type, size, mode, times. | `path` |
| `make_directory` | mkdir -p. | `path`, `recursive` |
| `move_path` | Move/rename, cross-drive safe. | `source`, `destination` |
| `delete_path` | Delete file/dir. **Destructive.** | `path`, `recursive` |

### run_command
- Returns `exit_code`, `stdout`, `stderr`, `timed_out`, `truncated`.
- Default timeout **120 s**, max **600 s** (`timeout_ms`). Output capped at 512 KB.
- For long jobs, don't block: launch detached and poll, e.g. on Linux
  `nohup ./build.sh > build.log 2>&1 & echo $!`, then `read_file` the log.
- A non-zero `exit_code` is a normal result, not a tool error — read `stderr`.

### read_file / write_file
- Text defaults to `utf8` (read cap 1 MB). For **binary** (images, archives,
  executables) use `encoding: "base64"` (read cap 4 MB).
- Large text: page with `offset` (1-based first line) and `limit` (line count).
- `write_file` creates parent directories automatically; `append: true` appends.
- To copy a binary: `read_file` base64 → `write_file` base64 with the same string.

### delete_path / move_path
- `delete_path` needs `recursive: true` for non-empty directories. It refuses to
  delete a filesystem root.
- `move_path` works across drives and creates the destination's parent dirs.

## 5. Safety rules (important)

This server has **full access** to the machine. Act like a careful admin:

1. **Confirm destructive actions with the user first** — `delete_path`,
   `rm -rf`, overwriting important files, dropping databases, killing services.
2. Prefer reversible steps: move/rename aside instead of deleting when unsure.
3. Inspect before you change: `file_info` / `list_directory` / `read_file` first.
4. Never exfiltrate secrets (`.env`, keys, tokens) to third-party services.
5. Keep the token private; it is the only thing guarding the box.

## 6. Recipes

**Explore a project**
```
system_info → list_directory {path: home} → list_directory {path: project}
→ read_file {path: project/README.md}
```

**Edit a config safely**
```
read_file {path} → (show diff to user) → write_file {path, content}
→ run_command {command: "cat " + path}   # verify
```

**Run a build and tail the log**
```
run_command {command: "nohup make > build.log 2>&1 & echo started", cwd: project}
run_command {command: "tail -n 40 build.log", cwd: project}
```

**Fetch a binary to the remote box**
```
run_command {command: "curl -fsSL <url> -o /tmp/file.bin"}   # linux
file_info {path: "/tmp/file.bin"}
```

## 7. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Network/DNS error, tunnel gone | Quick tunnel restarted — get the new URL from the user. |
| `401 Unauthorized` | Missing/wrong token. |
| `timed_out: true` | Command exceeded timeout; run detached + poll, or raise `timeout_ms`. |
| `truncated: true` | Output > 512 KB; redirect to a file and `read_file` with offset/limit. |
| Weird Windows quoting | You're in cmd.exe. Use cmd syntax or wrap PowerShell explicitly. |
| `cd` "didn't work" next call | cwd doesn't persist — pass `cwd` on each call. |