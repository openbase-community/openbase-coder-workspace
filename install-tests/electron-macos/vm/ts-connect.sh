#!/bin/bash
# Runs INSIDE the VM. Connects it to the tailnet headlessly using an auth key
# ($1). Userspace-networking avoids needing a utun/system-extension; we use
# tailscaled's DEFAULT socket (what the CLI expects) and chmod 666 it so the
# non-root admin user — and the openbase-coder CLI that runs `tailscale serve`
# during setup — can talk to the daemon.
set -e
KEY="$1"
eval "$(/opt/homebrew/bin/brew shellenv)"
SOCK=/var/run/tailscaled.socket

sudo -n true || { echo "no passwordless sudo in VM"; exit 1; }
sudo pkill -x tailscaled 2>/dev/null || true
sleep 2
sudo rm -f "$SOCK" 2>/dev/null || true
sudo mkdir -p /var/lib/tailscale
sudo nohup tailscaled --tun=userspace-networking --statedir=/var/lib/tailscale \
  >/tmp/tailscaled.log 2>&1 &
for _ in $(seq 1 30); do [ -S "$SOCK" ] && break; sleep 1; done
[ -S "$SOCK" ] || { echo "tailscaled socket never appeared"; sudo tail -20 /tmp/tailscaled.log; exit 1; }
sudo chmod 666 "$SOCK"

tailscale up --authkey="$KEY" --hostname=openbase-install-test --accept-dns=false --timeout=120s
sudo chmod 666 "$SOCK"
tailscale status | head -1
echo "TS_CONNECTED"
