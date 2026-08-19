#!/usr/bin/env bash
#
# End-to-end test of the STANDALONE installation flow (the production pathway a
# real user gets): cli/scripts/install.sh unpacks a release tarball into
# ~/.openbase/packages/standalone, wires up the ~/.local/bin launcher, and adds
# it to the shell profile.
#
# This runs the real install.sh against a real package tarball inside a sandbox
# $HOME (see lib/common.sh) so your machine's actual install is never touched.
#
# Package tarball resolution:
#   1. If $OPENBASE_CODER_INSTALL_TARBALL is set, that tarball is used (fully
#      offline — same hook CI uses to verify install.sh against a fresh build).
#   2. Otherwise a tarball is built from the local cli/ checkout with
#      scripts/build_standalone_package.py. This needs a livekit-server binary
#      (found at ~/.openbase/bin/livekit-server, or pass --livekit-bin PATH) and
#      may download a standalone Python the first time.
#
# Flags:
#   --full        also run `openbase-coder setup --skip-services` against the
#                 installed standalone package (writes installation.json,
#                 generates ~/.openbase). Needs network for the coding backend.
#   --keep        keep the sandbox dir on exit (also: KEEP_SANDBOX=1).
#   --livekit-bin PATH   livekit-server binary to bundle when building.
#
# Usage:
#   ./install-tests/test-standalone-install.sh
#   OPENBASE_CODER_INSTALL_TARBALL=/path/pkg.tar.gz ./install-tests/test-standalone-install.sh
#   ./install-tests/test-standalone-install.sh --full

set -euo pipefail
# shellcheck source=lib/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

CURRENT_TEST_NAME="standalone install (install.sh)"
RUN_FULL=0
LIVEKIT_BIN=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --full) RUN_FULL=1; shift ;;
    --keep) export KEEP_SANDBOX=1; shift ;;
    --livekit-bin) LIVEKIT_BIN="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) fatal "unknown argument: $1" ;;
  esac
done

trap sandbox_cleanup EXIT

# --- Resolve or build the package tarball (BEFORE sandboxing $HOME, so the
#     build uses the real toolchain/caches) -------------------------------------

TARBALL="${OPENBASE_CODER_INSTALL_TARBALL:-}"

build_tarball() {
  local lkbin="$LIVEKIT_BIN"
  [ -z "$lkbin" ] && lkbin="$REAL_HOME/.openbase/bin/livekit-server"
  if [ ! -x "$lkbin" ]; then
    fatal "no livekit-server binary to bundle (looked at $lkbin). Pass --livekit-bin PATH, or set OPENBASE_CODER_INSTALL_TARBALL to a prebuilt tarball."
  fi

  local build_root pkg_dir version target asset
  build_root="$(mktemp -d "${TMPDIR:-/tmp}/openbase-pkg-build.XXXXXX")"
  pkg_dir="$build_root/pkg"
  # A clean PEP 440 version the build's own version-stamp assertion accepts.
  # hatch-vcs otherwise overrides --version with the git-derived dev version,
  # so we also pin it via SETUPTOOLS_SCM_PRETEND_VERSION (mirrors CI).
  version="0.0.0"
  target="$(uname -m | sed 's/arm64/aarch64/;s/x86_64/x86_64/')-apple-darwin"
  asset="$build_root/openbase-coder-package-$target.tar.gz"

  log "Building a standalone package to test install.sh against"
  note "livekit-server: $lkbin"
  note "this can take a few minutes and may download a standalone Python"
  ( cd "$CLI_DIR" && SETUPTOOLS_SCM_PRETEND_VERSION="$version" \
    uv run python scripts/build_standalone_package.py \
      --version "$version" \
      --target "$target" \
      --channel installtest \
      --livekit-server-bin "$lkbin" \
      --package-dir "$pkg_dir" \
      --skip-console-build \
      --force ) || fatal "package build failed"

  tar -czf "$asset" -C "$pkg_dir" .
  TARBALL="$asset"
  # Remember the build root so cleanup removes it too.
  BUILD_ROOT_TO_CLEAN="$build_root"
}

BUILD_ROOT_TO_CLEAN=""
cleanup_build() { [ -n "$BUILD_ROOT_TO_CLEAN" ] && [ "${KEEP_SANDBOX:-0}" != "1" ] && rm -rf "$BUILD_ROOT_TO_CLEAN"; }
trap 'sandbox_cleanup; cleanup_build' EXIT

if [ -n "$TARBALL" ]; then
  [ -f "$TARBALL" ] || fatal "OPENBASE_CODER_INSTALL_TARBALL is set but not a file: $TARBALL"
  log "Using provided tarball: $TARBALL"
else
  build_tarball
fi

EXPECTED_VERSION="$(python3 -c 'import json,sys,tarfile
tf=tarfile.open(sys.argv[1])
m=tf.extractfile("./openbase-coder-package.json") or tf.extractfile("openbase-coder-package.json")
print(json.load(m)["version"])' "$TARBALL")"
log "Package version under test: $EXPECTED_VERSION"

# --- Sandbox and run install.sh ----------------------------------------------

sandbox_create

log "Running install.sh in the sandbox"
if OPENBASE_CODER_INSTALL_TARBALL="$TARBALL" \
   OPENBASE_CODER_HOME="$SBX_HOME/.openbase" \
   OPENBASE_CODER_INSTALL_BIN_DIR="$SBX_HOME/.local/bin" \
   sh "$CLI_DIR/scripts/install.sh" > "$SANDBOX_ROOT/install.log" 2>&1; then
  pass "install.sh completed successfully"
else
  fail "install.sh exited non-zero (see below)"
  sed 's/^/    | /' "$SANDBOX_ROOT/install.log"
fi

# --- Assert the installed layout ---------------------------------------------

PKG_ROOT="$SBX_HOME/.openbase/packages/standalone"
CURRENT="$PKG_ROOT/current"
LAUNCHER="$SBX_HOME/.local/bin/openbase-coder"

log "Verifying standalone install layout"
assert_dir  "$PKG_ROOT/releases"                 "releases directory created"
assert_symlink "$CURRENT"                         "current -> release symlink created"
assert_file "$CURRENT/openbase-coder-package.json" "package metadata present in current release"
assert_executable "$CURRENT/bin/openbase-coder"   "packaged launcher is executable"
assert_file "$LAUNCHER"                            "~/.local/bin launcher wrapper created"
# install.sh writes a wrapper script (not a symlink) so $0 resolves the package.
if [ -f "$LAUNCHER" ] && [ ! -L "$LAUNCHER" ]; then
  pass "launcher is a wrapper script, not a symlink"
else
  fail "launcher should be a plain wrapper script (got symlink or missing)"
fi
assert_file_contains "$LAUNCHER" "$CURRENT/bin/openbase-coder" "launcher execs the current release"

# The launcher must actually run and report the packaged version.
if [ -x "$LAUNCHER" ]; then
  ACTUAL_VERSION="$("$LAUNCHER" --version 2>/dev/null | grep -oE '[0-9][^ ]*' | head -1 || true)"
  if printf '%s' "$EXPECTED_VERSION" | grep -Fq "$ACTUAL_VERSION" 2>/dev/null || \
     printf '%s' "$ACTUAL_VERSION" | grep -Fq "$EXPECTED_VERSION" 2>/dev/null; then
    pass "launcher --version reports the packaged version ($ACTUAL_VERSION)"
  else
    fail "launcher --version was '$ACTUAL_VERSION', expected to match package '$EXPECTED_VERSION'"
  fi
fi

# PATH wiring in the (sandboxed) shell profile.
PROFILE="$SBX_HOME/.zprofile"
[ -f "$SBX_HOME/.bash_profile" ] && PROFILE="$SBX_HOME/.bash_profile"
assert_file_contains "$PROFILE" "Openbase Coder installer" "shell profile updated with PATH block"

# --- Guard: a dev-workspace setup must refuse over a standalone install -------

log "Verifying scripts/setup refuses to run over a standalone install"
SETUP_OUT="$SANDBOX_ROOT/setup-guard.log"
if "$WORKSPACE_DIR/scripts/setup" --backend openbase-cloud > "$SETUP_OUT" 2>&1; then
  fail "scripts/setup should have refused (standalone install present) but exited 0"
else
  pass "scripts/setup refused to run over the standalone install"
  if grep -Fq "uninstall" "$SETUP_OUT"; then
    pass "refusal points the user at the uninstall docs"
  else
    fail "refusal message did not mention uninstalling"
  fi
fi

# --- Optional: run the real setup against the standalone package -------------

if [ "$RUN_FULL" = "1" ]; then
  log "[--full] Running openbase-coder setup against the standalone package"
  note "this needs network for the coding backend and may take a while"
  SETUP_LOG="$SANDBOX_ROOT/standalone-setup.log"
  if OPENBASE_CODER_PACKAGE_DIR="$CURRENT" \
     "$LAUNCHER" setup --skip-services --non-interactive --backend openbase-cloud \
     > "$SETUP_LOG" 2>&1; then
    pass "standalone setup --skip-services completed"
  else
    fail "standalone setup failed (tail below)"
    tail -n 25 "$SETUP_LOG" | sed 's/^/    | /'
  fi
  INSTALL_JSON="$SBX_HOME/.openbase/installation.json"
  assert_file "$INSTALL_JSON" "installation.json written"
  if [ -f "$INSTALL_JSON" ]; then
    assert_eq "$(json_field "$INSTALL_JSON" standalone)" "true" "installation.json marks the install standalone"
  fi
fi

report_summary
