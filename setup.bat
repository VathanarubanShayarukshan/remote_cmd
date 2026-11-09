@echo off
REM ============================================================
REM  VPS Python Terminal + MCP - Windows Setup & Run (setup.bat)
REM  Checks Python, installs 'mcp' package, downloads server.py,
REM  installs cloudflared and starts Web UI + single MCP URL.
REM ============================================================
setlocal EnableDelayedExpansion
chcp 65001 >nul

set PORT=1212
set REPO_RAW=https://raw.githubusercontent.com/VathanarubanShayarukshan/remote_cmd/refs/heads/main

echo.
echo  ==============================================
echo    VPS Python Terminal + MCP  (Windows Setup)
echo  ==============================================
echo.

REM -- 1. Check Python -------------------------------------------------
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Install from https://python.org
    echo         Tick "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version') do set PYVER=%%v
echo [OK] Python %PYVER% found.

REM -- 2. Install mcp package ------------------------------------------
python -c "import mcp" >nul 2>nul
if %errorlevel% neq 0 (
    echo [..] Installing mcp package...
    python -m pip install --upgrade pip >nul 2>nul
    python -m pip install --upgrade mcp
    if !errorlevel! neq 0 (
        echo [ERROR] pip install mcp failed!
        pause
        exit /b 1
    )
) else (
    echo [OK] mcp package already installed.
)

REM -- 3. Create folder + download server.py ----------------------------
if not exist web_py mkdir web_py
cd web_py
echo [..] Downloading server.py...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%REPO_RAW%/server.py' -OutFile 'server.py'" 
if not exist server.py (
    echo [ERROR] Download failed!
    pause
    exit /b 1
)
echo [OK] server.py downloaded.

python -m py_compile server.py
if %errorlevel% neq 0 (
    echo [ERROR] Syntax error in server.py!
    pause
    exit /b 1
)
echo [OK] Syntax check passed.

REM -- 4. Cloudflared (tunnel for single public MCP URL) ----------------
where cloudflared >nul 2>nul
if %errorlevel% neq 0 (
    echo [..] Downloading cloudflared.exe...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
    if not exist cloudflared.exe (
        echo [WARN] cloudflared download failed - running WITHOUT tunnel.
    )
)

REM -- 5. Kill old instances --------------------------------------------
taskkill /F /IM python.exe >nul 2>nul
taskkill /F /IM cloudflared.exe >nul 2>nul
timeout /t 2 /nobreak >nul

REM -- 6. Start server ---------------------------------------------------
echo [..] Starting Python server (Web + MCP on port %PORT%)...
start "VPS-Python-Server" /min cmd /c "python server.py > output.log 2>&1"
timeout /t 3 /nobreak >nul

curl -s http://localhost:%PORT%/api/read >nul 2>nul
if %errorlevel% equ 0 (
    echo [OK] Server is running!
) else (
    echo [ERROR] Server failed to start! See web_py\output.log
    pause
    exit /b 1
)

REM -- 7. Start tunnel (optional) ----------------------------------------
set TUNNEL_URL=
if exist cloudflared.exe (
    echo [..] Starting Cloudflare Quick Tunnel...
    start "VPS-Tunnel" /min cmd /c "cloudflared.exe tunnel --url http://localhost:%PORT% > tunnel.log 2>&1"
    timeout /t 12 /nobreak >nul
    for /f "tokens=2 delims= " %%u in ('findstr /r /c:"https://[a-z0-9-]*.trycloudflare.com" tunnel.log') do (
        set TUNNEL_URL=%%u
    )
)

echo.
echo  ==============================================
echo   SUCCESS! Your VPS terminal + MCP is LIVE
echo  ==============================================
echo   Local Web Terminal : http://localhost:%PORT%/vps
echo   Local MCP URL      : http://localhost:%PORT%/mcp
if not "%TUNNEL_URL%"=="" (
    echo   Public Web URL     : %TUNNEL_URL%/vps
    echo   PUBLIC MCP URL     : %TUNNEL_URL%/mcp   ^<- give this to AI
) else (
    echo   (No tunnel URL found - check web_py\tunnel.log)
)
echo.
echo   Logs: web_py\output.log ^| web_py\tunnel.log
echo   Close the "VPS-Python-Server" window to stop.
echo.
pause
endlocal
