#!/bin/bash
# Stop the Remote-Shell MCP server, Web Terminal, and their Cloudflare tunnels.
MCP_PORT="${PORT:-1213}"
TERM_PORT="${TERMINAL_PORT:-1212}"

echo "Stopping Remote-Shell services..."
pkill -f "mcp_server.py" 2>/dev/null && echo "  - MCP server stopped" || echo "  - MCP server not running"
pkill -f "remote_cmd.py" 2>/dev/null && echo "  - Web Terminal stopped" || echo "  - Web Terminal not running"
pkill -f "mcp-server.js" 2>/dev/null || true
pkill -f "server V1.js" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://localhost:$MCP_PORT" 2>/dev/null && echo "  - MCP tunnel stopped" || true
pkill -f "cloudflared tunnel --url http://localhost:$TERM_PORT" 2>/dev/null && echo "  - Terminal tunnel stopped" || true
echo "Done. (Token preserved in .runtime/token; URLs expire with the tunnels.)"