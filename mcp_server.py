#!/usr/bin/env python3
"""Remote-Shell MCP Server — single-URL MCP endpoint (Streamable HTTP).

Shell execution + full file access for Claude / any MCP client.
Python standard library only. Run behind cloudflared:
    https://<tunnel>/mcp?token=<token>
"""
import base64
import hmac
import json
import os
import platform
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get('PORT', '1213'))
HOST = os.environ.get('HOST', '127.0.0.1')
BASE_DIR = Path(__file__).resolve().parent
RUNTIME = BASE_DIR / '.runtime'
IS_WIN = os.name == 'nt'
SERVER_INFO = {'name': 'remote-shell-mcp', 'version': '2.0.0'}
SUPPORTED_PROTOCOLS = ['2025-06-18', '2025-03-26', '2024-11-05']
MAX_BODY = 25 * 1024 * 1024
OUTPUT_CAP = 512 * 1024

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


def authorized(headers, query):
    h = headers.get('Authorization', '')
    if h.lower().startswith('bearer '):
        if hmac.compare_digest(h[7:].strip(), TOKEN):
            return True
    q = query.get('token', [''])[0]
    return bool(q) and hmac.compare_digest(q, TOKEN)


def _now_iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _uptime_seconds():
    try:
        if IS_WIN:
            import ctypes
            return int(ctypes.windll.kernel32.GetTickCount64() // 1000)
        return int(float(Path('/proc/uptime').read_text().split()[0]))
    except Exception:
        return None


def _kill_tree(proc):
    try:
        if IS_WIN:
            subprocess.run(['taskkill', '/pid', str(proc.pid), '/T', '/F'],
                           capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _shell_argv(command):
    if IS_WIN:
        # Pass a raw command line (not a list) so cmd.exe /s /c keeps inner
        # quotes intact; list args get backslash-escaped and break cmd.exe.
        comspec = os.environ.get('ComSpec', 'cmd.exe')
        return f'{comspec} /d /s /c "{command}"'
    bash = shutil.which('bash') or '/bin/sh'
    return [bash, '-c', command]


def _ensure_server_cwd():
    # If the directory this server was launched from was deleted/renamed, the
    # process cwd is a dead inode and every child shell inherits it, causing
    # bash "getcwd: cannot access parent directories". Move to a stable dir.
    try:
        os.getcwd()
    except OSError:
        try:
            os.chdir(str(Path.home()))
        except OSError:
            os.chdir('/')


def _usable_dir(requested):
    try:
        if requested and Path(requested).is_dir():
            return str(Path(requested).resolve())
    except OSError:
        pass
    return str(Path.home())


# ------------------------------ tool implementations ------------------------------

def run_command(args):
    command = str(args.get('command') or '')
    if not command.strip():
        raise ValueError('command is required')
    workdir = _usable_dir(os.path.abspath(str(args['cwd'])) if args.get('cwd') else None)
    try:
        timeout_ms = int(args.get('timeout_ms') or 120000)
    except (TypeError, ValueError):
        timeout_ms = 120000
    timeout_ms = max(1000, min(timeout_ms, 600000))

    result = {'exit_code': -1, 'stdout': '', 'stderr': '', 'cwd': workdir,
              'timed_out': False, 'truncated': False}
    creationflags = 0x00000200 if IS_WIN else 0  # CREATE_NEW_PROCESS_GROUP
    _ensure_server_cwd()
    try:
        proc = subprocess.Popen(
            _shell_argv(command), cwd=workdir, env=os.environ.copy(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=not IS_WIN, creationflags=creationflags)
    except Exception as e:
        result['stderr'] = str(e)
        return result

    lock = threading.Lock()
    state = {'size': 0, 'truncated': False}
    out_chunks, err_chunks = [], []

    def pump(stream, sink):
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            with lock:
                if state['size'] < OUTPUT_CAP:
                    take = min(len(chunk), OUTPUT_CAP - state['size'])
                    sink.append(chunk[:take])
                    state['size'] += take
                    if take < len(chunk):
                        state['truncated'] = True
                else:
                    state['truncated'] = True

    threads = [threading.Thread(target=pump, args=(proc.stdout, out_chunks), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, err_chunks), daemon=True)]
    for t in threads:
        t.start()
    try:
        proc.wait(timeout=timeout_ms / 1000)
    except subprocess.TimeoutExpired:
        result['timed_out'] = True
        _kill_tree(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    for t in threads:
        t.join(timeout=5)
    result['exit_code'] = proc.returncode if proc.returncode is not None else -1
    result['stdout'] = b''.join(out_chunks).decode('utf8', errors='replace')
    result['stderr'] = b''.join(err_chunks).decode('utf8', errors='replace')
    result['truncated'] = state['truncated']
    return result


def read_file(args):
    p = Path(os.path.abspath(str(args.get('path') or '')))
    encoding = 'base64' if args.get('encoding') == 'base64' else 'utf8'
    st = p.stat()
    if not p.is_file():
        raise ValueError(f'Not a regular file: {p}')
    if encoding == 'base64':
        cap = 4 * 1024 * 1024
        buf = p.read_bytes()
        return {'path': str(p), 'encoding': encoding, 'size_bytes': st.st_size,
                'truncated': len(buf) > cap,
                'content': base64.b64encode(buf[:cap]).decode('ascii')}
    cap = 1024 * 1024
    text = p.read_text(encoding='utf8', errors='replace')
    truncated = len(text) > cap
    if truncated:
        text = text[:cap]
    try:
        offset = int(args.get('offset') or 0)
        limit = int(args.get('limit') or 0)
    except (TypeError, ValueError):
        offset = limit = 0
    if offset > 0 or limit > 0:
        lines = text.split('\n')
        start = offset - 1 if offset > 0 else 0
        end = start + limit if limit > 0 else len(lines)
        return {'path': str(p), 'encoding': encoding, 'size_bytes': st.st_size,
                'truncated': truncated, 'total_lines': len(lines),
                'offset': start + 1, 'content': '\n'.join(lines[start:end])}
    return {'path': str(p), 'encoding': encoding, 'size_bytes': st.st_size,
            'truncated': truncated, 'content': text}


def write_file(args):
    p = Path(os.path.abspath(str(args.get('path') or '')))
    content = args.get('content')
    if not isinstance(content, str):
        raise ValueError('content (string) is required')
    encoding = 'base64' if args.get('encoding') == 'base64' else 'utf8'
    buf = base64.b64decode(content) if encoding == 'base64' else content.encode('utf8')
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = 'ab' if args.get('append') else 'wb'
    with open(p, mode) as f:
        f.write(buf)
    return {'path': str(p), 'bytes_written': len(buf), 'appended': bool(args.get('append'))}


def list_directory(args):
    p = Path(os.path.abspath(str(args.get('path') or Path.home())))
    dirents = list(p.iterdir())
    entries = []
    for d in dirents[:2000]:
        size = None
        try:
            size = d.stat().st_size
        except OSError:
            pass
        if d.is_dir():
            kind = 'dir'
        elif d.is_file():
            kind = 'file'
        elif d.is_symlink():
            kind = 'symlink'
        else:
            kind = 'other'
        entries.append({'name': d.name, 'type': kind, 'size_bytes': size})
    entries.sort(key=lambda e: (0 if e['type'] == 'dir' else 1, e['name'].lower()))
    return {'path': str(p), 'count': len(entries),
            'truncated': len(dirents) > 2000, 'entries': entries}


def file_info(args):
    p = Path(os.path.abspath(str(args.get('path') or '')))
    try:
        st = p.stat()
        lst = p.lstat()
        if p.is_dir():
            kind = 'dir'
        elif p.is_file():
            kind = 'file'
        else:
            kind = 'other'
        return {'path': str(p), 'exists': True, 'type': kind,
                'size_bytes': st.st_size, 'mode': '0' + format(st.st_mode & 0o777, 'o'),
                'is_symlink': p.is_symlink(),
                'modified': _now_iso(st.st_mtime), 'created': _now_iso(lst.st_ctime)}
    except OSError:
        return {'path': str(p), 'exists': False}


def delete_path(args):
    p = Path(os.path.abspath(str(args.get('path') or '')))
    if p == Path(p.anchor):
        raise ValueError('Refusing to delete filesystem root')
    if p.is_dir() and not p.is_symlink():
        if args.get('recursive'):
            shutil.rmtree(p)
        else:
            p.rmdir()
    else:
        p.unlink()
    return {'path': str(p), 'deleted': True}


def move_path(args):
    src = os.path.abspath(str(args.get('source') or ''))
    dst = os.path.abspath(str(args.get('destination') or ''))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dst)
    return {'source': src, 'destination': dst, 'moved': True}


def make_directory(args):
    p = Path(os.path.abspath(str(args.get('path') or '')))
    p.mkdir(parents=args.get('recursive', True) is not False, exist_ok=True)
    return {'path': str(p), 'created': True}


def system_info(_args):
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        user = 'unknown'
    _ensure_server_cwd()
    try:
        server_cwd = os.getcwd()
    except OSError:
        server_cwd = str(Path.home())
    return {'platform': sys.platform, 'arch': platform.machine(),
            'hostname': platform.node(), 'user': user,
            'home': str(Path.home()), 'default_cwd': str(Path.home()),
            'python_version': platform.python_version(),
            'uptime_seconds': _uptime_seconds(), 'server_cwd': server_cwd}


# ------------------------------ tool definitions ------------------------------

TOOLS = [
    {
        'name': 'run_command',
        'description': 'Execute a shell command on the remote machine (bash on Linux/macOS, cmd.exe on Windows). Returns exit_code, stdout, stderr. Each call starts in "cwd" (default: home dir) — cd does NOT persist between calls; pass cwd or use absolute paths. Default timeout 120s (max 600s). Output capped at 512KB.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'command': {'type': 'string', 'description': 'Shell command line to execute'},
                'cwd': {'type': 'string', 'description': 'Working directory (absolute path). Defaults to home directory.'},
                'timeout_ms': {'type': 'integer', 'description': 'Timeout in milliseconds (1000-600000). Default 120000.'}
            },
            'required': ['command']
        },
        'handler': run_command
    },
    {
        'name': 'read_file',
        'description': 'Read a file. Text (utf8) by default, capped at 1MB; use encoding="base64" for binary files (capped at 4MB). Optional offset/limit select lines (1-based) for large text files.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'Absolute or relative file path'},
                'encoding': {'type': 'string', 'enum': ['utf8', 'base64'], 'description': 'utf8 (default) or base64 for binary'},
                'offset': {'type': 'integer', 'description': 'First line to read (1-based, text only)'},
                'limit': {'type': 'integer', 'description': 'Number of lines to read (text only)'}
            },
            'required': ['path']
        },
        'handler': read_file
    },
    {
        'name': 'write_file',
        'description': 'Write or append a file with full access. Creates parent directories automatically. Use encoding="base64" to write binary content.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'Target file path'},
                'content': {'type': 'string', 'description': 'File content (text, or base64 when encoding=base64)'},
                'encoding': {'type': 'string', 'enum': ['utf8', 'base64'], 'description': 'utf8 (default) or base64'},
                'append': {'type': 'boolean', 'description': 'Append instead of overwrite. Default false.'}
            },
            'required': ['path', 'content']
        },
        'handler': write_file
    },
    {
        'name': 'list_directory',
        'description': 'List directory entries (name, type, size). Directories first, alphabetical. Defaults to home directory. Max 2000 entries.',
        'inputSchema': {
            'type': 'object',
            'properties': {'path': {'type': 'string', 'description': 'Directory path. Defaults to home.'}}
        },
        'handler': list_directory
    },
    {
        'name': 'file_info',
        'description': 'Stat a path: existence, type, size, permission mode, symlink flag, timestamps.',
        'inputSchema': {
            'type': 'object',
            'properties': {'path': {'type': 'string', 'description': 'Path to inspect'}},
            'required': ['path']
        },
        'handler': file_info
    },
    {
        'name': 'delete_path',
        'description': 'Delete a file or directory. Set recursive=true for non-empty directories. DESTRUCTIVE — confirm with the user before deleting anything important.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'Path to delete'},
                'recursive': {'type': 'boolean', 'description': 'Required for non-empty directories'}
            },
            'required': ['path']
        },
        'handler': delete_path
    },
    {
        'name': 'move_path',
        'description': 'Move or rename a file/directory (works across drives). Creates destination parent dirs.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'source': {'type': 'string', 'description': 'Existing path'},
                'destination': {'type': 'string', 'description': 'New path'}
            },
            'required': ['source', 'destination']
        },
        'handler': move_path
    },
    {
        'name': 'make_directory',
        'description': 'Create a directory (recursive by default, like mkdir -p).',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'Directory to create'},
                'recursive': {'type': 'boolean', 'description': 'Create parents. Default true.'}
            },
            'required': ['path']
        },
        'handler': make_directory
    },
    {
        'name': 'system_info',
        'description': 'Get remote machine info: OS, architecture, hostname, user, home directory, python version. Call this first to learn the environment.',
        'inputSchema': {'type': 'object', 'properties': {}},
        'handler': system_info
    }
]

TOOL_MAP = {t['name']: t for t in TOOLS}


# ------------------------------ JSON-RPC / MCP ------------------------------

def rpc_result(rid, result):
    return {'jsonrpc': '2.0', 'id': rid, 'result': result}


def rpc_error(rid, code, message):
    return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': code, 'message': message}}


def handle_rpc(msg):
    method = msg.get('method')
    rid = msg.get('id')
    params = msg.get('params') or {}
    is_notification = rid is None

    if method == 'initialize':
        requested = params.get('protocolVersion')
        version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return rpc_result(rid, {
            'protocolVersion': version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': SERVER_INFO,
            'instructions': 'Remote shell + file access. Call system_info first. run_command does not persist cwd between calls — pass cwd explicitly. Confirm destructive operations with the user.'
        })
    if method in ('notifications/initialized', 'notifications/cancelled'):
        return None
    if method == 'ping':
        return rpc_result(rid, {})
    if method == 'tools/list':
        return rpc_result(rid, {'tools': [
            {'name': t['name'], 'description': t['description'], 'inputSchema': t['inputSchema']}
            for t in TOOLS]})
    if method == 'tools/call':
        tool = TOOL_MAP.get(params.get('name'))
        if not tool:
            return rpc_result(rid, {'content': [{'type': 'text', 'text': 'Unknown tool: ' + str(params.get('name'))}], 'isError': True})
        try:
            result = tool['handler'](params.get('arguments') or {})
            return rpc_result(rid, {'content': [{'type': 'text', 'text': json.dumps(result, indent=2, ensure_ascii=False)}]})
        except Exception as e:
            return rpc_result(rid, {'content': [{'type': 'text', 'text': f'Error: {e}'}], 'isError': True})
    if method == 'resources/list':
        return rpc_result(rid, {'resources': []})
    if method == 'prompts/list':
        return rpc_result(rid, {'prompts': []})
    if is_notification:
        return None
    return rpc_error(rid, -32601, f'Method not found: {method}')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'RemoteShellMCP/2.0'

    def log_message(self, fmt, *args):
        sys.stderr.write(f'[{datetime.now().isoformat(timespec="seconds")}] {fmt % args}\n')

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, Mcp-Session-Id, MCP-Protocol-Version')
        self.send_header('Access-Control-Expose-Headers', 'Mcp-Session-Id')

    def _send(self, code, body, content_type='application/json', extra_headers=None):
        data = body.encode('utf8') if isinstance(body, str) else body
        self.send_response(code)
        self._cors()
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == '/health':
            self._send(200, json.dumps({'ok': True, 'server': SERVER_INFO, 'tools': len(TOOLS)}))
            return
        if url.path == '/':
            html = ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>Remote-Shell MCP</title>'
                    '<style>body{background:#111;color:#0f0;font-family:monospace;padding:40px}a{color:#0ff}</style></head>'
                    '<body><h2>Remote-Shell MCP Server (Python)</h2><p>Status: ONLINE</p>'
                    '<p>MCP endpoint: <code>/mcp</code> (POST, JSON-RPC 2.0, Streamable HTTP)</p>'
                    '<p>Auth: <code>Authorization: Bearer &lt;token&gt;</code> or <code>?token=&lt;token&gt;</code></p>'
                    '<p>Tools: ' + ', '.join(t['name'] for t in TOOLS) + '</p>'
                    '<p><a href="/health">/health</a></p></body></html>')
            self._send(200, html, 'text/html; charset=utf-8')
            return
        if url.path == '/mcp':
            self._send(405, '', 'text/plain', {'Allow': 'POST, DELETE'})
            return
        self._send(404, 'Not Found', 'text/plain')

    def do_DELETE(self):
        url = urlparse(self.path)
        if url.path == '/mcp':
            self._send(200, '')
            return
        self._send(404, 'Not Found', 'text/plain')

    def do_POST(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path not in ('/mcp', '/'):
            self._send(404, 'Not Found', 'text/plain')
            return
        if not authorized(self.headers, query):
            self._send(401, json.dumps(rpc_error(None, -32001, 'Unauthorized: missing or invalid token')),
                       extra_headers={'WWW-Authenticate': 'Bearer'})
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._send(413, json.dumps(rpc_error(None, -32600, 'Body too large')))
            return
        raw = self.rfile.read(length) if length else b''
        try:
            msg = json.loads(raw.decode('utf8'))
        except (ValueError, UnicodeDecodeError):
            self._send(400, json.dumps(rpc_error(None, -32700, 'Parse error')))
            return
        session_header = self.headers.get('Mcp-Session-Id')
        try:
            if isinstance(msg, list):
                results = [r for r in (handle_rpc(m) for m in msg) if r is not None]
                if not results:
                    self._send(202, '')
                    return
                self._send(200, json.dumps(results))
                return
            result = handle_rpc(msg)
            headers = {}
            if msg.get('method') == 'initialize':
                headers['Mcp-Session-Id'] = session_header or str(uuid.uuid4())
            elif session_header:
                headers['Mcp-Session-Id'] = session_header
            if result is None:
                self._send(202, '', extra_headers=headers)
                return
            self._send(200, json.dumps(result), extra_headers=headers)
        except Exception as e:
            self.log_message('Handler error: %s', e)
            rid = msg.get('id') if isinstance(msg, dict) else None
            self._send(500, json.dumps(rpc_error(rid, -32603, 'Internal error')))


def main():
    _ensure_server_cwd()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f'[{datetime.now().isoformat(timespec="seconds")}] Remote-Shell MCP (Python) listening on http://{HOST}:{PORT}', flush=True)
    print(f'MCP endpoint: http://{HOST}:{PORT}/mcp  (token file: {RUNTIME / "token"})', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()