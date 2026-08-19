#!/bin/bash
# Runs INSIDE the VM. Installs the app to /Applications and runs the Playwright
# onboarding driver inside the active GUI (Aqua) session so Electron can reach
# WindowServer. $1 = app bundle basename (e.g. "Openbase.app").
set -e
eval "$(/opt/homebrew/bin/brew shellenv)"
APP_BASENAME="${1:-Openbase.app}"
APPDST="/Applications/$APP_BASENAME"

echo "== clean prior state (kill any app/driver, reset ~/.openbase) =="
# The driver runs as root via `launchctl asuser`, so sudo-kill it.
sudo pkill -9 -f onboard-and-verify 2>/dev/null || true
sudo pkill -9 -f "$APP_BASENAME/Contents" 2>/dev/null || true
sudo pkill -9 -f "Openbase Helper" 2>/dev/null || true
sleep 2
for p in "$HOME"/Library/LaunchAgents/com.openbase.coder*.plist; do
  [ -e "$p" ] && launchctl bootout "gui/$(id -u)/$(basename "$p" .plist)" 2>/dev/null || true
done
rm -f "$HOME"/Library/LaunchAgents/com.openbase.coder*.plist 2>/dev/null || true
rm -rf "$HOME/.openbase" 2>/dev/null || true
echo "cleaned; ~/.openbase present? $([ -d "$HOME/.openbase" ] && echo yes || echo no)"

echo "== install app to /Applications =="
rm -rf "$APPDST"
cp -R "$HOME/install-test/app" "$APPDST"
xattr -dr com.apple.quarantine "$APPDST" 2>/dev/null || true
echo "installed: $(defaults read "$APPDST/Contents/Info" CFBundleShortVersionString)"

echo "== npm install driver deps =="
cd "$HOME/install-test/driver"
npm install --no-audit --no-fund --silent

echo "== run driver in GUI session =="
UID_N="$(id -u)"
NODE="$(command -v node)"
RESULT="$HOME/install-test/result.json"

# The app re-activates the bundled CLI on every prereq poll; the driver waits for
# that to settle, but the race can occasionally not converge. Retry the whole
# onboarding->setup a few times, re-cleaning state each attempt.
ATTEMPTS="${ATTEMPTS:-3}"
rc=1
for attempt in $(seq 1 "$ATTEMPTS"); do
  echo "== driver attempt $attempt/$ATTEMPTS =="
  sudo pkill -9 -f onboard-and-verify 2>/dev/null || true
  sudo pkill -9 -f "$APP_BASENAME/Contents" 2>/dev/null || true
  sleep 2
  for p in "$HOME"/Library/LaunchAgents/com.openbase.coder*.plist; do
    [ -e "$p" ] && launchctl bootout "gui/$UID_N/$(basename "$p" .plist)" 2>/dev/null || true
  done
  rm -f "$HOME"/Library/LaunchAgents/com.openbase.coder*.plist 2>/dev/null || true
  rm -rf "$HOME/.openbase" 2>/dev/null || true

  sudo launchctl asuser "$UID_N" sudo -u "$USER" \
    env PATH="$PATH" HOME="$HOME" \
        APP_PATH="$APPDST" \
        RESULT="$RESULT" \
        TIMEOUT_MS="${TIMEOUT_MS:-900000}" \
    "$NODE" "$HOME/install-test/driver/onboard-and-verify.mjs"
  rc=$?
  [ "$rc" -eq 0 ] && { echo "== driver passed on attempt $attempt =="; break; }
  echo "== driver attempt $attempt failed (rc=$rc) =="
done
exit "$rc"
