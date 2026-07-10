# Staging TODOs

## DONE — Bad packaging: CI-machine shebangs in released console scripts

**Fixed on staging: cli `4fc6730`.**

Diagnosis (from a broken 0.10.0 install): every console script in the
released macOS arm64 package (`super-agents-mcp`, `super-agents-backend`,
`openbase-coder`, `mcp`, `gunicorn`, ~40 scripts total) shipped with an
absolute shebang pointing at the CI build machine's Python
(`/Users/runner/work/_temp/.../python/bin/python`). That path never exists on
user machines, so the kernel can't find an interpreter and every script dies
instantly — Claude Code reported the MCP as "Failed to connect."

Fix in `cli/scripts/build_standalone_package.py`:

- `rewrite_bin_shebangs()` runs after `pip install` and rewrites each
  Python-shebanged script in `python/bin` to a location-independent
  `#!/bin/sh` trampoline (`'''exec' "$(dirname -- "$0")/python3.12" "$0" "$@"`).
  Upstream scripts that already ship a relocatable `realpath`-style
  trampoline (e.g. `2to3-3.12`) are left untouched.
- `validate_package` gained a tripwire that fails the build if any
  `python/bin` shebang still names an absolute interpreter or a
  non-relocatable trampoline — this would have caught 0.10.0.
- `validate_package` also functionally runs one rewritten script
  (`python/bin/pip --version`).

Verified by APFS-cloning the local reference bundle to `/tmp` (simulating an
install at a different path), rewriting, and running `pip`, `django-admin`,
and `2to3-3.12` from there; also verified the tripwire rejects the original
broken bundle.

## DONE — Desktop staged CLI bundle not self-contained

**Fixed on staging: desktop `531eb51`.**

`desktop/scripts/stage-openbase-coder-cli.mjs` copied the package with
`cpSync(..., { dereference: true })`. Node's `cpSync` leaves nested symlinks
as symlinks but rewrites their relative targets to absolute paths into the
source tree, so `bundled/OpenbaseCoderCLI/python/bin/python` pointed at the
workspace's `cli/dist` checkout. Now copies with `verbatimSymlinks: true`
(relative links preserved as-is) and fails staging if any symlink in the
staged bundle resolves outside it. Verified by re-staging from the local
reference bundle: no absolute symlinks remain and `bin/openbase-coder
--version` runs.

---

## Future — to do or consider later, not now

- **Ship the fix in a release.** The shebang fix only helps users once a
  0.10.1+ standalone package is built and published; every 0.10.0 macOS
  install is broken until its owner upgrades. Fold into the next `deploy`.
- **Remediate the affected local 0.10.0 install** (the one diagnosed at the
  top of this doc) by upgrading it once the fixed release ships; until then
  its `python/bin` scripts still have build-machine shebangs.
- **Merge coordination:** cli `dev` adds `prune_runtime()` to
  `scripts/build_standalone_package.py` (dev commit `9d80e22`) — expect a
  (small) conflict with `rewrite_bin_shebangs()` when dev and staging meet.
- **Consider the `realpath` trampoline form** for rewritten scripts and the
  `bin/openbase-coder` launcher: `$(dirname -- "$(realpath -- "$0")")`
  survives invocation through a symlink from another directory, but
  `/bin/realpath` requires macOS 13+ — check the minimum supported macOS
  before switching.
- **Consider a CI relocation test:** `validate_package` runs in the build
  directory, where absolute build paths still resolve, so only the static
  shebang tripwire (not the functional checks) proves relocatability. A CI
  step that copies the package to a fresh temp dir and runs
  `bin/openbase-coder --version` plus one `python/bin` script from there
  would prove it end-to-end.
