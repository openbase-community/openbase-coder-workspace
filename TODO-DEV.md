# TODO

## Shrink the macOS desktop app bundle (~1.5 GB fully built)

ON DEV BRANCH/WORKTREE

**DONE** (cli `dev` commit `9d80e22`): `prune_runtime` in
`build_standalone_package.py` removes `__pycache__`, site-packages test dirs,
the bundled Claude CLI, and dead Tk/Tcl after pip install. Verified against a
copy of the current 974 MB bundle: frees 382 MB; imports, the CLI entrypoint,
and the SDK fallback to the external `claude` all confirmed working from the
pruned tree. Item 3 needed no change — setup already installs only the
selected backend via `ensure_backend_binary`.

### Problem

The full macOS build stages the standalone CLI package into the Electron app via
`extraResources` (`desktop/package.json`, `desktop/scripts/stage-openbase-coder-cli.mjs`).
That package (`cli/dist/openbase-coder-package`, ~1.0 GB) dominates the app size;
Electron itself accounts for only ~300 MB. Inside the package, the two biggest
avoidable contributors are:

1. **A duplicate Claude binary (~226 MB).** `cli/pyproject.toml` depends on
   `super-agents[claude]`, which pulls in `claude-agent-sdk`, whose wheel ships a
   full Claude Code CLI at `claude_agent_sdk/_bundled/claude`. Every user downloads
   it — including Codex-only users — even though setup _also_ installs the external
   `claude` CLI via Anthropic's installer when the Claude backend is selected
   (`cli/openbase_coder_cli/backend_binaries.py`). Claude effectively ships twice,
   and `backend_binaries.py` explicitly states neither backend CLI should ship
   inside the standalone runtime.

2. **Stale build artifacts (~180 MB).** `build_standalone_package.py` excludes
   `__pycache__` when copying the base Python, but the subsequent `pip install`
   repopulates it (~161 MB under `site-packages`), and installed packages carry
   ~21 MB of `tests`/`test` directories.

### Proposed fix

1. **Prune after `pip install`** in `cli/scripts/build_standalone_package.py`:
   delete `__pycache__`, `tests`/`test` dirs, and (if unused) `idlelib`,
   `turtledemo`, and Tk/Tcl. Bytecode regenerates lazily on first run in the
   installed (writable) location. ~180 MB, near-zero risk.

2. **Delete `claude_agent_sdk/_bundled/claude` in the same prune step.** The SDK's
   `_find_cli()` falls back to `shutil.which("claude")` and standard install
   locations, so Claude turns keep working against the externally installed CLI —
   the path setup already uses. This requires **no change** to `claude_auth.py`
   (it already resolves via PATH) and makes Claude symmetric with Codex: installed
   on demand when the backend is selected. ~226 MB.

   _Rejected alternative:_ keeping the bundled binary and routing
   `claude auth status`/`login` through it. That removes the external install but
   saves zero app size and forces the 226 MB download on every user.

   _Risk to watch:_ version skew between the SDK (which pins a matched bundled CLI
   version) and a PATH-installed `claude`. The stdio protocol is stable across CLI
   versions and the installer fetches current releases, so this is low.

3. Optionally, stop eagerly installing `claude` during setup and defer to backend
   selection via `ensure_backend_binary` (already modeled).

### Explicitly deferred (product decisions, not quick wins)

- Removing the bundled `uv` binary (~49 MB): the CLI shells out to `uv` at
  runtime, so it may be required on machines without it. Verify before touching.
- Making local voice/ML deps (`onnxruntime`, `transformers`, LiveKit noise
  cancellation, etc.) optional or first-run downloadable.
- Not bundling the CLI seed in the app at all (first-launch download). Affects
  offline first-run and `AUTO_UPDATE.md` seed semantics — needs a spec.

Note: the DMG is compressed, so ~400 MB of uncompressed savings translates to
roughly 150–250 MB off the actual download. Keep `AUTO_UPDATE.md` accurate if
staging behavior changes.

## Settings item: Openbase git provenance hooks

ON DEV BRANCH/WORKTREE

**DONE** (cli `dev` `01e36e1`, coder-react `dev` `11e183e`, both rebased onto
the final staging and pushed): `provenance_hooks.py` installs the shared
dependency-free inject-session-id SessionStart hook into both managed backend
homes — Claude settings hook plus Codex `hooks.json` with a `[hooks.state]`
trust entry whose `trusted_hash` replicates Codex's normalized trust identity
(verified byte-for-byte against a hook Codex itself trusted, and covered by a
golden-vector test). `GET/POST /api/settings/openbase-hooks/` serves the new
console settings section with its Install button. The duplicated TOML table
helpers were consolidated into `toml_text.py`. 8 new tests; related suites
pass; the 12 pre-existing dev failures (thread-sync/projects) reproduce
identically without these changes.

The console settings should show whether the Openbase hooks are installed,
with an install button when they are not. The Openbase hooks are the git
provenance hooks from the "Common AI MCPs/Skills" Notion doc: a SessionStart
hook (`inject-session-id`) that reads the `session_id` from the hook's stdin
JSON and injects it back into the conversation as context, so agents can
stamp commits with an `Agent-Thread-Id` trailer tying each commit to the
exact agent session that produced it. Install covers the coding-backend homes
Openbase Coder manages (Codex hook manifest + `[hooks.state]` trust entry
with the reviewed `trusted_hash`; Claude Code settings hook), and the status
check verifies the registered hooks still match the shipped script content.

## Voice input via `<voice>` tags + responding-to-voice-tag skill

ON DEV BRANCH/WORKTREE — do after the settings/hooks item above.

**DONE** (cli `45d1ce0`, skills `8973f44`, coder-react `b925d24`, workspace
root `dc74a93`, all on dev and pushed): speech is wrapped via the new
`voice_tags` module at the single point transcripts become turn prompts; the
new `responding-to-voice-tag` skill (bundled, symlinked into both agent
homes) carries the voice etiquette plus exit-to-dispatch mechanics; the
direct-LiveKit instructions loader, env overrides, builtin text,
VOICE_INSTRUCTIONS.md rendering/file, the `direct_livekit` AGENTS.md editor
document (CLI + console), and voice-transfer instruction injection are all
removed. Dispatcher role instructions unchanged. cli suite: 777 passed
(pre-existing thread-sync/projects failures excluded). Note: the workspace
root dev branch was squash-rebased onto staging (old history at
`dev-pre-rebase-backup`); its lockfiles kept staging versions pending regen
on a machine with full checkouts.

Today the LiveKit session injects context telling the agent whether it is
being talked to over voice, via backend-specific shims (Codex / Claude Code
voice-instructions file injection). Replace that with a cross-platform
convention: when the user speaks to an agent over voice, wrap what they say
in `<voice>` tags, and give agents (dispatcher and Super Agents alike) a
`responding-to-voice-tag` skill that teaches them how to respond to
voice-tagged input. The skill effectively replaces the voice instructions
file, and the per-backend injection shims go away.

## Reduce Electron app size

Add by Gabe. Still expected on dev branch and still expecting you to commit and push as you go:

Do the plan in /tmp/openbase_electron_size_rmot.md for reducing electron app size. Gabe left comments about which are in scope.

**DONE** (cli `dev` `d73646d`) for the in-scope items:
- Item 1 (merge pruning + staging shebang fix) happened during the dev
  rebase: the builder now runs `rewrite_bin_shebangs` then `prune_runtime`.
- Item 2: `uv` removed from default deps (~49 MB) with a pyproject note;
  `prune_runtime` also drops a stray `bin/uv` as belt-and-braces. Verified
  no code imports it and all call sites resolve user/system uv with
  `python -m pip` fallback.
- Item 3: `livekit-plugins-noise-cancellation` removed (~74 MB) with the
  requested loud note in pyproject about re-adding the dependency FIRST to
  avoid prod-only failures.
- Item 5: new `strip_native_binaries` pass (`strip -x`, best-effort, before
  ad-hoc codesign); validated on real onnxruntime binaries (63 → 39 MB).
- Item 4: analysis written back into the RMOT — the turn-detector model
  already downloads at runtime; the bundle cost is the transformers stack
  (~125 MB), recommended path is on-demand install at setup like the
  local-audio deps.
- Caveat: a fresh end-to-end package build is currently impossible from dev
  because `open-approvals` is not yet on PyPI (known carve-out release
  blocker), so validation was per-component against the reference bundle.

## FUTURE TODO (not now)

Follow-ups suggested by the prune work, beyond the deferred items above:

- **Exercise a fresh end-to-end build with the prune.** The prune was
  validated against a copy of an existing 974 MB bundle, not a from-scratch
  `build_standalone_package.py` run through the release pipeline and an
  install test. Confirm the first CI build on this branch and one
  `live-installation-test` pass.
- **Add a package size budget to the build.** Print per-top-level-directory
  sizes and fail (or loudly warn) when the package exceeds a threshold
  (e.g. 650 MB uncompressed), so the next accidental 226 MB passenger gets
  caught at build time instead of by users' download meters.
- **Guard Claude CLI version skew at setup.** With the bundled SDK CLI gone,
  the SDK runs against whatever external `claude` is installed. If the SDK
  exposes a minimum supported CLI version, check it in
  `ensure_backend_binary`/setup and offer the official installer's update
  path when the installed binary is too old.
- **Skip writing bytecode instead of deleting it.** Passing `--no-compile` to
  the runtime `pip install` steps would keep `__pycache__` from being written
  at all; `prune_runtime` then becomes belt-and-braces rather than the only
  line of defense (and builds get slightly faster).
