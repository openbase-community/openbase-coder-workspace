#!/usr/bin/env bash
#
# Run the Openbase Coder macOS installation-flow tests.
#
#   Runs the developer install flow (cli/scripts/install.sh) in a sandbox $HOME
#   — fast, safe, no VM. Your real install is never touched. Flags (--full,
#   --keep) are forwarded to it.
#
# The Electron app install flow runs in a disposable Tart VM and needs a
# one-time golden image plus a Tailscale auth key, so it is run separately:
#   ./install-tests/electron-macos/bootstrap-golden.sh                       # one-time
#   ./install-tests/electron-macos/run.sh --tailscale-authkey tskey-auth-... # a run
#
# Examples:
#   ./install-tests/run-all.sh
#   ./install-tests/run-all.sh --full

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

printf '\n\033[1m========== developer install (install.sh) ==========\033[0m\n'
if bash "$HERE/test-standalone-install.sh" "$@"; then
  printf '\n\033[32mPASS  developer install (install.sh)\033[0m\n'
  printf '\033[2mElectron flow: run ./install-tests/electron-macos/run.sh --tailscale-authkey ...\033[0m\n'
  exit 0
else
  printf '\n\033[31mFAIL  developer install (install.sh)\033[0m\n'
  exit 1
fi
