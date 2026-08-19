# shellcheck shell=bash
#
# Shared harness for Openbase Coder installation-flow tests.
#
# The whole point of these tests is to exercise the REAL install entrypoints
# (cli/scripts/install.sh and the dev-workspace `openbase-coder setup`) without
# uninstalling/reinstalling Openbase on the developer's actual machine. We do
# that by running each flow inside a throwaway sandbox $HOME.
#
# Why a sandbox $HOME is sufficient:
#   - openbase_coder_cli/paths.py derives every managed path from
#     `Path.home()`, which honors $HOME. So ~/.openbase, ~/.local/bin,
#     ~/Library/LaunchAgents, ~/.claude, ~/.codex, and the shell profile all
#     redirect into the sandbox.
#   - install.sh additionally honors OPENBASE_CODER_HOME and
#     OPENBASE_CODER_INSTALL_BIN_DIR, which we also point at the sandbox.
#
# The two things that are NOT $HOME-scoped, and how we neutralize them:
#   - launchd/launchctl services (a per-user domain): every flow is run with
#     `--skip-services`, so no real LaunchAgent is ever bootstrapped.
#   - Tailscale Serve (machine-level routes): `configure_tailscale_serve()`
#     resolves the CLI via `shutil.which("tailscale")` first, so we shadow it
#     with a no-op stub placed first on PATH. The real tailnet is never touched.
#
# Nothing here should ever run against the real $HOME. `sandbox_guard` is the
# interlock that enforces that.

set -euo pipefail

# --- Locate the workspace -----------------------------------------------------

# lib/ -> install-tests/ -> workspace root
COMMON_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_TESTS_DIR="$(cd "$COMMON_LIB_DIR/.." && pwd)"
WORKSPACE_DIR="$(cd "$INSTALL_TESTS_DIR/.." && pwd)"
CLI_DIR="$WORKSPACE_DIR/cli"

# The developer's real home, captured before we ever touch $HOME.
REAL_HOME="$HOME"

# --- Pretty output ------------------------------------------------------------

if [ -t 1 ]; then
  C_RESET="$(printf '\033[0m')"
  C_RED="$(printf '\033[31m')"
  C_GREEN="$(printf '\033[32m')"
  C_YELLOW="$(printf '\033[33m')"
  C_BLUE="$(printf '\033[34m')"
  C_DIM="$(printf '\033[2m')"
else
  C_RESET="" C_RED="" C_GREEN="" C_YELLOW="" C_BLUE="" C_DIM=""
fi

TESTS_PASSED=0
TESTS_FAILED=0
CURRENT_TEST_NAME="${CURRENT_TEST_NAME:-installation test}"

log()   { printf '%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
note()  { printf '%s    %s%s\n' "$C_DIM" "$*" "$C_RESET"; }
warn()  { printf '%sWARN%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
fatal() { printf '%sFATAL%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 2; }

pass() {
  TESTS_PASSED=$((TESTS_PASSED + 1))
  printf '  %sPASS%s %s\n' "$C_GREEN" "$C_RESET" "$*"
}

fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  printf '  %sFAIL%s %s\n' "$C_RED" "$C_RESET" "$*"
}

# --- Assertions ---------------------------------------------------------------
# Each takes a human description as the last argument.

assert_dir() {
  local path="$1" desc="${2:-directory exists: $1}"
  if [ -d "$path" ]; then pass "$desc"; else fail "$desc (missing dir: $path)"; fi
}

assert_file() {
  local path="$1" desc="${2:-file exists: $1}"
  if [ -f "$path" ]; then pass "$desc"; else fail "$desc (missing file: $path)"; fi
}

assert_symlink() {
  local path="$1" desc="${2:-symlink exists: $1}"
  if [ -L "$path" ]; then pass "$desc"; else fail "$desc (not a symlink: $path)"; fi
}

assert_executable() {
  local path="$1" desc="${2:-executable: $1}"
  if [ -x "$path" ]; then pass "$desc"; else fail "$desc (not executable: $path)"; fi
}

# assert_file_contains <path> <fixed-string> <desc>
assert_file_contains() {
  local path="$1" needle="$2" desc="$3"
  if [ -f "$path" ] && grep -Fq "$needle" "$path"; then
    pass "$desc"
  else
    fail "$desc (expected '$needle' in $path)"
  fi
}

# assert_eq <actual> <expected> <desc>
assert_eq() {
  local actual="$1" expected="$2" desc="$3"
  if [ "$actual" = "$expected" ]; then
    pass "$desc"
  else
    fail "$desc (got '$actual', expected '$expected')"
  fi
}

# assert_cmd <desc> -- <command...>  (passes when the command exits 0)
assert_cmd() {
  local desc="$1"; shift
  [ "$1" = "--" ] && shift
  if "$@" >/dev/null 2>&1; then
    pass "$desc"
  else
    fail "$desc (command failed: $*)"
  fi
}

# assert_cmd_fails <desc> -- <command...>  (passes when the command exits != 0)
assert_cmd_fails() {
  local desc="$1"; shift
  [ "$1" = "--" ] && shift
  if "$@" >/dev/null 2>&1; then
    fail "$desc (command unexpectedly succeeded: $*)"
  else
    pass "$desc"
  fi
}

# json_field <file> <dotted.path> -> prints the value (via python)
json_field() {
  local file="$1" path="$2"
  python3 - "$file" "$path" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    data = json.load(fh)
cur = data
for part in sys.argv[2].split("."):
    if part == "":
        continue
    cur = cur[part]
print(cur if not isinstance(cur, bool) else str(cur).lower())
PY
}

# --- Sandbox lifecycle --------------------------------------------------------

SANDBOX_ROOT=""
SBX_HOME=""

# Create an isolated $HOME and rewire the environment so every install flow
# writes only inside it. Call once at the top of a test.
sandbox_create() {
  SANDBOX_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/openbase-install-test.XXXXXX")"
  SBX_HOME="$SANDBOX_ROOT/home"
  mkdir -p "$SBX_HOME/.local/bin" "$SANDBOX_ROOT/bin"

  # Marker file used by sandbox_guard to prove $HOME is really the sandbox.
  printf 'openbase-coder installation-test sandbox\n' > "$SBX_HOME/.openbase-install-test-sandbox"

  _install_tailscale_stub

  # Rewire the environment. Order matters: the stub bin must precede the real
  # tailscale so shutil.which() resolves ours.
  #
  # Deliberately do NOT put the sandbox's ~/.local/bin on PATH: install.sh only
  # writes its PATH block to the shell profile when the bin dir is absent from
  # PATH, and we want to exercise that. Tests invoke the launcher by absolute
  # path, so it need not be resolvable by name.
  export HOME="$SBX_HOME"
  export OPENBASE_CODER_HOME="$SBX_HOME/.openbase"
  export OPENBASE_CODER_INSTALL_BIN_DIR="$SBX_HOME/.local/bin"
  export PATH="$SANDBOX_ROOT/bin:$PATH"

  # Reuse the real caches (read-mostly, non-destructive) so a full run does not
  # re-download every Python/pnpm artifact into the throwaway home.
  export UV_CACHE_DIR="${UV_CACHE_DIR:-$REAL_HOME/.cache/uv}"

  # Non-interactive, no colours-that-confuse-parsers inside the flows.
  export CI="${CI:-1}"

  sandbox_guard
  log "Sandbox home: $SBX_HOME"
  note "real home ($REAL_HOME) is untouched; services skipped; tailscale stubbed"
}

# Abort loudly if $HOME is anything other than our sandbox. Every step that
# could mutate the filesystem should be preceded (directly or transitively) by
# a sandbox_create, and this guard is the last line of defense.
sandbox_guard() {
  if [ -z "$SBX_HOME" ] || [ "$HOME" != "$SBX_HOME" ]; then
    fatal "sandbox guard: \$HOME ($HOME) is not the sandbox ($SBX_HOME) — refusing to continue"
  fi
  if [ "$HOME" = "$REAL_HOME" ]; then
    fatal "sandbox guard: \$HOME equals the real home — refusing to continue"
  fi
  if [ ! -f "$SBX_HOME/.openbase-install-test-sandbox" ]; then
    fatal "sandbox guard: sandbox marker missing — refusing to continue"
  fi
}

# A no-op tailscale that satisfies configure_tailscale_serve()/health without
# touching the real tailnet. `serve` succeeds silently; status queries return
# an empty object so the setup health probe reports "not configured" and skips
# its 30s wait loop instead of blocking.
_install_tailscale_stub() {
  cat > "$SANDBOX_ROOT/bin/tailscale" <<'STUB'
#!/bin/sh
# Installation-test stub. Never contacts the real tailnet.
case "$*" in
  *"serve status"*) printf '{}\n' ;;
  status*)          printf '{}\n' ;;
  serve*)           : ;;   # no-op, exit 0
  *)                : ;;
esac
exit 0
STUB
  chmod 0755 "$SANDBOX_ROOT/bin/tailscale"
}

# Seed a fake existing installation.json in the sandbox, for guard tests.
# Usage: seed_installation_json <standalone true|false> [workspace_path]
seed_installation_json() {
  local standalone="$1" workspace_path="${2:-}"
  sandbox_guard
  mkdir -p "$SBX_HOME/.openbase"
  python3 - "$SBX_HOME/.openbase/installation.json" "$standalone" "$workspace_path" <<'PY'
import json, sys
path, standalone, workspace_path = sys.argv[1], sys.argv[2] == "true", sys.argv[3]
doc = {
    "schema_version": 1,
    "workspace_path": workspace_path,
    "env_file": "",
    "standalone": standalone,
}
with open(path, "w") as fh:
    json.dump(doc, fh, indent=2)
PY
}

sandbox_cleanup() {
  if [ -n "$SANDBOX_ROOT" ] && [ -d "$SANDBOX_ROOT" ]; then
    if [ "${KEEP_SANDBOX:-0}" = "1" ]; then
      warn "KEEP_SANDBOX=1 — leaving sandbox at $SANDBOX_ROOT"
    else
      rm -rf "$SANDBOX_ROOT"
    fi
  fi
}

# --- Summary ------------------------------------------------------------------

report_summary() {
  local name="${1:-$CURRENT_TEST_NAME}"
  printf '\n%s--- %s ---%s\n' "$C_BLUE" "$name" "$C_RESET"
  printf '  passed: %s%d%s   failed: %s%d%s\n' \
    "$C_GREEN" "$TESTS_PASSED" "$C_RESET" \
    "$([ "$TESTS_FAILED" -gt 0 ] && printf '%s' "$C_RED" || printf '%s' "$C_GREEN")" \
    "$TESTS_FAILED" "$C_RESET"
  if [ "$TESTS_FAILED" -gt 0 ]; then
    return 1
  fi
  return 0
}
