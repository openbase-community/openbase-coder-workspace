#!/usr/bin/env bash
#
# Orchestrate the macOS Electron install-flow test in a disposable Tart VM.
#
#   host: build the bundled dev app (unless --app given)
#   VM:   clone golden -> join tailnet -> install app to /Applications ->
#         Playwright clickthrough of onboarding's Setup step -> verify install
#         -> delete clone
#
# Nothing runs against your real machine except the host build. The VM clone is
# always deleted at the end (kept only with --keep-on-fail, on failure).
#
# The desktop onboarding requires Tailscale CONNECTED before it will run setup,
# so a Tailscale auth key is required. Generate an ephemeral+reusable key at
# https://login.tailscale.com/admin/settings/keys and pass it via
# --tailscale-authkey or the TS_AUTHKEY env var.
#
# Flags:
#   --app PATH             use a prebuilt .app instead of building on the host
#   --tailscale-authkey K  Tailscale ephemeral auth key (or env TS_AUTHKEY)
#   --golden NAME          golden VM to clone (default: openbase-golden)
#   --keep-on-fail         keep the VM clone if the test fails (for debugging)
#   --vm-user / --vm-pass  VM ssh creds (default admin/admin, cirruslabs base)
#
# Prereq: run ./bootstrap-golden.sh once to install tart+sshpass and bake the
# golden VM (Node, Tailscale client, Playwright).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP=""
GOLDEN="openbase-golden"
KEEP_ON_FAIL=0
VM_USER="admin"
VM_PASS="admin"
TS_AUTHKEY="${TS_AUTHKEY:-}"
INSTANCE="openbase-install-test-$$"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app) APP="$2"; shift 2 ;;
    --tailscale-authkey) TS_AUTHKEY="$2"; shift 2 ;;
    --golden) GOLDEN="$2"; shift 2 ;;
    --keep-on-fail) KEEP_ON_FAIL=1; shift ;;
    --vm-user) VM_USER="$2"; shift 2 ;;
    --vm-pass) VM_PASS="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\033[34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31mFATAL\033[0m %s\n' "$*" >&2; exit 2; }

command -v tart >/dev/null 2>&1 || die "tart not installed — run ./bootstrap-golden.sh"
command -v sshpass >/dev/null 2>&1 || die "sshpass not installed — run ./bootstrap-golden.sh"
tart list 2>/dev/null | grep -q "[[:space:]]$GOLDEN[[:space:]]" || \
  die "golden VM '$GOLDEN' not found — run ./bootstrap-golden.sh"
[ -n "$TS_AUTHKEY" ] || die "Tailscale auth key required (--tailscale-authkey or TS_AUTHKEY). Onboarding needs Tailscale connected."

SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10)
VM_IP=""
ssh_vm()  { sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_IP" "$@"; }
scp_vm()  { sshpass -p "$VM_PASS" scp -q "${SSH_OPTS[@]}" -r "$@"; }
# tart's default DHCP-lease resolver can go stale mid-run; ARP is reliable.
vm_ip()   { tart ip "$INSTANCE" --resolver arp 2>/dev/null || true; }

VM_RUN_PID=""
TEST_OK=1
cleanup() {
  [ -n "$VM_RUN_PID" ] && kill "$VM_RUN_PID" 2>/dev/null || true
  if tart list 2>/dev/null | grep -q "[[:space:]]$INSTANCE[[:space:]]"; then
    if [ "$TEST_OK" = "0" ] && [ "$KEEP_ON_FAIL" = "1" ]; then
      printf '\033[33mWARN\033[0m keeping failed VM clone: %s (ip %s)\n' "$INSTANCE" "$(vm_ip)"
      return
    fi
    step "Deleting VM clone $INSTANCE"
    tart stop "$INSTANCE" 2>/dev/null || true
    tart delete "$INSTANCE" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# --- 1. Build (host) ----------------------------------------------------------

if [ -z "$APP" ]; then
  step "Building the bundled dev app on the host"
  APP="$("$HERE/build-app.sh" | sed -n 's/^APP=//p' | tail -1)"
fi
[ -d "$APP" ] || die "app bundle not found: $APP"
APP_BASENAME="$(basename "$APP")"
step "App under test: $APP"

# --- 2. Clone + boot the VM ---------------------------------------------------

step "Cloning golden '$GOLDEN' -> '$INSTANCE'"
tart clone "$GOLDEN" "$INSTANCE"
step "Booting VM (headless)"
tart run "$INSTANCE" --no-graphics >/dev/null 2>&1 &
VM_RUN_PID=$!

step "Waiting for VM IP + SSH"
for _ in $(seq 1 60); do
  VM_IP="$(vm_ip)"
  if [ -n "$VM_IP" ] && ssh_vm true 2>/dev/null; then break; fi
  sleep 5
done
[ -n "$VM_IP" ] && ssh_vm true 2>/dev/null || die "VM SSH never came up"
step "VM reachable at $VM_IP"

# --- 3. Join the tailnet ------------------------------------------------------

step "Connecting VM to the tailnet"
ssh_vm 'bash -s -- '"$TS_AUTHKEY" < "$HERE/vm/ts-connect.sh" | grep -v "^tskey" || die "Tailscale connect failed"

# --- 4. Copy app + driver -----------------------------------------------------

step "Copying app + driver into the VM"
ssh_vm "mkdir -p ~/install-test/driver && rm -rf ~/install-test/app"
scp_vm "$APP" "$VM_USER@$VM_IP:~/install-test/app"
scp_vm "$HERE/driver/." "$VM_USER@$VM_IP:~/install-test/driver/"

# --- 5. Install + drive onboarding + verify -----------------------------------

step "Installing app + running the onboarding driver (this takes a few minutes)"
set +e
ssh_vm 'bash -s -- '"$APP_BASENAME" < "$HERE/vm/run-driver.sh"
DRIVER_RC=$?
set -e

# --- 6. Collect + report ------------------------------------------------------

scp_vm "$VM_USER@$VM_IP:~/install-test/result.json" "$HERE/last-result.json" 2>/dev/null || true
echo
if [ -f "$HERE/last-result.json" ]; then
  python3 - "$HERE/last-result.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for c in d.get("checks", []):
    print(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['name']}" + (f"  — {c['detail']}" if c.get('detail') else ""))
print(f"\n  result: {'PASS' if d.get('passed') else 'FAIL'}")
PY
fi

if [ "$DRIVER_RC" -ne 0 ]; then
  TEST_OK=0
  printf '\n\033[31mElectron install-flow test FAILED\033[0m (driver rc=%s)\n' "$DRIVER_RC"
  exit 1
fi
printf '\n\033[32mElectron install-flow test PASSED\033[0m\n'
