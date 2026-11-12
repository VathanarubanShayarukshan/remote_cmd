@echo off
setlocal
cd /d "%~dp0"
title Stop Remote-Shell Services

echo Stopping Remote-Shell services...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'mcp_server\.py|remote_cmd\.py|mcp-server\.js|server V1\.js' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('  - stopped PID ' + $_.ProcessId) }"
taskkill /IM cloudflared.exe /F >nul 2>&1 && echo   - cloudflared tunnels stopped || echo   - no cloudflared running
echo Done. Token preserved in .runtime\token; tunnel URLs expire with the tunnels.
pause