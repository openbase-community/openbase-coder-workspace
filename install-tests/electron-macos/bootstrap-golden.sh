#!/usr/bin/env bash
#
# One-time bootstrap for the macOS Electron install-flow test: install Tart +
# sshpass, pull a macOS base image, and bake a reusable "golden" VM.
#
# The cirruslabs macOS base images are pre-provisioned for CI (user admin /
# password admin, Remote Login on, auto-login to a GUI session), so this runs
# fully headless — no macOS Setup Assistant clicking. The golden VM is cloned
# (copy-on-write, seconds) for every test run, so it contains everything a run
# needs but NO Openbase install:
#   - Node (for the Playwright driver)
#   - the Tailscale client (tailscaled + tailscale)
#   - the driver's npm deps (playwright) prewarmed
#
# Safe to re-run; it skips a golden VM that already exists.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOLDEN="${1:-openbase-golden}"
BASE_IMAGE="${OPENBASE_TART_BASE_IMAGE:-ghcr.io/cirruslabs/macos-sequoia-base:latest}"
VM_USER="admin"; VM_PASS="admin"
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10)

step() { printf '\033[34m==>\033[0m %s\n' "$*"; }

# Prerequisites (fail early with a clear message rather than mid-run).
[ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ] || {
  echo "This harness requires an Apple Silicon Mac (Tart virtualizes macOS on arm64)." >&2; exit 1; }
command -v brew >/dev/null 2>&1 || { echo "Homebrew is required (https://brew.sh)." >&2; exit 1; }

if ! command -v tart >/dev/null 2>&1; then
  step "Installing Tart"
  # Current Homebrew refuses third-party taps until trusted; Tart lives in one.
  brew trust cirruslabs/cli 2>/dev/null || true
  brew install cirruslabs/cli/tart
fi
if ! command -v sshpass >/dev/null 2>&1; then
  step "Installing sshpass"
  brew install sshpass || brew install esolitos/ipa/sshpass
fi

if tart list 2>/dev/null | grep -q "[[:space:]]$GOLDEN[[:space:]]"; then
  step "Golden VM '$GOLDEN' already exists — nothing to do."
  echo "  (rebuild from scratch with: tart delete $GOLDEN && $0)"
  exit 0
fi

step "Pulling base image $BASE_IMAGE (large, one-time)"
tart clone "$BASE_IMAGE" "$GOLDEN"

step "Booting the golden VM to provision it (headless)"
tart run "$GOLDEN" --no-graphics >/tmp/openbase-golden-run.log 2>&1 &
RUN_PID=$!
trap 'kill "$RUN_PID" 2>/dev/null || true' EXIT

step "Waiting for SSH (admin/admin)"
VM_IP=""
for _ in $(seq 1 60); do
  VM_IP="$(tart ip "$GOLDEN" --resolver arp 2>/dev/null || true)"
  if [ -n "$VM_IP" ] && sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_IP" true 2>/dev/null; then break; fi
  sleep 5
done
[ -n "$VM_IP" ] || { echo "VM never came up; see /tmp/openbase-golden-run.log"; exit 1; }
step "VM reachable at $VM_IP"

step "Provisioning: Homebrew, Node, Tailscale"
sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_IP" 'bash -s' <<'PROVISION'
set -e
if ! command -v brew >/dev/null 2>&1; then
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.profile
fi
eval "$(/opt/homebrew/bin/brew shellenv)"
brew install node tailscale >/dev/null 2>&1 || brew install node tailscale
echo "node $(node -v); tailscale $(command -v tailscale)"
PROVISION

step "Prewarming the driver's Playwright deps"
sshpass -p "$VM_PASS" scp -q "${SSH_OPTS[@]}" -r "$HERE/driver" "$VM_USER@$VM_IP:~/driver-warm"
sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_IP" \
  'eval "$(/opt/homebrew/bin/brew shellenv)"; cd ~/driver-warm && npm install --no-audit --no-fund >/dev/null 2>&1 && echo "playwright prewarmed"'
sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_IP" 'rm -rf ~/driver-warm'

step "Shutting the golden VM down"
tart stop "$GOLDEN" 2>/dev/null || true
kill "$RUN_PID" 2>/dev/null || true
trap - EXIT

echo
step "Golden VM '$GOLDEN' is ready."
echo "  Run a test with:"
echo "    ./install-tests/electron-macos/run.sh --tailscale-authkey tskey-..."
