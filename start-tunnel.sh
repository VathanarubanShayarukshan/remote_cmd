#!/bin/bash
set -e

PORT=4040

echo "Downloading cloudflared..."
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64

chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

echo "Starting Cloudflare tunnel..."
cloudflared tunnel --url http://localhost:$PORT
