#!/usr/bin/env node
'use strict';
/* Remote-Shell MCP Server — single-URL MCP endpoint (Streamable HTTP).
 * Shell execution + full file access for Claude / any MCP client.
 * Zero dependencies. Run behind cloudflared: https://<tunnel>/mcp?token=<token>
 */
const http = require('http');
const fs = require('fs');
const fsp = fs.promises;
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const { spawn } = require('child_process');

const PORT = parseInt(process.env.PORT || '1213', 10);
const HOST = process.env.HOST || '127.0.0.1';
const RUNTIME = path.join(__dirname, '.runtime');
const IS_WIN = process.platform === 'win32';
const SERVER_INFO = { name: 'remote-shell-mcp', version: '1.0.0' };
const SUPPORTED_PROTOCOLS = ['2025-06-18', '2025-03-26', '2024-11-05'];
const MAX_BODY = 25 * 1024 * 1024;
const OUTPUT_CAP = 512 * 1024;

fs.mkdirSync(RUNTIME, { recursive: true });

function loadToken() {
    if (process.env.MCP_TOKEN && process.env.MCP_TOKEN.trim()) return process.env.MCP_TOKEN.trim();
    const file = path.join(RUNTIME, 'token');
    try {
        const t = fs.readFileSync(file, 'utf8').trim();
        if (t) return t;
    } catch (e) { /* generate below */ }
    const t = crypto.randomBytes(24).toString('hex');
    fs.writeFileSync(file, t + '\n', { mode: 0o600 });
    return t;
}
const TOKEN = loadToken();

function tokenEquals(a, b) {
    const ba = Buffer.from(String(a));
    const bb = Buffer.from(String(b));
    return ba.length === bb.length && crypto.timingSafeEqual(ba, bb);
}

function authorized(req, url) {
    const h = req.headers['authorization'];
    if (h && /^Bearer\s+/i.test(h) && tokenEquals(h.replace(/^Bearer\s+/i, '').trim(), TOKEN)) return true;
    const q = url.searchParams.get('token');
    if (q && tokenEquals(q, TOKEN)) return true;
    return false;
}

/* ------------------------------ tool implementations ------------------------------ */

function runCommand(args) {
    const command = String(args.command || '');
    if (!command.trim()) throw new Error('command is required');
    const workdir = args.cwd ? path.resolve(String(args.cwd)) : os.homedir();
    const timeout = Math.min(Math.max(parseInt(args.timeout_ms, 10) || 120000, 1000), 600000);
    return new Promise((resolve) => {
        const shell = IS_WIN ? (process.env.ComSpec || 'cmd.exe') : '/bin/bash';
        const shellArgs = IS_WIN ? ['/d', '/s', '/c', command] : ['-c', command];
        let child;
        try {
            child = spawn(shell, shellArgs, { cwd: workdir, env: process.env, detached: !IS_WIN, windowsHide: true });
        } catch (e) {
            resolve({ exit_code: -1, stdout: '', stderr: String(e && e.message || e), cwd: workdir, timed_out: false, truncated: false });
            return;
        }
        let stdout = '', stderr = '', truncated = false, timedOut = false, done = false;
        const timer = setTimeout(() => {
            timedOut = true;
            try {
                if (IS_WIN) spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
                else process.kill(-child.pid, 'SIGKILL');
            } catch (e) { try { child.kill('SIGKILL'); } catch (e2) { /* already dead */ } }
        }, timeout);
        const collect = (which) => (d) => {
            if (stdout.length + stderr.length < OUTPUT_CAP) {
                if (which === 'out') stdout += d.toString(); else stderr += d.toString();
            } else truncated = true;
        };
        child.stdout.on('data', collect('out'));
        child.stderr.on('data', collect('err'));
        const finish = (code, extraErr) => {
            if (done) return;
            done = true;
            clearTimeout(timer);
            resolve({ exit_code: code, stdout, stderr: stderr + (extraErr || ''), cwd: workdir, timed_out: timedOut, truncated });
        };
        child.on('error', (e) => finish(-1, String(e && e.message || e)));
        child.on('close', (code) => finish(code === null ? -1 : code));
    });
}

async function readFile(args) {
    const p = path.resolve(String(args.path || ''));
    const encoding = args.encoding === 'base64' ? 'base64' : 'utf8';
    const st = await fsp.stat(p);
    if (!st.isFile()) throw new Error('Not a regular file: ' + p);
    if (encoding === 'base64') {
        const cap = 4 * 1024 * 1024;
        const buf = await fsp.readFile(p);
        const truncated = buf.length > cap;
        return { path: p, encoding, size_bytes: st.size, truncated, content: buf.subarray(0, cap).toString('base64') };
    }
    const cap = 1024 * 1024;
    let text = await fsp.readFile(p, 'utf8');
    const truncated = text.length > cap;
    if (truncated) text = text.slice(0, cap);
    let totalLines = null;
    const offset = parseInt(args.offset, 10);
    const limit = parseInt(args.limit, 10);
    if (offset > 0 || limit > 0) {
        const lines = text.split('\n');
        totalLines = lines.length;
        const start = offset > 0 ? offset - 1 : 0;
        const end = limit > 0 ? start + limit : lines.length;
        text = lines.slice(start, end).join('\n');
        return { path: p, encoding, size_bytes: st.size, truncated, total_lines: totalLines, offset: start + 1, content: text };
    }
    return { path: p, encoding, size_bytes: st.size, truncated, content: text };
}

async function writeFile(args) {
    const p = path.resolve(String(args.path || ''));
    if (typeof args.content !== 'string') throw new Error('content (string) is required');
    const encoding = args.encoding === 'base64' ? 'base64' : 'utf8';
    const buf = Buffer.from(args.content, encoding);
    await fsp.mkdir(path.dirname(p), { recursive: true });
    if (args.append) await fsp.appendFile(p, buf);
    else await fsp.writeFile(p, buf);
    return { path: p, bytes_written: buf.length, appended: !!args.append };
}

async function listDirectory(args) {
    const p = path.resolve(String(args.path || os.homedir()));
    const dirents = await fsp.readdir(p, { withFileTypes: true });
    const entries = [];
    for (const d of dirents.slice(0, 2000)) {
        let size = null;
        try {
            const st = await fsp.stat(path.join(p, d.name));
            size = st.size;
        } catch (e) { /* permission / broken link */ }
        entries.push({
            name: d.name,
            type: d.isDirectory() ? 'dir' : d.isFile() ? 'file' : d.isSymbolicLink() ? 'symlink' : 'other',
            size_bytes: size
        });
    }
    entries.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'dir' ? -1 : 1));
    return { path: p, count: entries.length, truncated: dirents.length > 2000, entries };
}

async function fileInfo(args) {
    const p = path.resolve(String(args.path || ''));
    try {
        const st = await fsp.stat(p);
        const lst = await fsp.lstat(p);
        return {
            path: p, exists: true,
            type: st.isDirectory() ? 'dir' : st.isFile() ? 'file' : 'other',
            size_bytes: st.size, mode: '0' + (st.mode & 0o777).toString(8),
            is_symlink: lst.isSymbolicLink(),
            modified: st.mtime.toISOString(), created: st.birthtime.toISOString()
        };
    } catch (e) {
        return { path: p, exists: false };
    }
}

async function deletePath(args) {
    const p = path.resolve(String(args.path || ''));
    if (p === path.parse(p).root) throw new Error('Refusing to delete filesystem root');
    await fsp.rm(p, { recursive: !!args.recursive, force: false });
    return { path: p, deleted: true };
}

async function movePath(args) {
    const src = path.resolve(String(args.source || ''));
    const dst = path.resolve(String(args.destination || ''));
    await fsp.mkdir(path.dirname(dst), { recursive: true });
    try {
        await fsp.rename(src, dst);
    } catch (e) {
        if (e.code === 'EXDEV') {
            await fsp.cp(src, dst, { recursive: true });
            await fsp.rm(src, { recursive: true, force: true });
        } else throw e;
    }
    return { source: src, destination: dst, moved: true };
}

async function makeDirectory(args) {
    const p = path.resolve(String(args.path || ''));
    await fsp.mkdir(p, { recursive: args.recursive !== false });
    return { path: p, created: true };
}

async function systemInfo() {
    let user = 'unknown';
    try { user = os.userInfo().username; } catch (e) { /* ignore */ }
    return {
        platform: process.platform, arch: process.arch, hostname: os.hostname(),
        user, home: os.homedir(), default_cwd: os.homedir(),
        node_version: process.version, uptime_seconds: Math.round(os.uptime()),
        server_cwd: process.cwd()
    };
}

/* ------------------------------ tool definitions ------------------------------ */

const TOOLS = [
    {
        name: 'run_command',
        description: 'Execute a shell command on the remote machine (bash on Linux/macOS, cmd.exe on Windows). Returns exit_code, stdout, stderr. Each call starts in "cwd" (default: home dir) — cd does NOT persist between calls; pass cwd or use absolute paths. Default timeout 120s (max 600s). Output capped at 512KB.',
        inputSchema: {
            type: 'object',
            properties: {
                command: { type: 'string', description: 'Shell command line to execute' },
                cwd: { type: 'string', description: 'Working directory (absolute path). Defaults to home directory.' },
                timeout_ms: { type: 'integer', description: 'Timeout in milliseconds (1000-600000). Default 120000.' }
            },
            required: ['command']
        },
        handler: runCommand
    },
    {
        name: 'read_file',
        description: 'Read a file. Text (utf8) by default, capped at 1MB; use encoding="base64" for binary files (capped at 4MB). Optional offset/limit select lines (1-based) for large text files.',
        inputSchema: {
            type: 'object',
            properties: {
                path: { type: 'string', description: 'Absolute or relative file path' },
                encoding: { type: 'string', enum: ['utf8', 'base64'], description: 'utf8 (default) or base64 for binary' },
                offset: { type: 'integer', description: 'First line to read (1-based, text only)' },
                limit: { type: 'integer', description: 'Number of lines to read (text only)' }
            },
            required: ['path']
        },
        handler: readFile
    },
    {
        name: 'write_file',
        description: 'Write or append a file with full access. Creates parent directories automatically. Use encoding="base64" to write binary content.',
        inputSchema: {
            type: 'object',
            properties: {
                path: { type: 'string', description: 'Target file path' },
                content: { type: 'string', description: 'File content (text, or base64 when encoding=base64)' },
                encoding: { type: 'string', enum: ['utf8', 'base64'], description: 'utf8 (default) or base64' },
                append: { type: 'boolean', description: 'Append instead of overwrite. Default false.' }
            },
            required: ['path', 'content']
        },
        handler: writeFile
    },
    {
        name: 'list_directory',
        description: 'List directory entries (name, type, size). Directories first, alphabetical. Defaults to home directory. Max 2000 entries.',
        inputSchema: {
            type: 'object',
            properties: { path: { type: 'string', description: 'Directory path. Defaults to home.' } }
        },
        handler: listDirectory
    },
    {
        name: 'file_info',
        description: 'Stat a path: existence, type, size, permission mode, symlink flag, timestamps.',
        inputSchema: {
            type: 'object',
            properties: { path: { type: 'string', description: 'Path to inspect' } },
            required: ['path']
        },
        handler: fileInfo
    },
    {
        name: 'delete_path',
        description: 'Delete a file or directory. Set recursive=true for non-empty directories. DESTRUCTIVE — confirm with the user before deleting anything important.',
        inputSchema: {
            type: 'object',
            properties: {
                path: { type: 'string', description: 'Path to delete' },
                recursive: { type: 'boolean', description: 'Required for non-empty directories' }
            },
            required: ['path']
        },
        handler: deletePath
    },
    {
        name: 'move_path',
        description: 'Move or rename a file/directory (works across drives). Creates destination parent dirs.',
        inputSchema: {
            type: 'object',
            properties: {
                source: { type: 'string', description: 'Existing path' },
                destination: { type: 'string', description: 'New path' }
            },
            required: ['source', 'destination']
        },
        handler: movePath
    },
    {
        name: 'make_directory',
        description: 'Create a directory (recursive by default, like mkdir -p).',
        inputSchema: {
            type: 'object',
            properties: {
                path: { type: 'string', description: 'Directory to create' },
                recursive: { type: 'boolean', description: 'Create parents. Default true.' }
            },
            required: ['path']
        },
        handler: makeDirectory
    },
    {
        name: 'system_info',
        description: 'Get remote machine info: OS, architecture, hostname, user, home directory, node version. Call this first to learn the environment.',
        inputSchema: { type: 'object', properties: {} },
        handler: systemInfo
    }
];

/* ------------------------------ JSON-RPC / MCP ------------------------------ */

function rpcResult(id, result) { return { jsonrpc: '2.0', id, result }; }
function rpcError(id, code, message) { return { jsonrpc: '2.0', id, error: { code, message } }; }

async function handleRpc(msg) {
    const method = msg.method;
    const id = msg.id;
    const params = msg.params || {};
    const isNotification = id === undefined || id === null;

    switch (method) {
        case 'initialize': {
            const requested = params.protocolVersion;
            const protocolVersion = SUPPORTED_PROTOCOLS.includes(requested) ? requested : SUPPORTED_PROTOCOLS[0];
            return rpcResult(id, {
                protocolVersion,
                capabilities: { tools: { listChanged: false } },
                serverInfo: SERVER_INFO,
                instructions: 'Remote shell + file access. Call system_info first. run_command does not persist cwd between calls — pass cwd explicitly. Confirm destructive operations with the user.'
            });
        }
        case 'notifications/initialized':
        case 'notifications/cancelled':
            return null;
        case 'ping':
            return rpcResult(id, {});
        case 'tools/list':
            return rpcResult(id, { tools: TOOLS.map(t => ({ name: t.name, description: t.description, inputSchema: t.inputSchema })) });
        case 'tools/call': {
            const tool = TOOLS.find(t => t.name === params.name);
            if (!tool) return rpcResult(id, { content: [{ type: 'text', text: 'Unknown tool: ' + params.name }], isError: true });
            try {
                const result = await tool.handler(params.arguments || {});
                return rpcResult(id, { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] });
            } catch (e) {
                return rpcResult(id, { content: [{ type: 'text', text: 'Error: ' + (e && e.message || String(e)) }], isError: true });
            }
        }
        case 'resources/list':
            return rpcResult(id, { resources: [] });
        case 'prompts/list':
            return rpcResult(id, { prompts: [] });
        default:
            if (isNotification) return null;
            return rpcError(id, -32601, 'Method not found: ' + method);
    }
}

function readBody(req) {
    return new Promise((resolve, reject) => {
        let size = 0;
        const chunks = [];
        req.on('data', (c) => {
            size += c.length;
            if (size > MAX_BODY) { reject(new Error('Body too large')); req.destroy(); return; }
            chunks.push(c);
        });
        req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
        req.on('error', reject);
    });
}

const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const p = url.pathname;
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, Mcp-Session-Id, MCP-Protocol-Version');
    res.setHeader('Access-Control-Expose-Headers', 'Mcp-Session-Id');

    if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

    if (p === '/health') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, server: SERVER_INFO, tools: TOOLS.length }));
        return;
    }

    if (p === '/' && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end('<!DOCTYPE html><html><head><meta charset="utf-8"><title>Remote-Shell MCP</title>' +
            '<style>body{background:#111;color:#0f0;font-family:monospace;padding:40px}a{color:#0ff}</style></head>' +
            '<body><h2>Remote-Shell MCP Server</h2><p>Status: ONLINE</p>' +
            '<p>MCP endpoint: <code>/mcp</code> (POST, JSON-RPC 2.0, Streamable HTTP)</p>' +
            '<p>Auth: <code>Authorization: Bearer &lt;token&gt;</code> or <code>?token=&lt;token&gt;</code></p>' +
            '<p>Tools: ' + TOOLS.map(t => t.name).join(', ') + '</p>' +
            '<p><a href="/health">/health</a></p></body></html>');
        return;
    }

    if ((p === '/mcp' || p === '/') && req.method === 'POST') {
        if (!authorized(req, url)) {
            res.writeHead(401, { 'Content-Type': 'application/json', 'WWW-Authenticate': 'Bearer' });
            res.end(JSON.stringify(rpcError(null, -32001, 'Unauthorized: missing or invalid token')));
            return;
        }
        let body;
        try { body = await readBody(req); } catch (e) {
            res.writeHead(413, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(rpcError(null, -32600, String(e.message))));
            return;
        }
        let msg;
        try { msg = JSON.parse(body); } catch (e) {
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(rpcError(null, -32700, 'Parse error')));
            return;
        }
        const sessionHeader = req.headers['mcp-session-id'];
        try {
            if (Array.isArray(msg)) {
                const results = (await Promise.all(msg.map(handleRpc))).filter(Boolean);
                if (results.length === 0) { res.writeHead(202); res.end(); return; }
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify(results));
            } else {
                const result = await handleRpc(msg);
                const headers = { 'Content-Type': 'application/json' };
                if (msg.method === 'initialize') headers['Mcp-Session-Id'] = sessionHeader || crypto.randomUUID();
                else if (sessionHeader) headers['Mcp-Session-Id'] = sessionHeader;
                if (result === null) { res.writeHead(202, headers); res.end(); return; }
                res.writeHead(200, headers);
                res.end(JSON.stringify(result));
            }
        } catch (e) {
            console.error('Handler error:', e);
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(rpcError(msg && msg.id !== undefined ? msg.id : null, -32603, 'Internal error')));
        }
        return;
    }

    if (p === '/mcp' && req.method === 'GET') { res.writeHead(405, { 'Allow': 'POST, DELETE' }); res.end(); return; }
    if (p === '/mcp' && req.method === 'DELETE') { res.writeHead(200); res.end(); return; }

    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
});

process.on('uncaughtException', (err) => { console.error('Uncaught:', err); });
process.on('SIGTERM', () => { server.close(() => process.exit(0)); setTimeout(() => process.exit(0), 2000); });
process.on('SIGINT', () => { server.close(() => process.exit(0)); setTimeout(() => process.exit(0), 2000); });

server.listen(PORT, HOST, () => {
    console.log(`[${new Date().toISOString()}] Remote-Shell MCP listening on http://${HOST}:${PORT}`);
    console.log(`MCP endpoint: http://${HOST}:${PORT}/mcp  (token file: ${path.join(RUNTIME, 'token')})`);
});