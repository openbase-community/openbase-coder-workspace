#!/usr/bin/env bash
#
# Host-side semantic-automation toolkit for a running Tart macOS VM.
#
# Purpose: keep VM images PURE (nothing baked in — no Node, no Homebrew, no
# helpers) while still giving agents byte-exact, semantic control of the guest.
# Everything here works against a bare clone over SSH + forwarded sockets;
# nothing is installed into the guest image, and anything injected lands only
# in the disposable clone.
#
# Why this exists: Tart window keystroke forwarding corrupts shifted/option
# characters even with matching host/guest layouts (openai/tart#1167), and
# clipboard sharing is image-version dependent. Field tests must not enter
# text through the Tart window — use the semantic paths below instead.
#
# Subcommands (all take the VM name as first arg unless noted):
#   ip NAME                     print the VM's IP (arp resolver)
#   ssh NAME [CMD...]           run a command in the guest (or interactive)
#   push NAME SRC DEST          scp a file/dir into the guest
#   pin-layout NAME             pin the guest to the U.S. keyboard layout
#   enable-safaridriver NAME    enable safaridriver in the guest (built-in)
#   safari-tunnel NAME [PORT]   start guest safaridriver + forward to host
#                               (prints the local WebDriver endpoint; leave
#                               running, Ctrl-C to stop)
#   app-cdp NAME [APP] [PORT]   launch the installed Electron app in the guest
#                               GUI session with a CDP port + forward to host
#                               (prints the local CDP endpoint; leave running)
#
# The default credentials are the cirruslabs CI image's admin/admin. Override
# with VM_USER / VM_PASS env vars.
#
# Text entry rules for drivers built on these endpoints:
#   - Electron app UI  -> driver/host-drive.mjs over the app-cdp endpoint
#   - Guest web pages  -> Safari via the safari-tunnel WebDriver endpoint
#   - OS dialogs       -> keep using the Tart window (clicks are reliable;
#                         only TEXT ENTRY through the window is not)

set -euo pipefail

VM_USER="${VM_USER:-admin}"; VM_PASS="${VM_PASS:-admin}"
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10)

die() { printf '\033[31mFATAL\033[0m %s\n' "$*" >&2; exit 2; }
step() { printf '\033[34m==>\033[0m %s\n' "$*"; }

vm_ip() {
  local name="$1" ip=""
  ip="$(tart ip "$name" --resolver arp 2>/dev/null || true)"
  [ -n "$ip" ] || die "no IP for VM '$name' — is it running?"
  printf '%s' "$ip"
}

ssh_vm() { # IP CMD...
  local ip="$1"; shift
  sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" "$VM_USER@$ip" "$@"
}

cmd="${1:-}"; shift || true
case "$cmd" in
  ip)
    vm_ip "${1:?usage: guest-automate.sh ip NAME}"; echo ;;

  ssh)
    NAME="${1:?usage: guest-automate.sh ssh NAME [CMD...]}"; shift
    ssh_vm "$(vm_ip "$NAME")" "$@" ;;

  push)
    NAME="${1:?usage: guest-automate.sh push NAME SRC DEST}"
    SRC="${2:?src}"; DEST="${3:?dest}"
    IP="$(vm_ip "$NAME")"
    sshpass -p "$VM_PASS" scp -q "${SSH_OPTS[@]}" -r "$SRC" "$VM_USER@$IP:$DEST"
    step "pushed $SRC -> $NAME:$DEST" ;;

  pin-layout)
    # Hygiene only: pins the guest input source to plain U.S. It does NOT fix
    # option-key symbol corruption through the Tart window (openai/tart#1167) —
    # that path stays unreliable for text; use the semantic endpoints instead.
    NAME="${1:?usage: guest-automate.sh pin-layout NAME}"
    IP="$(vm_ip "$NAME")"
    ssh_vm "$IP" '
      defaults write com.apple.HIToolbox AppleEnabledInputSources -array \
        "<dict><key>InputSourceKind</key><string>Keyboard Layout</string><key>KeyboardLayout ID</key><integer>0</integer><key>KeyboardLayout Name</key><string>U.S.</string></dict>"
      defaults write com.apple.HIToolbox AppleSelectedInputSources -array \
        "<dict><key>InputSourceKind</key><string>Keyboard Layout</string><key>KeyboardLayout ID</key><integer>0</integer><key>KeyboardLayout Name</key><string>U.S.</string></dict>"
      defaults delete com.apple.HIToolbox AppleInputSourceHistory 2>/dev/null || true
    '
    step "guest input source pinned to U.S. (takes effect for new processes / after login)" ;;

  enable-safaridriver)
    NAME="${1:?usage: guest-automate.sh enable-safaridriver NAME}"
    IP="$(vm_ip "$NAME")"
    # safaridriver ships with macOS; enabling needs sudo once per guest.
    ssh_vm "$IP" "echo '$VM_PASS' | sudo -S safaridriver --enable" \
      && step "safaridriver enabled in '$NAME' (nothing installed)" ;;

  safari-tunnel)
    NAME="${1:?usage: guest-automate.sh safari-tunnel NAME [PORT]}"
    PORT="${2:-4444}"
    IP="$(vm_ip "$NAME")"
    step "starting guest safaridriver on :$PORT and forwarding to localhost:$PORT"
    step "WebDriver endpoint: http://127.0.0.1:$PORT  (Ctrl-C to stop)"
    # -t keeps safaridriver attached to the ssh session so Ctrl-C cleans up.
    sshpass -p "$VM_PASS" ssh -t "${SSH_OPTS[@]}" -L "$PORT:127.0.0.1:$PORT" \
      "$VM_USER@$IP" "/usr/bin/safaridriver --port $PORT" ;;

  app-cdp)
    NAME="${1:?usage: guest-automate.sh app-cdp NAME [APP_PATH] [PORT]}"
    APP="${2:-/Applications/Openbase Coder.app}"
    PORT="${3:-9222}"
    IP="$(vm_ip "$NAME")"
    # Resolve the bundle's executable, then launch it inside the GUI (Aqua)
    # session with a CDP port. --remote-debugging-port is a debug-only launch
    # deviation from a Finder double-click; keep one pure launch in the run's
    # smoke pass and record this flag as a known deviation in the field log.
    ssh_vm "$IP" "
      set -e
      EXE=\"\$(/usr/bin/defaults read '$APP/Contents/Info' CFBundleExecutable)\"
      UID_N=\"\$(id -u)\"
      launchctl asuser \"\$UID_N\" nohup \"$APP/Contents/MacOS/\$EXE\" \
        --remote-debugging-port=$PORT >/tmp/openbase-cdp-launch.log 2>&1 &
      sleep 2
      curl -sf http://127.0.0.1:$PORT/json/version >/dev/null \
        || { echo 'CDP endpoint not up yet — check /tmp/openbase-cdp-launch.log'; exit 1; }
    "
    step "app launched with CDP on guest :$PORT — forwarding to localhost:$PORT"
    step "CDP endpoint: http://127.0.0.1:$PORT  (Ctrl-C to stop)"
    step "drive it: node driver/host-drive.mjs --cdp http://127.0.0.1:$PORT <cmd...>"
    sshpass -p "$VM_PASS" ssh -N "${SSH_OPTS[@]}" -L "$PORT:127.0.0.1:$PORT" "$VM_USER@$IP" ;;

  *)
    sed -n '2,40p' "$0"; exit 2 ;;
esac
