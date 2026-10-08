# Shared helpers for the workspace git hooks. Sourced by the hooks, never run
# directly. Identical copies live in every Openbase multi workspace (coder,
# cloud, selfhost); change them together. See README.md in this directory.

HOOK_DIR=$(cd "$(dirname "$0")" && pwd -P)
REPO_TOP=$(git rev-parse --show-toplevel) || exit 1
REPO_TOP=$(cd "$REPO_TOP" && pwd -P)

hook_err() {
  printf '%s\n' "$*" >&2
}

# True (and loud) when the emergency bypass is set. Skips only the gitleaks
# scan; the .reports guard and repo-local boundary guards still run.
skip_secret_scan() {
  [ "${OPENBASE_SKIP_SECRET_HOOKS:-}" = 1 ] || return 1
  hook_err "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  hook_err "!! OPENBASE_SKIP_SECRET_HOOKS=1: the gitleaks secret scan is SKIPPED for"
  hook_err "!! this $1 in $REPO_TOP."
  hook_err "!! Nothing checked it for secrets. Unset the variable for the next one."
  hook_err "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  return 0
}

# Print the gitleaks binary. Hooks also run from GUI apps and services whose
# PATH lacks Homebrew, so check the usual install locations too.
# OPENBASE_GITLEAKS overrides the lookup (tests use it to simulate a missing binary).
find_gitleaks() {
  if [ -n "${OPENBASE_GITLEAKS:-}" ]; then
    _candidates=$OPENBASE_GITLEAKS
  else
    _candidates="$(command -v gitleaks 2>/dev/null) /opt/homebrew/bin/gitleaks /usr/local/bin/gitleaks"
  fi
  for candidate in $_candidates; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  hook_err "$1: BLOCKED - gitleaks is not installed; this workspace's git hooks scan every commit and push for secrets."
  hook_err "  Install it:          brew install gitleaks"
  hook_err "  Emergency bypass:    OPENBASE_SKIP_SECRET_HOOKS=1 git ...   (skips only the secret scan, loudly)"
  return 1
}

# Run gitleaks over git history in this repo. Findings print with values
# redacted. Honours the repo's own .gitleaks.toml and gitleaks:allow comments.
run_gitleaks() {
  _hook=$1
  shift
  "$GITLEAKS" git --no-banner --no-color --redact -v -l warn --exit-code 3 "$@" "$REPO_TOP" >&2
  case $? in
    0) return 0 ;;
    3)
      hook_err "$_hook: BLOCKED - gitleaks found a likely secret (values redacted above)."
      hook_err "  Move the value to an ignored local file or an environment variable."
      hook_err "  False positive: add a narrow allowlist to this repo's .gitleaks.toml,"
      hook_err "  or end the line with a 'gitleaks:allow' comment."
      ;;
    *) hook_err "$_hook: BLOCKED - gitleaks failed to run (see its output above)." ;;
  esac
  return 1
}

# owner/name of the origin remote, from https or ssh URLs.
repo_slug() {
  _url=$(git remote get-url origin 2>/dev/null) || return 1
  _url=${_url%/}
  _url=${_url%.git}
  _name=${_url##*/}
  _owner=${_url%/*}
  _owner=${_owner##*/}
  _owner=${_owner##*:}
  printf '%s/%s\n' "$_owner" "$_name"
}

# Repos listed in private-repos may track .reports/; everything else,
# including repos without an origin, is treated as public.
repo_is_private() {
  _slug=$(repo_slug) || return 1
  grep -v '^#' "$HOOK_DIR/private-repos" 2>/dev/null | grep -qixF -- "$_slug"
}

# shellcheck disable=SC2034 # used by the hooks that source this file
REPORTS_PATHSPEC=".reports */.reports/*"

# The repo's own hook to chain after the workspace checks: <repo>/.githooks/<hook>
# for sub-repos, root/<hook> in this directory for the workspace root repo.
repo_local_hook() {
  _dir="$REPO_TOP/.githooks"
  if [ -d "$_dir" ] && [ "$(cd "$_dir" && pwd -P)" = "$HOOK_DIR" ]; then
    _dir="$HOOK_DIR/root"
  fi
  [ -f "$_dir/$1" ] && [ -x "$_dir/$1" ] && printf '%s\n' "$_dir/$1"
}
