#!/usr/bin/env python3
"""VPS Web Terminal — Python port of server V1.js.

Persistent-cwd web terminal + file upload/download, cross-platform.
Python standard library only. Run behind cloudflared:
    https://<tunnel>/vps?token=<token>
"""
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

PORT = int(os.environ.get('TERMINAL_PORT', '1212'))
HOST = os.environ.get('HOST', '127.0.0.1')
BASE_DIR = Path(__file__).resolve().parent
RUNTIME = BASE_DIR / '.runtime'
IS_WIN = os.name == 'nt'
OUTPUT_CAP = 2 * 1024 * 1024
CWD_MARKER = '___CWD___'
# Harmless bash warnings emitted when a shell starts in a deleted directory.
# The server recovers automatically; hide these lines from the web UI.
NOISE_RE = re.compile(r'^[^\n]*error retrieving current directory[^\n]*\n?', re.MULTILINE)

RUNTIME.mkdir(parents=True, exist_ok=True)


def load_token():
    env = os.environ.get('MCP_TOKEN', '').strip()
    if env:
        return env
    token_file = RUNTIME / 'token'
    try:
        t = token_file.read_text(encoding='utf8').strip()
        if t:
            return t
    except OSError:
        pass
    t = secrets.token_hex(24)
    token_file.write_text(t + '\n', encoding='utf8')
    try:
        os.chmod(token_file, 0o600)
    except OSError:
        pass
    return t


TOKEN = load_token()

# Shared terminal state (single active command, like the Node original).
STATE = {
    'cwd': str(Path.home()),
    'output': 'Terminal System Ready...',
    'running': False,
}
LOCK = threading.Lock()
ACTIVE = {'proc': None}


def _shell_argv(command):
    if IS_WIN:
        # Raw command line so cmd.exe /s /c preserves inner quotes (e.g. cd /d "path").
        comspec = os.environ.get('ComSpec', 'cmd.exe')
        return f'{comspec} /d /s /c "{command}"'
    bash = shutil.which('bash') or '/bin/sh'
    return [bash, '-c', command]


def _ensure_server_cwd():
    # If the launch directory was deleted/renamed, the process cwd is a dead
    # inode that child shells inherit -> bash "getcwd" errors. Move to home.
    try:
        os.getcwd()
    except OSError:
        try:
            os.chdir(str(Path.home()))
        except OSError:
            os.chdir('/')


def _wrap_command(command, cwd):
    if IS_WIN:
        return f'cd /d "{cwd}" && {command} & echo {CWD_MARKER} & cd'
    quoted = cwd.replace("'", "'\\''")
    return f"cd '{quoted}' && {command} ; echo -n \"{CWD_MARKER}\" ; pwd"


def _kill_tree(proc, sig=None):
    if proc is None or proc.poll() is not None:
        return
    try:
        if IS_WIN:
            subprocess.run(['taskkill', '/pid', str(proc.pid), '/T', '/F'],
                           capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, sig or signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _append_output(text):
    with LOCK:
        buf = STATE['output'] + text
        if len(buf) > OUTPUT_CAP:
            buf = buf[-OUTPUT_CAP:]
        STATE['output'] = buf


def _execute(command):
    with LOCK:
        old = ACTIVE['proc']
        cwd = STATE['cwd']
        STATE['output'] = ''
        STATE['running'] = True
    _kill_tree(old)

    # The persistent cwd may have been deleted/renamed since the last command.
    # Spawning a shell into a dead directory causes bash "getcwd" errors, so
    # fall back to home and remember the recovery.
    if not Path(cwd).is_dir():
        home = str(Path.home())
        _append_output(f'[Previous directory no longer exists; reset to {home}]\n')
        cwd = home
        with LOCK:
            STATE['cwd'] = home

    creationflags = 0x00000200 if IS_WIN else 0
    _ensure_server_cwd()
    try:
        proc = subprocess.Popen(
            _shell_argv(_wrap_command(command, cwd)), cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=not IS_WIN, creationflags=creationflags)
    except Exception as e:
        _append_output(f'Failed to start: {e}\n')
        with LOCK:
            STATE['running'] = False
        return
    with LOCK:
        ACTIVE['proc'] = proc

    def reader():
        collected = []
        for chunk in iter(lambda: proc.stdout.read(1024), b''):
            text = chunk.decode('utf8', errors='replace')
            collected.append(text)
            _append_output(text)
        proc.wait()
        full = ''.join(collected)
        idx = full.rfind(CWD_MARKER)
        if idx != -1:
            parsed = full[idx + len(CWD_MARKER):].strip()
            with LOCK:
                STATE['output'] = STATE['output'][:STATE['output'].rfind(CWD_MARKER)] \
                    if CWD_MARKER in STATE['output'] else STATE['output']
            if parsed and Path(parsed).exists():
                with LOCK:
                    STATE['cwd'] = parsed
        with LOCK:
            STATE['running'] = False
            ACTIVE['proc'] = None

    threading.Thread(target=reader, daemon=True).start()


def _autocomplete(text):
    words = text.split(' ')
    last = words[-1] if words else ''
    with LOCK:
        cwd = STATE['cwd']
    try:
        base = Path(cwd)
        prefix = last
        matches = []
        for entry in base.iterdir():
            if entry.name.startswith(prefix):
                matches.append(entry.name)
        matches.sort()
        is_dir = False
        if len(matches) == 1:
            is_dir = (base / matches[0]).is_dir()
        return {'matches': matches[:100], 'isDir': is_dir}
    except OSError:
        return {'matches': [], 'isDir': False}


def authorized(headers, query, cookies):
    import hmac
    h = headers.get('Authorization', '')
    if h.lower().startswith('bearer ') and hmac.compare_digest(h[7:].strip(), TOKEN):
        return True
    q = query.get('token', [''])[0]
    if q and hmac.compare_digest(q, TOKEN):
        return True
    c = cookies.get('rterm_token')
    if c and hmac.compare_digest(c.value, TOKEN):
        return True
    return False


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VPS Web Terminal</title>
    <style>
        body { background: #1a1a1a; color: #00ff00; font-family: 'Courier New', monospace; margin: 20px; }
        .container { max-width: 900px; margin: 0 auto; background: #262626; padding: 20px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
        h2 { color: #ffffff; text-align: center; margin-top: 0; border-bottom: 2px solid #00ff00; padding-bottom: 10px; }
        .path-banner { background: #333; padding: 8px 12px; border-left: 4px solid #00ff00; margin-bottom: 15px; color: #00ffff; font-weight: bold; word-break: break-all; }
        #output { background: #000; height: 180px; overflow-y: auto; padding: 15px; border-radius: 4px; white-space: pre-wrap; margin-bottom: 15px; border: 1px solid #444; color: #ddd; }
        .v-keys { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; background: #222; padding: 8px; border-radius: 4px; border: 1px solid #444; }
        .v-keys button { background: #3a3a3a; color: #fff; border: 1px solid #555; padding: 6px 14px; font-family: monospace; font-size: 12px; font-weight: bold; border-radius: 4px; cursor: pointer; }
        .v-keys button:active { background: #00ff00; color: #000; }
        .input-row { display: flex; gap: 10px; margin-bottom: 20px; align-items: center; flex-wrap: wrap; }
        input[type="text"] { flex: 1; min-width: 200px; background: #000; color: #00ff00; border: 1px solid #00ff00; padding: 10px; font-family: monospace; font-size: 14px; border-radius: 4px; }
        button.exec-btn { background: #00ff00; color: #000; border: none; padding: 10px 20px; font-family: monospace; font-weight: bold; cursor: pointer; border-radius: 4px; font-size: 14px; }
        .btn-stop { background: #ff3333 !important; color: #fff !important; display: none; }
        .tools-section { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; background: #333; padding: 15px; border-radius: 4px; border: 1px solid #555; }
        .tool-box { display: flex; flex-direction: column; gap: 10px; }
        .tool-box h3 { margin: 0; color: #fff; font-size: 16px; }
    </style>
</head>
<body>
    <div class="container">
        <h2>&#9889; VPS WEB TERMINAL</h2>
        <div class="path-banner" id="currentPath">CWD: Connecting...</div>
        <div id="output">Terminal System Ready...</div>

        <div class="v-keys">
            <button onclick="triggerTab()">TAB</button>
            <button onclick="stopCommand()">CTRL+C</button>
            <button onclick="clearTerminal()">Ctrl+L (Clear)</button>
            <button onclick="insertText(' --help')">--help</button>
        </div>

        <div class="input-row">
            <span style="font-weight:bold;">$</span>
            <input type="text" id="cmdInput" placeholder="Enter command..." autofocus>
            <button id="execBtn" class="exec-btn" onclick="runCommand()">EXECUTE</button>
            <button id="stopBtn" class="exec-btn btn-stop" onclick="stopCommand()">STOP (Ctrl+C)</button>
        </div>

        <div class="tools-section">
            <div class="tool-box">
                <h3>&#128193; Upload File</h3>
                <input type="file" id="fileInput">
                <button id="uploadBtn" onclick="uploadFile()" style="background:#00ffff;">UPLOAD</button>
            </div>
            <div class="tool-box">
                <h3>&#128229; Download File</h3>
                <input type="text" id="dlPathInput" placeholder="filename.txt or full path">
                <button onclick="downloadFile()" style="background:#ffff00;">DOWNLOAD</button>
            </div>
        </div>
    </div>

    <script>
        const TOKEN = "__TOKEN__";
        const cmdInput = document.getElementById('cmdInput');
        const outputDiv = document.getElementById('output');
        const pathBanner = document.getElementById('currentPath');
        const execBtn = document.getElementById('execBtn');
        const stopBtn = document.getElementById('stopBtn');
        let activeCwd = '';
        let pollTimeout = null;
        let pollIntervalMs = 1500;

        function auth(url) { return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN); }

        cmdInput.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') { e.preventDefault(); triggerTab(); }
            if (e.key === 'Enter') runCommand();
        });

        async function maintainHeartbeat() {
            try {
                const res = await fetch(auth('/api/read?t=' + Date.now()));
                if (!res.ok) throw new Error('HTTP ' + res.status);
                const data = await res.json();
                pathBanner.innerText = 'CWD: ' + data.cwd;
                pathBanner.style.color = '#00ff00';
                activeCwd = data.cwd;
                if (data.output) {
                    outputDiv.innerText = data.output;
                    outputDiv.scrollTop = outputDiv.scrollHeight;
                }
                if (data.isRunning) {
                    execBtn.style.display = 'none';
                    stopBtn.style.display = 'inline-block';
                    cmdInput.disabled = true;
                    pollIntervalMs = 300;
                } else {
                    execBtn.style.display = 'inline-block';
                    stopBtn.style.display = 'none';
                    cmdInput.disabled = false;
                    pollIntervalMs = 1500;
                }
            } catch (e) {
                pathBanner.innerText = 'Connecting to Backend...';
                pathBanner.style.color = '#ff9900';
            }
            if (pollTimeout) clearTimeout(pollTimeout);
            pollTimeout = setTimeout(maintainHeartbeat, pollIntervalMs);
        }

        function triggerTab() {
            fetch(auth('/api/autocomplete'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: cmdInput.value })
            })
            .then(res => res.json())
            .then(data => {
                if (data.matches && data.matches.length === 1) {
                    const words = cmdInput.value.split(' ');
                    words[words.length - 1] = data.matches[0];
                    cmdInput.value = words.join(' ') + (data.isDir ? '/' : ' ');
                } else if (data.matches && data.matches.length > 1) {
                    outputDiv.innerText += '\n' + data.matches.join('    ') + '\n';
                    outputDiv.scrollTop = outputDiv.scrollHeight;
                }
            });
        }

        function insertText(text) { cmdInput.value += text; cmdInput.focus(); }
        function clearTerminal() { outputDiv.innerText = ''; fetch(auth('/api/clear-buffer?t=' + Date.now()), { method: 'POST' }); }

        function runCommand() {
            const cmd = cmdInput.value.trim();
            if (!cmd) return;
            cmdInput.value = '';
            outputDiv.innerText = '';
            pollIntervalMs = 300;
            fetch(auth('/api/execute'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: cmd })
            }).then(() => { maintainHeartbeat(); });
        }

        function stopCommand() {
            fetch(auth('/api/interrupt'), { method: 'POST' }).then(() => { pollIntervalMs = 300; maintainHeartbeat(); });
        }

        function uploadFile() {
            const fileBox = document.getElementById('fileInput');
            if (fileBox.files.length === 0) return alert('Select file!');
            const file = fileBox.files[0];
            const uploadBtn = document.getElementById('uploadBtn');
            uploadBtn.disabled = true;
            fetch(auth('/api/upload'), {
                method: 'POST',
                headers: { 'file-name': encodeURIComponent(file.name), 'cwd': encodeURIComponent(activeCwd) },
                body: file
            })
            .then(res => res.json())
            .then(data => { outputDiv.innerText = 'System: ' + data.message; fileBox.value = ''; })
            .finally(() => { uploadBtn.disabled = false; });
        }

        function downloadFile() {
            const filePath = document.getElementById('dlPathInput').value.trim();
            if (!filePath) return alert('Enter file path!');
            window.open(auth('/api/download?path=' + encodeURIComponent(filePath)), '_blank');
        }

        maintainHeartbeat();
    </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'VPSWebTerminal/2.0'

    def log_message(self, fmt, *args):
        sys.stderr.write(f'[{time.strftime("%H:%M:%S")}] {fmt % args}\n')

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def _cookies(self):
        c = SimpleCookie()
        raw = self.headers.get('Cookie')
        if raw:
            c.load(raw)
        return c

    def _send(self, code, body, content_type='application/json', extra=None):
        data = body.encode('utf8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            length = 0
        return self.rfile.read(length) if length else b''

    def _unauthorized(self):
        self._send(401, json.dumps({'error': 'Unauthorized: missing or invalid token'}))

    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        query = self._query()
        cookies = self._cookies()

        if p == '/' :
            self.send_response(302)
            loc = '/vps'
            if query.get('token'):
                loc += '?token=' + query['token'][0]
            self.send_header('Location', loc)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

        if p == '/vps':
            if not authorized(self.headers, query, cookies):
                self._unauthorized()
                return
            html = HTML_TEMPLATE.replace('__TOKEN__', TOKEN)
            extra = {}
            if query.get('token'):
                extra['Set-Cookie'] = f'rterm_token={TOKEN}; Path=/; HttpOnly; SameSite=Lax'
            self._send(200, html, 'text/html; charset=utf-8', extra)
            return

        if not authorized(self.headers, query, cookies):
            self._unauthorized()
            return

        if p == '/api/read':
            with LOCK:
                output, cwd, running = STATE['output'], STATE['cwd'], STATE['running']
            payload = {'output': NOISE_RE.sub('', output), 'cwd': cwd, 'isRunning': running}
            self._send(200, json.dumps(payload))
            return

        if p == '/api/download':
            target = query.get('path', [''])[0]
            with LOCK:
                cwd = STATE['cwd']
            resolved = Path(target) if os.path.isabs(target) else Path(cwd) / target
            resolved = Path(os.path.abspath(str(resolved)))
            if resolved.is_file():
                data = resolved.read_bytes()
                self._send(200, data, 'application/octet-stream',
                           {'Content-Disposition': f'attachment; filename="{resolved.name}"'})
            else:
                self._send(404, 'File not found.', 'text/plain')
            return

        self._send(404, 'Not Found', 'text/plain')

    def do_POST(self):
        url = urlparse(self.path)
        p = url.path
        query = self._query()
        cookies = self._cookies()
        if not authorized(self.headers, query, cookies):
            self._unauthorized()
            return

        if p == '/api/clear-buffer':
            with LOCK:
                STATE['output'] = ''
            self._send(200, json.dumps({'ok': True}))
            return

        if p == '/api/interrupt':
            with LOCK:
                proc = ACTIVE['proc']
            _kill_tree(proc, None if IS_WIN else signal.SIGINT)
            _append_output('\n[Process Interrupted]\n')
            with LOCK:
                STATE['running'] = False
            self._send(200, json.dumps({'ok': True}))
            return

        if p == '/api/execute':
            try:
                payload = json.loads(self._read_body().decode('utf8'))
                command = str(payload.get('command', ''))
            except (ValueError, UnicodeDecodeError):
                self._send(400, json.dumps({'error': 'bad request'}))
                return
            if not command.strip():
                self._send(400, json.dumps({'error': 'command required'}))
                return
            threading.Thread(target=_execute, args=(command,), daemon=True).start()
            self._send(200, json.dumps({'status': 'started'}))
            return

        if p == '/api/autocomplete':
            try:
                payload = json.loads(self._read_body().decode('utf8'))
                text = str(payload.get('text', ''))
            except (ValueError, UnicodeDecodeError):
                text = ''
            self._send(200, json.dumps(_autocomplete(text)))
            return

        if p == '/api/upload':
            file_name = unquote(self.headers.get('file-name', 'upload.bin'))
            file_name = Path(file_name).name  # strip any path components
            target_cwd = unquote(self.headers.get('cwd', '')) or STATE['cwd']
            dest = Path(os.path.abspath(str(Path(target_cwd) / file_name)))
            body = self._read_body()
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
                self._send(200, json.dumps({'success': True, 'message': f'Uploaded "{file_name}" successfully.'}))
            except OSError as e:
                self._send(500, json.dumps({'success': False, 'message': str(e)}))
            return

        self._send(404, 'Not Found', 'text/plain')


def main():
    _ensure_server_cwd()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f'[{time.strftime("%H:%M:%S")}] VPS Web Terminal (Python) listening on http://{HOST}:{PORT}', flush=True)
    print(f'Open: http://{HOST}:{PORT}/vps?token={TOKEN}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()