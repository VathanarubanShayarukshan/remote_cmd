@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Remote-Shell MCP + Web Terminal Setup

set "RUNTIME=.runtime"
set "MCP_PORT=1213"
set "TERM_PORT=1212"
if not exist "%RUNTIME%" mkdir "%RUNTIME%"
if not exist "bin" mkdir "bin"

echo ==============================================
echo   Remote-Shell MCP + Web Terminal  (Windows)
echo ==============================================
echo.

REM ---------- 1) Python ----------
echo [..] Checking Python...
set "PY="
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY ( py -3 -c "import sys" >nul 2>&1 && set "PY=py -3" )
if not defined PY (
    echo [..] Python not found. Trying winget install...
    where winget >nul 2>&1 && winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    python -c "import sys" >nul 2>&1 && set "PY=python"
    if not defined PY ( py -3 -c "import sys" >nul 2>&1 && set "PY=py -3" )
)
if not defined PY (
    echo [ERR] Python 3 is required but was not found.
    echo       Install it from https://www.python.org/downloads/ then re-run setup.bat
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)
echo [OK] Python launcher: !PY!

REM ---------- 2) cloudflared ----------
set "CF="
where cloudflared >nul 2>&1 && set "CF=cloudflared"
if not defined CF if exist "bin\cloudflared.exe" set "CF=bin\cloudflared.exe"
if not defined CF (
    echo [..] Downloading cloudflared...
    set "CFURL=https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    where curl >nul 2>&1 && (
        curl -L -o "bin\cloudflared.exe" "!CFURL!"
    ) || (
        powershell -NoProfile -Command "Invoke-WebRequest -Uri '!CFURL!' -OutFile 'bin\cloudflared.exe'"
    )
    if exist "bin\cloudflared.exe" ( set "CF=bin\cloudflared.exe" ) else (
        echo [ERR] Failed to download cloudflared. Check your internet connection.
        pause
        exit /b 1
    )
)
echo [OK] cloudflared: !CF!

REM ---------- 3) Stop old instances ----------
echo [..] Stopping old instances...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'mcp_server\.py|remote_cmd\.py|mcp-server\.js|server V1\.js' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
taskkill /IM cloudflared.exe /F >nul 2>&1
ping -n 2 127.0.0.1 >nul

REM ---------- 4) Start servers in background ----------
echo [..] Starting MCP server (port %MCP_PORT%)...
start "RemoteShellMCP" /min cmd /c "!PY! mcp_server.py > %RUNTIME%\mcp.log 2>&1"
echo [..] Starting Web Terminal (port %TERM_PORT%)...
start "RemoteTerminal" /min cmd /c "!PY! remote_cmd.py > %RUNTIME%\terminal.log 2>&1"
ping -n 3 127.0.0.1 >nul

REM ---------- 5+6) Start Cloudflare tunnels (with retries) and get URLs ----------
echo [..] Starting Cloudflare tunnels...
call :start_tunnel %MCP_PORT% "%RUNTIME%\tunnel-mcp.log" MCP_URL
call :start_tunnel %TERM_PORT% "%RUNTIME%\tunnel-terminal.log" TERM_URL

REM ---------- 7) Token ----------
set "TOKEN="
if exist "%RUNTIME%\token" set /p TOKEN=<"%RUNTIME%\token"

REM ---------- 8) Optional skill install ----------
if exist "%USERPROFILE%\.claude" (
    if exist "skills\remote-shell\SKILL.md" (
        if not exist "%USERPROFILE%\.claude\skills\remote-shell" mkdir "%USERPROFILE%\.claude\skills\remote-shell"
        copy /y "skills\remote-shell\SKILL.md" "%USERPROFILE%\.claude\skills\remote-shell\SKILL.md" >nul
        echo [OK] Installed AI guide skill to %USERPROFILE%\.claude\skills\remote-shell\
    )
)

REM ---------- 9) Save + print connection info ----------
> "%RUNTIME%\connection.txt" (
    echo MCP URL: !MCP_URL!/mcp?token=!TOKEN!
    echo Terminal URL: !TERM_URL!/vps?token=!TOKEN!
    echo Token: !TOKEN!
)

echo.
echo ==============================================
echo   SUCCESS - services are LIVE in background
echo ==============================================
if defined MCP_URL (
    echo MCP URL for Claude:
    echo   !MCP_URL!/mcp?token=!TOKEN!
    echo.
    echo Add to Claude Code:
    echo   claude mcp add --transport http remote-shell "!MCP_URL!/mcp?token=!TOKEN!"
) else (
    echo [..] MCP tunnel failed. If the log shows HTTP 429 / "failed to request", Cloudflare is
    echo      rate-limiting quick tunnels from this IP. Wait a few minutes and re-run, or use a named tunnel.
    echo      Log: %RUNTIME%\tunnel-mcp.log
)
echo.
if defined TERM_URL (
    echo Web Terminal URL for you:
    echo   !TERM_URL!/vps?token=!TOKEN!
) else (
    echo [..] Terminal tunnel failed. See %RUNTIME%\tunnel-terminal.log ^(often HTTP 429 rate-limit^).
)
echo.
echo Token file: %RUNTIME%\token
echo Connection info saved: %RUNTIME%\connection.txt
echo Logs: %RUNTIME%\mcp.log, terminal.log, tunnel-mcp.log, tunnel-terminal.log
echo Stop everything: stop.bat
echo.
echo NOTE: Quick-tunnel URLs change on every restart. Re-run setup.bat for new URLs.
echo.
REM Pause only when double-clicked from Explorer (keeps window open); skip in automated runs.
echo !cmdcmdline! | find /i /c:"%~f0" >nul 2>&1 && pause
exit /b 0

REM ---------- subroutine: start one tunnel with retries, set outvar to its URL ----------
:start_tunnel
set "TPORT=%~1"
set "TLOG=%~2"
set "TVAR=%~3"
set "%TVAR%="
for /L %%a in (1,1,3) do (
    start "Tunnel%TPORT%" /min cmd /c "!CF! tunnel --url http://localhost:%TPORT% > %TLOG% 2>&1"
    for /L %%i in (1,1,25) do (
        call :geturl "%TLOG%" %TVAR%
        if defined %TVAR% goto :tunnel_done
        ping -n 2 127.0.0.1 >nul
    )
    echo [..] Tunnel on port %TPORT% not up ^(attempt %%a/3^) - Cloudflare may be rate-limiting; retrying...
    powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'tunnel --url http://localhost:%TPORT%' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
    ping -n 6 127.0.0.1 >nul
)
:tunnel_done
goto :eof

REM ---------- subroutine: extract first trycloudflare URL from a log ----------
:geturl
set "LOGFILE=%~1"
set "OUTVAR=%~2"
for /f "usebackq delims=" %%u in (`powershell -NoProfile -Command "if(Test-Path '%LOGFILE%'){$c=Get-Content '%LOGFILE%' -Raw -ErrorAction SilentlyContinue;if($c){$m=[regex]::Match($c,'https://[a-z0-9]+(-[a-z0-9]+)+\.trycloudflare\.com');if($m.Success){$m.Value}}}"`) do set "%OUTVAR%=%%u"
goto :eof