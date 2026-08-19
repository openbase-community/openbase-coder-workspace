#!/usr/bin/env bash
#
# Build the bundled macOS dev app for the Electron install-flow test.
#
# Mirrors the packaging path documented in the `live-installation-test` skill:
# build a standalone CLI package (with console), stage it + the macOS companion
# into the desktop app, then electron-builder a dev build with the real
# extraResources (bundled CLI + companion) intact. No notarization, no publish,
# unsigned (identity=null) for speed — the app runs inside a disposable VM.
#
# Output: desktop/release/mac-arm64/<ProductName>.app  (path printed on the
# last line as `APP=<path>` for run.sh to consume).
#
# Flags:
#   --livekit-bin PATH   livekit-server to bundle (default ~/.openbase/bin/livekit-server)
#   --skip-cli-build     reuse an existing cli/dist/openbase-coder-package
#   --sign               keep Developer ID signing (default: unsigned)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "$HERE/../.." && pwd)"
CLI_DIR="$WORKSPACE_DIR/cli"
DESKTOP_DIR="$WORKSPACE_DIR/desktop"

LIVEKIT_BIN="$HOME/.openbase/bin/livekit-server"
SKIP_CLI_BUILD=0
SIGN=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --livekit-bin) LIVEKIT_BIN="$2"; shift 2 ;;
    --skip-cli-build) SKIP_CLI_BUILD=1; shift ;;
    --sign) SIGN=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\033[34m==>\033[0m %s\n' "$*"; }

CLI_PKG_DIR="$CLI_DIR/dist/openbase-coder-package"

if [ "$SKIP_CLI_BUILD" = "1" ]; then
  [ -f "$CLI_PKG_DIR/console/index.html" ] || {
    echo "--skip-cli-build set but $CLI_PKG_DIR has no console build" >&2; exit 1; }
  step "Reusing standalone CLI package at $CLI_PKG_DIR"
else
  [ -x "$LIVEKIT_BIN" ] || { echo "livekit-server not found at $LIVEKIT_BIN (pass --livekit-bin)" >&2; exit 1; }
  step "Building standalone CLI package (with console) for desktop bundling"
  # Console IS required for the desktop bundle (stage-openbase-coder-cli.mjs
  # validates console/index.html), so do NOT pass --skip-console-build here.
  ( cd "$CLI_DIR" && SETUPTOOLS_SCM_PRETEND_VERSION="0.0.0" \
    uv run python scripts/build_standalone_package.py \
      --version "0.0.0" \
      --channel installtest \
      --livekit-server-bin "$LIVEKIT_BIN" \
      --package-dir "$CLI_PKG_DIR" \
      --force )
fi

export OPENBASE_CODER_DESKTOP_CLI_PACKAGE_DIR="$CLI_PKG_DIR"

step "Staging macOS companion (xcodebuild)"
pnpm --dir "$DESKTOP_DIR" run companion:stage:mac

step "Staging bundled CLI into the app"
pnpm --dir "$DESKTOP_DIR" run cli:stage:mac

step "Generating icons + building renderer"
pnpm --dir "$DESKTOP_DIR" run icons:generate
pnpm --dir "$DESKTOP_DIR" run build

step "Packaging dev app with electron-builder (bundled resources intact)"
EB_ARGS=(--mac --arm64 --publish never -c.extraMetadata.openbaseDevBuild=true)
[ "$SIGN" = "1" ] || EB_ARGS+=(-c.mac.identity=null)
pnpm --dir "$DESKTOP_DIR" exec electron-builder "${EB_ARGS[@]}"

APP="$(find "$DESKTOP_DIR/release/mac-arm64" -maxdepth 1 -name '*.app' | head -1)"
[ -n "$APP" ] || { echo "no .app produced under desktop/release/mac-arm64" >&2; exit 1; }

step "Verifying the built app bundles its resources"
test -d "$APP/Contents/Resources/OpenbaseCoderCLI" || { echo "missing bundled OpenbaseCoderCLI" >&2; exit 1; }
test -d "$APP/Contents/Resources/OpenbaseScreenShareCompanion.app" || echo "WARN: companion app not bundled" >&2

step "Built: $APP"
printf 'APP=%s\n' "$APP"
