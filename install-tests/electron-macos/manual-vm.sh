#!/usr/bin/env bash
#
# Boot a fresh, VISIBLE, BARE macOS VM so you can do the whole install manually —
# and choose which channel (main vs staging) to test from inside the VM.
#
# It clones a clean macOS base image (NOT the provisioned golden VM): no
# Homebrew, no Node, no Tailscale, nothing Openbase, and NO app. Inside the VM
# you download the real signed DMG for whichever channel you want and install it
# by hand, exactly as a user would.
#
# For the automated pass/fail test, use ./run.sh instead.
#
# Flags:
#   --app PATH        also drop a LOCAL prebuilt .app in the VM's ~/Downloads
#                     (unsigned dev build; for testing a local build instead of a
#                     released channel). Default: no app at all.
#   --source REF      macOS image/VM to clone (default: the cirruslabs base
#                     image; e.g. macos-sequoia-vanilla for even less)
#   --name NAME       clone name (default: openbase-manual)
#
# When done: tart delete <name>   (default: openbase-manual)

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP=""
SOURCE="ghcr.io/cirruslabs/macos-sequoia-base:latest"
NAME="openbase-manual"
VM_USER="admin"; VM_PASS="admin"

# Real user-facing macOS download URLs (signed + notarized), per channel.
DMG_BASE="https://openbase-coder-desktop-releases-632795836081-us-east-1.s3.amazonaws.com"
DMG_MAIN="$DMG_BASE/mac/Openbase-Coder-latest-arm64.dmg"
DMG_STAGING="$DMG_BASE/mac-staging/Openbase-Coder-latest-arm64.dmg"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app) APP="$2"; shift 2 ;;
    --source) SOURCE="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\033[34m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[31mFATAL\033[0m %s\n' "$*" >&2; exit 2; }
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10)
ssh_vm() { sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" "$VM_USER@$VM_IP" "$@"; }

command -v tart >/dev/null 2>&1 || die "tart not installed — run ./bootstrap-golden.sh (installs tart+sshpass)"
command -v sshpass >/dev/null 2>&1 || die "sshpass not installed — run ./bootstrap-golden.sh"
tart list 2>/dev/null | grep -q "[[:space:]]$NAME[[:space:]]" && die "VM '$NAME' already exists — delete it (tart delete $NAME) or pass --name."
[ -n "$APP" ] && { [ -d "$APP" ] || die "app bundle not found: $APP"; }

# --- Clone a fresh macOS + boot with a window --------------------------------
step "Cloning fresh macOS '$SOURCE' -> '$NAME'"
tart clone "$SOURCE" "$NAME"
step "Booting VM with a window (a clean macOS desktop opens on your screen)"
nohup tart run "$NAME" >/tmp/openbase-manual-$NAME.log 2>&1 &
disown || true

step "Waiting for VM IP + SSH"
VM_IP=""
for _ in $(seq 1 60); do
  VM_IP="$(tart ip "$NAME" --resolver arp 2>/dev/null || true)"
  if [ -n "$VM_IP" ] && ssh_vm true 2>/dev/null; then break; fi
  sleep 5
done
[ -n "$VM_IP" ] && ssh_vm true 2>/dev/null || die "VM SSH never came up"
step "VM reachable at $VM_IP (ssh $VM_USER@$VM_IP, password: $VM_PASS)"

# --- Optionally hand over a LOCAL build (off by default) ---------------------
if [ -n "$APP" ]; then
  APP_BASENAME="$(basename "$APP")"
  step "Placing local $APP_BASENAME in the VM's ~/Downloads (unsigned dev build)"
  ssh_vm "rm -rf ~/Downloads/'$APP_BASENAME'"
  sshpass -p "$VM_PASS" scp -q "${SSH_OPTS[@]}" -r "$APP" "$VM_USER@$VM_IP:~/Downloads/$APP_BASENAME"
fi

cat <<DONE

$(printf '\033[32m==> Ready.\033[0m') A fresh, bare macOS VM is on your screen. Nothing Openbase is
installed. Log in inside the VM as: $VM_USER / $VM_PASS

To install a REAL release, open Terminal IN THE VM and download the channel you
want (signed + notarized, so Gatekeeper works normally):

  # main / stable
  curl -L -o ~/Downloads/Openbase.dmg "$DMG_MAIN"

  # staging
  curl -L -o ~/Downloads/Openbase.dmg "$DMG_STAGING"

Then open the DMG, drag the app to /Applications, and run onboarding (it will
prompt you to install Tailscale yourself).
$( [ -n "$APP" ] && printf '\nA local unsigned dev build is also in ~/Downloads/%s (right-click > Open to bypass Gatekeeper).\n' "$APP_BASENAME" )
  SSH into it:        sshpass -p $VM_PASS ssh $VM_USER@$VM_IP
  Delete when done:   tart delete $NAME
DONE
