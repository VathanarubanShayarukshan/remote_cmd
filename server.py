#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =====================================================================
#  ⚡ VPS WEB TERMINAL + MCP SERVER — Python Version (server.py)
# =====================================================================
#  Full Python conversion of "server V1.js". ONE process, ONE port,
#  ONE single MCP URL for AI:
#
#    🌐 Web Terminal : http://localhost:1212/vps     (same UI as before)
#    🤖 MCP Endpoint : http://localhost:1212/mcp     (Streamable HTTP)
#
#  After cloudflared tunnel → AI connects to:
#    https://<your-tunnel>.trycloudflare.com/mcp
#
#  AI tools (terminal + files opened with 777 permission):
#    run_command, interrupt_command, get_terminal_status,
#    read_file, write_file, list_directory,
#    upload_file(base64), download_file(base64), set_permission
#
#  Env vars:
#    VPS_PORT   (default 1212)
#    VPS_TOKEN  (optional; if set, every request needs X-API-Token header)
# =====================================================================

import os
import sys
import json
import time
import base64
import signal
import shutil
import asyncio
import threading
import subprocess
import traceback
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ----------------------------- Config -------------------------------
PORT = int(os.environ.get("VPS_PORT", "1212"))
MCP_PATH = "/mcp"
WEB_PATH = "/vps"
API_TOKEN = os.environ.get("VPS_TOKEN", "")

# ------------------------- Terminal State ----------------------------
STATE_LOCK = threading.RLock()
CURRENT_CWD = os.path.expanduser("~") or "/root"
OUTPUT_BUFFER = ""
IS_RUNNING = False
ACTIVE_CHILD = None          # subprocess.Popen
CWD_TOKEN = "___CWD___"


def set_perm_777(target: str):
    """chmod 777 so AI can fully use terminal dirs & files."""
    try:
        os.chmod(target, 0o777)
    except Exception:
        pass


def resolve_path(path_str: str) -> str:
    """Relative paths resolve from the live terminal CWD."""
    p = Path(path_str or ".")
    if not p.is_absolute():
        p = Path(CURRENT_CWD) / p
    return str(p.resolve())


def start_command(command: str):
    """Spawn bash in a NEW process group (== detached:true in node)."""
    global ACTIVE_CHILD, IS_RUNNING, OUTPUT_BUFFER

    with STATE_LOCK:
        if ACTIVE_CHILD and ACTIVE_CHILD.poll() is None:
            try:
                os.killpg(os.getpgid(ACTIVE_CHILD.pid), signal.SIGKILL)
            except Exception:
                try:
                    ACTIVE_CHILD.kill()
                except Exception:
                    pass

        OUTPUT_BUFFER = ""
        IS_RUNNING = True
        cwd_snapshot = CURRENT_CWD.replace("'", "'\\''")
        wrapped = f"cd '{cwd_snapshot}' && {command} ; echo -n \"{CWD_TOKEN}\" ; pwd"

        ACTIVE_CHILD = subprocess.Popen(
            ["/bin/bash", "-c", wrapped],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            bufsize=0,
        )
    threading.Thread(target=_read_output, args=(ACTIVE_CHILD,), daemon=True).start()


def _read_output(child):
    global OUTPUT_BUFFER, IS_RUNNING, ACTIVE_CHILD, CURRENT_CWD
    try:
        while True:
            raw = child.stdout.read(4096)
            if not raw:
                break
            with STATE_LOCK:
                OUTPUT_BUFFER += raw.decode("utf-8", errors="replace")
    except Exception:
        pass
    finally:
        try:
            child.wait()
        except Exception:
            pass
        with STATE_LOCK:
            idx = OUTPUT_BUFFER.rfind(CWD_TOKEN)
            if idx != -1:
                parsed = OUTPUT_BUFFER[idx + len(CWD_TOKEN):].strip()
                OUTPUT_BUFFER = OUTPUT_BUFFER[:idx]
                if parsed and os.path.isdir(parsed):
                    CURRENT_CWD = parsed
                    set_perm_777(parsed)
            IS_RUNNING = False
            if ACTIVE_CHILD is child:
                ACTIVE_CHILD = None


def interrupt_running():
    """Ctrl+C the whole process group (like kill(-pid, SIGINT))."""
    global IS_RUNNING
    with STATE_LOCK:
        if ACTIVE_CHILD and ACTIVE_CHILD.poll() is None:
            try:
                os.killpg(os.getpgid(ACTIVE_CHILD.pid), signal.SIGINT)
            except Exception:
                try:
                    ACTIVE_CHILD.send_signal(signal.SIGINT)
                except Exception:
                    pass
            OUTPUT_BUFFER += "\n[Process Interrupted]\n"
            IS_RUNNING = False
            return "[Process Interrupted]"
    return "Nothing is running."


# =====================================================================
#  MCP SERVER (FastMCP) — tools for AI
# =====================================================================
MCP_AVAILABLE = False
mcp_app = None
try:
    from mcp.server.fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    print("⚠️  'mcp' package missing -> pip install mcp (MCP disabled)")

if MCP_AVAILABLE:
    mcp_app = FastMCP(
        name="VPS Terminal MCP",
        instructions=(
            "You have FULL access to this VPS. Terminal and all files are "
            "opened with 777 permissions for AI use. Use run_command for any "
            "shell task; the working directory persists between calls."
        ),
    )

    @mcp_app.tool()
    def run_command(command: str, wait: bool = True) -> str:
        """Run a linux command on the VPS. CWD persists like a real shell
        (cd works across calls). Returns the full output when wait=True."""
        start_command(command)
        if not wait:
            return "Command started in background."
        deadline = time.time() + 120
        while time.time() < deadline:
            with STATE_LOCK:
                if not IS_RUNNING:
                    return OUTPUT_BUFFER or "(no output)"
            time.sleep(0.2)
        with STATE_LOCK:
            return (OUTPUT_BUFFER or "(no output)") + \
                   "\n[still running — use get_terminal_status / interrupt_command]"

    @mcp_app.tool()
    def interrupt_command() -> str:
        """Send Ctrl+C (SIGINT) to the currently running command."""
        return interrupt_running()

    @mcp_app.tool()
    def get_terminal_status() -> str:
        """Get cwd, running state and live terminal output buffer."""
        with STATE_LOCK:
            return json.dumps({"cwd": CURRENT_CWD, "isRunning": IS_RUNNING,
                               "output": OUTPUT_BUFFER}, indent=2)

    @mcp_app.tool()
    def read_file(path: str) -> str:
        """Read any file on the VPS (relative path = from terminal CWD)."""
        try:
            real = resolve_path(path)
            set_perm_777(real)
            return Path(real).read_text(errors="replace")
        except Exception as e:
            return f"ERROR: {e}"

    @mcp_app.tool()
    def write_file(path: str, content: str) -> str:
        """Create/overwrite any file on the VPS with 777 permission."""
        try:
            real = resolve_path(path)
            Path(real).parent.mkdir(parents=True, exist_ok=True)
            Path(real).write_text(content)
            set_perm_777(real)
            return f"Written {len(content)} bytes to {real} (mode 777)"
        except Exception as e:
            return f"ERROR: {e}"

    @mcp_app.tool()
    def list_directory(path: str = ".") -> str:
        """List files/folders in a directory (default: terminal CWD)."""
        try:
            real = resolve_path(path)
            entries = sorted(os.scandir(real), key=lambda x: x.name)
            lines = [("DIR  " if e.is_dir() else "FILE ") + e.name for e in entries]
            return f"CWD: {real}\n" + ("\n".join(lines) or "(empty)")
        except Exception as e:
            return f"ERROR: {e}"

    @mcp_app.tool()
    def upload_file(filename: str, base64_content: str) -> str:
        """Write a binary/text file (base64) into the current terminal dir, mode 777."""
        try:
            safe = os.path.basename(filename)
            real = os.path.join(CURRENT_CWD, safe)
            with open(real, "wb") as f:
                f.write(base64.b64decode(base64_content))
            set_perm_777(real)
            return f'Uploaded "{safe}" to {real} (mode 777)'
        except Exception as e:
            return f"ERROR: {e}"

    @mcp_app.tool()
    def download_file(path: str) -> str:
        """Return a file from the VPS as base64 text."""
        try:
            real = resolve_path(path)
            return base64.b64encode(Path(real).read_bytes()).decode()
        except Exception as e:
            return f"ERROR: {e}"

    @mcp_app.tool()
    def set_permission(path: str, mode: str = "777") -> str:
        """chmod any file/folder (recursive). Default 777 for AI full use."""
        try:
            real = resolve_path(path)
            perm = int(mode, 8)
            os.chmod(real, perm)
            if os.path.isdir(real):
                for root, dirs, files in os.walk(real):
                    for d in dirs + files:
                        try:
                            os.chmod(os.path.join(root, d), perm)
                        except Exception:
                            pass
            return f"chmod {mode} applied on {real}"
        except Exception as e:
            return f"ERROR: {e}"


# =====================================================================
#  MCP Streamable-HTTP bridge (ASGI app driven inside a private
#  asyncio loop, called from our plain-ThreadingHTTPServer handler)
# =====================================================================
_mcp_manager = None
_mcp_loop = None

if MCP_AVAILABLE:
    def _mcp_loop_thread():
        """Start ASGI session manager in its own event loop thread."""
        global _mcp_manager, _mcp_loop

        async def _boot():
            global _mcp_manager
            from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

            mgr = StreamableHTTPSessionManager(
                app=mcp_app._mcp_server,
                event_store=None,
                json_response=True,   # simple JSON replies (works with all clients)
                stateless=True,       # perfect for a single MCP URL
            )
            _mcp_manager = mgr

            # run() is an async context manager that keeps a task group alive
            async with mgr.run():
                # park forever — handle_request is driven from HTTP threads
                await asyncio.Event().wait()

        _mcp_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_mcp_loop)
        try:
            _mcp_loop.run_until_complete(_boot())
        except Exception:
            traceback.print_exc()

    threading.Thread(target=_mcp_loop_thread, daemon=True, name="mcp-loop").start()


def call_mcp_http(method: str, body: bytes, query: str, headers: list):
    """Drive the ASGI MCP app from a sync thread; returns (status, headers, body)."""
    global _mcp_manager
    if _mcp_manager is None or _mcp_loop is None:
        for _ in range(100):  # wait up to 10s for boot
            if _mcp_manager is not None:
                break
            time.sleep(0.1)
        if _mcp_manager is None:
            return 503, [(b"content-type", b"application/json")], \
                   json.dumps({"error": "MCP manager not ready"}).encode()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "path": MCP_PATH,
        "raw_path": MCP_PATH.encode(),
        "query_string": query.encode(),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        "client": ("127.0.0.1", 0),
        "server": ("localhost", PORT),
        "root_path": "",
    }

    req_events = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        if req_events:
            return req_events.pop(0)
        return {"type": "http.disconnect"}

    result = {"status": None, "headers": [], "body": bytearray()}

    async def send(message):
        if message["type"] == "http.response.start":
            result["status"] = message["status"]
            result["headers"] = list(message.get("headers", []))
        elif message["type"] == "http.response.body":
            result["body"] += message.get("body", b"")

    async def _run():
        await _mcp_manager.handle_request(scope, receive, send)

    fut = asyncio.run_coroutine_threadsafe(_run(), _mcp_loop)
    fut.result(timeout=180)
    return result["status"], result["headers"], bytes(result["body"])


# =====================================================================
#  Web UI HTML (same look & feel as the original Node version)
# =====================================================================
WEB_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VPS Web Terminal</title>
<style>
body{background:#1a1a1a;color:#00ff00;font-family:'Courier New',monospace;margin:20px}
.container{max-width:900px;margin:0 auto;background:#262626;padding:20px;border-radius:8px;box-shadow:0 4px 10px rgba(0,0,0,.5)}
h2{color:#fff;text-align:center;margin-top:0;border-bottom:2px solid #00ff00;padding-bottom:10px}
.path-banner{background:#333;padding:8px 12px;border-left:4px solid #00ff00;margin-bottom:15px;color:#00ffff;font-weight:bold;word-break:break-all}
#output{background:#000;height:180px;overflow-y:auto;padding:15px;border-radius:4px;white-space:pre-wrap;margin-bottom:15px;border:1px solid #444;color:#ddd}
.v-keys{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;background:#222;padding:8px;border-radius:4px;border:1px solid #444}
.v-keys button{background:#3a3a3a;color:#fff;border:1px solid #555;padding:6px 14px;font-family:monospace;font-size:12px;font-weight:bold;border-radius:4px;cursor:pointer}
.input-row{display:flex;gap:10px;margin-bottom:20px;align-items:center;flex-wrap:wrap}
input[type=text]{flex:1;min-width:200px;background:#000;color:#00ff00;border:1px solid #00ff00;padding:10px;font-family:monospace;font-size:14px;border-radius:4px}
button.exec-btn{background:#00ff00;color:#000;border:none;padding:10px 20px;font-family:monospace;font-weight:bold;cursor:pointer;border-radius:4px;font-size:14px}
.btn-stop{background:#ff3333!important;color:#fff!important;display:none}
.tools-section{display:grid;grid-template-columns:1fr 1fr;gap:20px;background:#333;padding:15px;border-radius:4px;border:1px solid #555}
.tool-box{display:flex;flex-direction:column;gap:10px}
.tool-box h3{margin:0;color:#fff;font-size:16px}
.mcp-banner{background:#002b33;border:1px solid #00ffff;color:#00ffff;padding:10px 12px;border-radius:4px;margin-top:15px;font-size:13px;word-break:break-all}
.mcp-banner code{background:#000;padding:2px 6px;border-radius:3px;cursor:pointer}
</style>
</head>
<body>
<div class="container">
<h2>&#9889; VPS WEB TERMINAL (Python + MCP)</h2>
<div class="path-banner" id="currentPath">CWD: Connecting...</div>
<div id="output">Terminal System Ready...</div>

<div class="v-keys">
<button onclick="stopCommand()">CTRL+C</button>
<button onclick="clearTerminal()">Ctrl+L (Clear)</button>
<button onclick="insertText(' --help')">--help</button>
</div>

<div class="input-row">
<span style="font-weight:bold">$</span>
<input type="text" id="cmdInput" placeholder="Enter linux command..." autofocus>
<button id="execBtn" class="exec-btn" onclick="runCommand()">EXECUTE</button>
<button id="stopBtn" class="exec-btn btn-stop" onclick="stopCommand()">STOP (Ctrl+C)</button>
</div>

<div class="tools-section">
<div class="tool-box"><h3>&#128194; Upload File</h3>
<input type="file" id="fileInput">
<button id="uploadBtn" onclick="uploadFile()" style="background:#00ffff">UPLOAD</button></div>
<div class="tool-box"><h3>&#128229; Download File</h3>
<input type="text" id="dlPathInput" placeholder="filename.txt or full path">
<button onclick="downloadFile()" style="background:#ffff00">DOWNLOAD</button></div>
</div>

<div class="mcp-banner">&#129302; <b>MCP URL for AI (single url):</b><br>
<code id="mcpUrl" onclick="copyMcp()" title="Click to copy">loading...</code></div>
</div>

<script>
const cmdInput=document.getElementById('cmdInput'),outputDiv=document.getElementById('output'),
pathBanner=document.getElementById('currentPath'),execBtn=document.getElementById('execBtn'),
stopBtn=document.getElementById('stopBtn');
let activeCwd='',pollTimeout=null,pollIntervalMs=1500;
document.getElementById('mcpUrl').innerText=location.origin+'/mcp';
function copyMcp(){navigator.clipboard.writeText(location.origin+'/mcp');alert('MCP URL copied!');}
cmdInput.addEventListener('keydown',e=>{if(e.key==='Enter')runCommand();});
async function heartbeat(){
 try{
  const res=await fetch('/api/read?t='+Date.now());
  if(!res.ok)throw 0;
  const d=await res.json();
  pathBanner.innerText='CWD: '+d.cwd;pathBanner.style.color='#00ff00';activeCwd=d.cwd;
  if(d.output){outputDiv.innerText=d.output;outputDiv.scrollTop=outputDiv.scrollHeight;}
  if(d.isRunning){execBtn.style.display='none';stopBtn.style.display='inline-block';cmdInput.disabled=true;pollIntervalMs=300;}
  else{execBtn.style.display='inline-block';stopBtn.style.display='none';cmdInput.disabled=false;pollIntervalMs=1500;}
 }catch(e){pathBanner.innerText='Connecting to Backend...';pathBanner.style.color='#ff9900';}
 pollTimeout=setTimeout(heartbeat,pollIntervalMs);
}
function insertText(t){cmdInput.value+=t;cmdInput.focus();}
function clearTerminal(){outputDiv.innerText='';fetch('/api/clear-buffer',{method:'POST'});}
function runCommand(){const c=cmdInput.value.trim();if(!c)return;cmdInput.value='';outputDiv.innerText='';pollIntervalMs=300;
 fetch('/api/execute',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:c})}).then(()=>heartbeat());}
function stopCommand(){fetch('/api/interrupt',{method:'POST'}).then(()=>{pollIntervalMs=300;heartbeat();});}
function uploadFile(){const fb=document.getElementById('fileInput');if(!fb.files.length)return alert('Select file!');
 const f=fb.files[0],btn=document.getElementById('uploadBtn');btn.disabled=true;
 fetch('/api/upload',{method:'POST',headers:{'file-name':encodeURIComponent(f.name),'cwd':encodeURIComponent(activeCwd)},body:f})
 .then(r=>r.json()).then(d=>{outputDiv.innerText='System: '+d.message;fb.value='';}).finally(()=>btn.disabled=false);}
function downloadFile(){const p=document.getElementById('dlPathInput').value.trim();if(!p)return alert('Enter file path!');
 window.open('/api/download?path='+encodeURIComponent(p),'_blank');}
heartbeat();
</script>
</body>
</html>"""


# =====================================================================
#  HTTP Handler — routes: / , /vps , /api/* , /mcp
# =====================================================================
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "VPSPythonServer/2.0"

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {self.command} {self.path}", flush=True)

    # ---------- helpers ----------
    def _check_token(self):
        if not API_TOKEN:
            return True
        hdr = self.headers.get("X-API-Token", "")
        auth = self.headers.get("Authorization", "").replace("Bearer ", "")
        qtok = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return API_TOKEN in (hdr, auth, qtok)

    def _send(self, status, ctype, data, extra_headers=None):
        if isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or []):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, obj):
        self._send(status, "application/json", json.dumps(obj))

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    # ---------- routes ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        route = url.path.rstrip("/") or "/"

        if route in ("/", ""):
            self.send_response(302)
            self.send_header("Location", WEB_PATH)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if route == WEB_PATH:
            self._send(200, "text/html; charset=utf-8", WEB_HTML)
            return

        if route == "/api/read":
            with STATE_LOCK:
                self._json(200, {"output": OUTPUT_BUFFER, "cwd": CURRENT_CWD,
                                 "isRunning": IS_RUNNING})
            return

        if route == "/api/download":
            if not self._check_token():
                self._json(401, {"error": "unauthorized"})
                return
            fp = parse_qs(url.query).get("path", [""])[0]
            real = resolve_path(fp) if fp else ""
            if real and os.path.isfile(real):
                size = os.path.getsize(real)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{os.path.basename(real)}"')
                self.send_header("Content-Length", str(size))
                self.end_headers()
                with open(real, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            else:
                self._send(404, "text/plain", "File not found.")
            return

        if route == MCP_PATH or route.startswith(MCP_PATH + "/"):
            self._proxy_mcp("GET", b"")
            return

        self._send(404, "text/plain", "Not Found")

    def do_POST(self):
        url = urlparse(self.path)
        route = url.path.rstrip("/") or "/"
        body = self._read_body()

        if route == "/api/clear-buffer":
            global OUTPUT_BUFFER
            with STATE_LOCK:
                OUTPUT_BUFFER = ""
            self._send(200, "application/json", "{}")
            return

        if route == "/api/interrupt":
            self._json(200, {"status": interrupt_running()})
            return

        if route == "/api/execute":
            if not self._check_token():
                self._json(401, {"error": "unauthorized"})
                return
            try:
                cmd = json.loads(body.decode() or "{}").get("command", "")
            except Exception:
                self._json(400, {"error": "bad json"})
                return
            if cmd:
                start_command(cmd)
            self._json(200, {"status": "started"})
            return

        if route == "/api/autocomplete":
            try:
                text = json.loads(body.decode() or "{}").get("text", "")
            except Exception:
                self._json(400, {"error": "bad json"})
                return
            last = text.split(" ")[-1] if text else ""
            try:
                out = subprocess.run(
                    ["/bin/bash", "-c",
                     f"cd \"{CURRENT_CWD}\" && compgen -f \"{last}\""],
                    capture_output=True, text=True, timeout=5).stdout
                lst = [os.path.basename(x) for x in out.splitlines() if x]
                isdir = len(lst) == 1 and os.path.isdir(os.path.join(CURRENT_CWD, lst[0]))
                self._json(200, {"matches": lst, "isDir": isdir})
            except Exception:
                self._json(200, {"matches": [], "isDir": False})
            return

        if route == "/api/upload":
            if not self._check_token():
                self._json(401, {"error": "unauthorized"})
                return
            fname = unquote(self.headers.get("file-name", "file.txt"))
            tcwd = unquote(self.headers.get("cwd", "") or "") or CURRENT_CWD
            target = os.path.join(tcwd, os.path.basename(fname))
            with open(target, "wb") as f:
                f.write(body)
            set_perm_777(target)
            self._json(200, {"success": True,
                             "message": f'Uploaded "{fname}" successfully.'})
            return

        if route == MCP_PATH or route.startswith(MCP_PATH + "/"):
            self._proxy_mcp("POST", body)
            return

        self._send(404, "text/plain", "Not Found")

    def do_DELETE(self):
        url = urlparse(self.path)
        if url.path.rstrip("/") == MCP_PATH:
            self._proxy_mcp("DELETE", self._read_body())
            return
        self._send(404, "text/plain", "Not Found")

    # ---------- MCP proxy ----------
    def _proxy_mcp(self, method, body):
        if not MCP_AVAILABLE:
            self._json(500, {"error": "pip install mcp to enable MCP endpoint"})
            return
        if not self._check_token():
            self._json(401, {"error": "unauthorized. Send X-API-Token header."})
            return
        headers = [(k, v) for k, v in self.headers.items()]
        try:
            status, resp_headers, resp_body = call_mcp_http(
                method, body, urlparse(self.path).query, headers)
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": str(e)})
            return
        self.send_response(status)
        sent_ct = False
        for k, v in resp_headers:
            ks, vs = k.decode(), v.decode()
            if ks.lower() in ("content-length", "transfer-encoding"):
                continue
            if ks.lower() == "content-type":
                sent_ct = True
            self.send_header(ks, vs)
        if not sent_ct:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)


# =====================================================================
def main():
    print("=" * 62)
    print(f"⚡ VPS Python Server  |  Port: {PORT}")
    print(f"🌐 Web Terminal : http://localhost:{PORT}{WEB_PATH}")
    print(f"🤖 MCP Endpoint : http://localhost:{PORT}{MCP_PATH}")
    print(f"🔓 Files/CWD chmod 777 for AI use")
    if API_TOKEN:
        print("🔒 Token auth ENABLED (X-API-Token header required)")
    else:
        print("🔓 Token auth OFF (set VPS_TOKEN env to enable)")
    print("=" * 62, flush=True)

    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
