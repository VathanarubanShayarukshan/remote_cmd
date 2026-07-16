const http = require('http');                          
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');                          
const os = require('os');

const PORT = 1212;                                     
let currentCwd = os.homedir() || '/root';
let outputBuffer = ''; 
let isRunning = false;
let activeChild = null;

process.on('uncaughtException', (err) => { console.error('Server Error:', err); });

const server = http.createServer((req, res) => {
    console.log(`[${new Date().toLocaleTimeString()}] ${req.method} ${req.url}`);

    if (req.url === '/' || req.url.startsWith('/?')) {
        res.writeHead(302, { 'Location': '/vps' });
        res.end();
        return;
    }

    if (req.url.startsWith('/vps')) {             
        res.writeHead(200, { 
            'Content-Type': 'text/html; charset=utf-8',
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma': 'no-cache'
        });
        
        res.write(`<!DOCTYPE html>
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
        <h2>⚡ VPS WEB TERMINAL</h2>
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
            <input type="text" id="cmdInput" placeholder="Enter linux command..." autofocus>
            <button id="execBtn" class="exec-btn" onclick="runCommand()">EXECUTE</button>
            <button id="stopBtn" class="exec-btn btn-stop" onclick="stopCommand()">STOP (Ctrl+C)</button>
        </div>

        <div class="tools-section">
            <div class="tool-box">
                <h3>📁 Upload File</h3>
                <input type="file" id="fileInput">
                <button id="uploadBtn" onclick="uploadFile()" style="background:#00ffff;">UPLOAD</button>
            </div>
            <div class="tool-box">
                <h3>📥 Download File</h3>
                <input type="text" id="dlPathInput" placeholder="filename.txt or full path">
                <button onclick="downloadFile()" style="background:#ffff00;">DOWNLOAD</button>
            </div>
        </div>
    </div>

    <script>
        const cmdInput = document.getElementById('cmdInput');
        const outputDiv = document.getElementById('output');
        const pathBanner = document.getElementById('currentPath');
        const execBtn = document.getElementById('execBtn');
        const stopBtn = document.getElementById('stopBtn');
        let activeCwd = '';
        let pollTimeout = null;
        let pollIntervalMs = 1500;

        cmdInput.addEventListener('keydown', (e) => { 
            if (e.key === 'Tab') { e.preventDefault(); triggerTab(); }
            if (e.key === 'Enter') runCommand();
        });

        async function maintainHeartbeat() {
            try {
                const res = await fetch('/api/read?t=' + Date.now());
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
            fetch('/api/autocomplete', {
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
                    outputDiv.innerText += '\\n' + data.matches.join('    ') + '\\n';
                    outputDiv.scrollTop = outputDiv.scrollHeight;
                }
            });
        }

        function insertText(text) { cmdInput.value += text; cmdInput.focus(); }
        function clearTerminal() { outputDiv.innerText = ''; fetch('/api/clear-buffer?t=' + Date.now(), { method: 'POST' }); }

        function runCommand() {
            const cmd = cmdInput.value.trim();
            if (!cmd) return;
            cmdInput.value = '';
            outputDiv.innerText = ''; 
            pollIntervalMs = 300; 

            fetch('/api/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: cmd })
            }).then(() => { maintainHeartbeat(); });
        }

        function stopCommand() {
            fetch('/api/interrupt', { method: 'POST' }).then(() => { pollIntervalMs = 300; maintainHeartbeat(); });
        }

        function uploadFile() {
            const fileBox = document.getElementById('fileInput');
            if (fileBox.files.length === 0) return alert('Select file!');
            const file = fileBox.files[0];
            const uploadBtn = document.getElementById('uploadBtn');
            uploadBtn.disabled = true;

            fetch('/api/upload', {
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
            if(!filePath) return alert('Enter file path!');
            window.open('/api/download?path=' + encodeURIComponent(filePath), '_blank');
        }

        maintainHeartbeat();
    </script>
</body>
</html>`);
        res.end();
        return;
    }

    if (req.url.startsWith('/api/read') && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store, no-cache' });
        res.end(JSON.stringify({ output: outputBuffer, cwd: currentCwd, isRunning: isRunning }));
        return;
    }

    if (req.url.startsWith('/api/clear-buffer') && req.method === 'POST') {
        outputBuffer = ''; res.writeHead(200); res.end(); return;
    }

    // FIXED: Kill entire process group using negative PID (-activeChild.pid)
    if (req.url === '/api/interrupt' && req.method === 'POST') {
        if (activeChild && activeChild.pid) {
            try { 
                process.kill(-activeChild.pid, 'SIGINT'); 
                outputBuffer += "\n[Process Interrupted]\n"; 
            } catch(e){
                try { activeChild.kill('SIGINT'); } catch(err){}
            }
        }
        isRunning = false; res.writeHead(200); res.end(); return;
    }

    if (req.url === '/api/execute' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => body += chunk);
        req.on('end', () => {
            try {
                const { command } = JSON.parse(body);
                if (activeChild && activeChild.pid) { 
                    try { process.kill(-activeChild.pid, 'SIGKILL'); } catch(e){} 
                }
                outputBuffer = ''; isRunning = true;
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'started' }));

                const wrappedCommand = `cd '${currentCwd.replace(/'/g, "'\\''")}' && ${command} ; echo -n "___CWD___" ; pwd`;
                
                // FIXED: Added { detached: true } to spawn a new process group
                activeChild = spawn('/bin/bash', ['-c', wrappedCommand], { detached: true });
                
                activeChild.stdout.on('data', (chunk) => { outputBuffer += chunk.toString(); });
                activeChild.stderr.on('data', (chunk) => { outputBuffer += chunk.toString(); });
                activeChild.on('close', () => {
                    const token = "___CWD___";
                    const idx = outputBuffer.lastIndexOf(token);
                    if (idx !== -1) {
                        const parsedPath = outputBuffer.substring(idx + token.length).trim();
                        outputBuffer = outputBuffer.substring(0, idx);
                        if (parsedPath && fs.existsSync(parsedPath)) { currentCwd = parsedPath; }
                    }
                    isRunning = false; activeChild = null;
                });
            } catch (err) { res.writeHead(400); res.end(); }
        });
        return;
    }

    // Autocomplete, Upload, Download routes remain exact same
    if (req.url === '/api/autocomplete' && req.method === 'POST') {
        let body = '';
        req.on('data', chunk => body += chunk);
        req.on('end', () => {
            try {
                const { text } = JSON.parse(body);
                const words = text.split(' ');
                const lastWord = words[words.length - 1] || '';
                const compCmd = `cd '${currentCwd.replace(/'/g, "'\\''")}' && compgen -f '${lastWord.replace(/'/g, "'\\''")}'`;
                const child = spawn('/bin/bash', ['-c', compCmd]);
                let matches = '';
                child.stdout.on('data', chunk => matches += chunk.toString());
                child.on('close', () => {
                    const list = matches.trim().split('\n').filter(Boolean).map(item => path.basename(item));
                    let isDir = false;
                    if (list.length === 1) { try { isDir = fs.lstatSync(path.join(currentCwd, list[0])).isDirectory(); } catch(e){} }
                    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ matches: list, isDir }));
                });
            } catch(e) { res.writeHead(400); res.end(); }
        });
        return;
    }
    if (req.url === '/api/upload' && req.method === 'POST') {
        const fileName = decodeURIComponent(req.headers['file-name']);
        const targetCwd = decodeURIComponent(req.headers['cwd'] || currentCwd);
        req.pipe(fs.createWriteStream(path.join(targetCwd, fileName)));
        req.on('end', () => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ success: true, message: `Uploaded "${fileName}" successfully.` })); });
        return;
    }
    if (req.url.startsWith('/api/download') && req.method === 'GET') {
        const urlObj = new URL(req.url, `http://${req.headers.host}`);
        const fileTarget = urlObj.searchParams.get('path');
        const resolvedPath = path.isAbsolute(fileTarget) ? fileTarget : path.join(currentCwd, fileTarget);
        if (fs.existsSync(resolvedPath) && fs.lstatSync(resolvedPath).isFile()) {
            res.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Content-Disposition': `attachment; filename="${path.basename(resolvedPath)}"` });
            fs.createReadStream(resolvedPath).pipe(res);
        } else { res.writeHead(404); res.end('File not found.'); }
        return;
    }
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
});

server.listen(PORT, () => { console.log(`Stable Server running on port ${PORT}`); });
