# Syncthing Code Sync Without `.git` — Plan

Goal: bidirectional, near-realtime sync of code (including secrets and
gitignored files) between the MacBook and the Mac mini — and eventually any
user's laptop ⇄ Mac mini or cloud DevSpace — without routing day-to-day file
changes through git commits, and without ever again letting sync corrupt git
state. Productize this in openbase-coder so a user's secondary machine is
always ready to take a voice call.

## 1. The Incident That Motivates This

On 2026-07-05/06, while committing in `cli/`, Syncthing synced `.git/` from
the mini mid-operation (another agent there had just created two commits).
The local checkout's refs/HEAD advanced under a running git process while the
index stayed stale. The resulting commit (`c8f2e79`) silently reverted ~40
files on `main` — deleting two docs pages and the mini's release fixes — and
the docs site briefly deployed from it. Recovery required a forensic restore
commit (`d993865`). The DEV_RUNBOOK "Syncthing flap" hazard is the same class
of failure.

Today's config (`~/Projects/.stignore` + `.stglobalignore`) excludes build
outputs and `node_modules`/venvs but **syncs `.git` fully**. That is the root
problem.

## 2. Why Syncing `.git` Can Never Be Made Safe

- `.git` is a multi-file database (`objects/`, `refs/`, `HEAD`, `index`,
  `packed-refs`) mutated non-atomically. Git's correctness depends on its own
  local locking (`index.lock`, ref locks) and atomic renames on one
  filesystem. Syncthing transfers files independently with no transactional
  grouping, so the receiving side routinely holds refs from one moment and an
  index/HEAD from another.
- With agents active on both machines, there are two concurrent writers to
  the same logical repo. No ignore pattern, timing discipline, or scan
  interval fixes concurrent writers on a non-transactional channel.
- Loose objects are append-only and mostly survive; refs and the index do
  not. `git gc`/repack on one side also races deletes against the other.

Conclusion: `.git` (and any VCS metadata) must be excluded from file sync,
categorically. Git state should move only through git's own transports.

## 3. Requirements

- Bidirectional file sync of working trees: laptop ⇄ mini, laptop ⇄ cloud
  DevSpace.
- Secrets (`.env`, keys) and gitignored-but-needed files sync too — git
  push/pull alone cannot do this, which is why sync exists at all.
- No obligation to commit to move code between machines.
- Git remains fully usable on **both** sides (agents commit anywhere).
- Conflicts are surfaced in the product (console + iOS), not silently
  resolved.
- Machine-specific state never syncs (device identity, local DBs, launchd
  wrappers, logs).

## 4. Core Design: Split the Two Kinds of State

Clarifying the "no git" requirement up front: **moving files never involves
git** — code, secrets, and gitignored files sync on save with no commit
required. Git appears in exactly one place: synchronizing git's *own* state
(branch pointers, history) between the two repos, because both machines run
agents that commit and their repos must eventually agree. That data cannot
travel as raw files (that is the incident), and the only transactional,
lock-aware channel for it is git's own transport — driven automatically by a
service, never by a human or agent "syncing via commits". A design with zero
git anywhere would require one machine to have no repo at all, which
contradicts the requirement that agents can commit on either machine.

**Layer 1 — file sync (Syncthing): working trees only, never `.git`.**
Each machine keeps its own private `.git`. Files flow continuously.

**Layer 2 — git-state reconciliation (git-native, automated).**
Each repo gets the peer as a git remote over Tailscale SSH (no GitHub
round-trip needed). A small reconciler service keeps branch pointers in
step with the already-synced file content:

- When machine B's working tree content for branch X already equals the tree
  of A's new commit on X (because Syncthing delivered the files), B's
  reconciler fetches from the peer and moves its local branch pointer to the
  same commit (`git fetch peer && git update-ref` / `reset --soft` when
  `git diff` against the fetched commit is empty). Status goes clean; no
  content moves twice; no user-visible commits were required to sync files.
- When trees don't match (both sides edited), do nothing automatic: report a
  **repo sync conflict** with both fingerprints, mirroring the existing
  thread-sync-conflicts UX ("Keep Local" / "Use Remote" / open diff).
- Uncommitted work needs no reconciliation at all — it just syncs as files
  and shows as dirty on both sides, which is the desired semantics.

This preserves the "no commits needed" property for file movement, while
commits — when they do happen — propagate safely through git itself.

**Layer 3 — write coordination (advisory, not locking).**
Don't build distributed locks. Instead make concurrent editing visible and
rare: the product already knows which machine has active agent
sessions/voice routes. Surface "agents are active on <machine> in <repo>"
in the console/iOS before dispatching work to the other machine, and prefer
dispatching to the machine that already has the active session. Syncthing's
`*.sync-conflict-*` copies remain the last-resort safety net for true
simultaneous edits of one file; the reconciler should list them for cleanup
instead of leaving them to be found by grep.

## 5. Immediate Fix for MacBook ⇄ Mini (do this now)

1. Quiesce: finish/park agent work on both machines; ensure both sides'
   repos are at pushed, clean states (or accept that dirty diffs will simply
   coexist as dirty diffs).
2. Add to `~/Projects/.stglobalignore` on **both** machines (patterns are
   folder-relative; cover nested subrepos and linked worktrees):

   ```text
   // VCS metadata must never sync (torn git state; see 2026-07-05 incident)
   (?d).git
   (?d)**/.git
   (?d)**/.jj
   (?d)**/.hg
   ```

   Note: `**/.git` also matches git-worktree `.git` *files*; those point at
   machine-local paths and must not sync either.
3. Let both sides rescan; Syncthing will stop tracking `.git` but leaves the
   existing local copies in place — each machine now owns its `.git`
   privately. Verify with `syncthing cli` or the GUI that `.git` paths show
   as ignored.
4. From now on, move refs between the machines via normal `git fetch`/`pull`
   of `origin`, or add direct peer remotes over Tailscale:

   ```bash
   git remote add mini ssh://gabemontague@<mini-tailscale-dns>/Users/gabemontague/Projects/<...>/cli
   ```

5. Interim, until the reconciler exists: after committing on one machine,
   the other machine will show the same changes as a dirty tree; either
   ignore it (it's truthful) or `git fetch && git reset <peer>/<branch>`
   when the diff is empty.

## 6. Productizing in openbase-coder

New subsystem, working name **`code-sync`** (CLI: `openbase-coder sync ...`).

**File-sync engine.** Bundle/manage Syncthing the way LiveKit server is
bundled today (standalone package already ships binaries; add
`syncthing` + a managed `code-sync` launchd/systemd service). openbase-coder
owns the Syncthing config: device IDs exchanged through Openbase Cloud
device registration (the pairing flow already knows both devices), transport
pinned to Tailscale addresses, global discovery/relays disabled.

**Managed ignores.** Generate the folder `.stignore` from a template the
user never hand-edits:

- always: VCS metadata patterns from §5, `node_modules`, venvs, build dirs
  (reuse the repo's registered build-output globs), caches;
- never ignored (explicitly documented): `.env` and other gitignored
  secrets inside project dirs — syncing them is a feature;
- per-project overrides editable in the console.

**Scope.** User-selected directories, chosen in a new console **Sync** page
(see Surfaces): the user picks directories under their home; each synced
folder's identity is its **home-relative path**, and every device mounts it
at `$HOME/<relpath>` regardless of what the home directory is named
(Syncthing natively supports per-device folder paths for a shared folder ID;
the service generates each device's config with its own expansion). Only
paths under `~` are eligible — the picker validates this. Folder IDs are
deterministic (hash of the relpath) so devices agree without negotiation.
The Projects page's registered roots seed the default suggestions.
Optionally a curated slice of `~/.openbase` (skills, instructions,
dispatcher config) — but never `installation.json`, `auth.json`/device
identity, `db.sqlite3`, `logs/`, `launchd/`, `packages/`.

**Eligibility gate.** The feature only arms when the cloud device registry
shows **two or more non-phone devices** (desktop or headless workspace) with
Tailscale identities for the account. Phones never participate as sync
peers (no viable background Syncthing on iOS); they only *view* sync state
and conflicts. The console page shows a "add a second machine" nudge when
only one eligible device exists.

**Reconciler service.** Per §4 layer 2: peer remotes over Tailscale SSH (or
git's smart HTTP served by the local CLI API with token auth, which avoids
SSH setup entirely — likely the better product choice), auto-fast-forward
when trees already match, conflict records exposed at
`/api/repo-sync/conflicts/`.

**Surfaces** (following the existing product pattern):

- Console/desktop: a "Machines" or extended Devices page showing sync
  health per project, last reconcile, and a Repo Sync conflicts page
  (sibling of Thread Sync conflicts).
- iOS: conflicts appear alongside thread sync conflicts in the Sync tab;
  push notification on new conflicts (route exists already).
- `openbase-coder doctor`: checks that no synced folder includes `.git`
  (guards against regression on user-managed Syncthing setups).
- Docs: new page under Using the Apps; glossary entries.

**Cloud DevSpace.** Identical mechanics — the DevSpace image already has
Tailscale; add syncthing + code-sync service to the image. Trust model: the
DevSpace is a trusted device (it must run the code), so no
receive-encrypted mode; isolation comes from tailnet-only transport.
Sandbox teardown/re-launch re-pairs via the cloud device registry.

## 7. Edge Cases and Policies

- **Multi workspaces**: every subrepo has its own `.git`; the recursive
  patterns cover them. `multi.json` itself syncs (it's just a file).
- **Symlinked skills**: Syncthing syncs symlinks as symlinks on
  macOS/Linux — fine for the workspace-relative links (`.claude/skills/...`
  → `.agents/skills/...`), but absolute-path links won't resolve on the
  peer; the skills auto-link service should regenerate machine-local links
  rather than relying on synced ones.
- **Mid-operation git states** (rebase/merge in progress) live entirely in
  `.git`, so they stay machine-local by design — correct behavior.
- **`index.lock` era ends**: with `.git` unsynced, git's own locking is
  sufficient again on each machine.
- **Build flap hazard** remains for non-git files: keep build outputs
  stignored (already done) and have release builds assert their inputs are
  in sync-idle state (`syncthing cli` completion check) before packaging.
- **Databases/large binaries** inside projects: default-ignore common
  patterns (`*.sqlite3`, model weights dirs) with per-project opt-in.

## 8. Alternatives Considered (and why not)

- **Keep syncing `.git`, add pause/lock discipline** (pause folder during
  git ops via Syncthing REST): rejected — agents run arbitrary git
  constantly on both sides; any missed pause reproduces the incident.
- **Git-only flow (auto-commit shadow branches, bundles)**: safe but
  violates the core requirement — secrets/gitignored files don't travel,
  and it forces commit-shaped noise.
- **Mutagen/Unison instead of Syncthing**: strong two-way sync semantics
  and VCS-dir defaults, but session-oriented (laptop-initiated), weaker fit
  for an always-on mesh of 2–3 devices; Syncthing is already deployed and
  embeddable. Revisit for laptop⇄cloud if Syncthing-in-DevSpace proves
  heavy.
- **Jujutsu (jj) colocated repos**: its op-log/working-copy-as-commit model
  tolerates concurrency far better, but requiring a VCS switch is not a
  product option; worth watching.

## 9. Rollout

1. **Now**: apply §5 on both machines; add the `doctor` check; note the
   policy in DEV_RUNBOOK (replaces the "suspect a sync flap" hazard with
   "`.git` is never synced").
2. **Phase 1**: `code-sync` service managing Syncthing + generated ignores
   for registered projects (laptop ⇄ mini), no reconciler — dirty-tree
   semantics only.
3. **Phase 2**: reconciler (auto-ff + conflict records) + console/iOS
   conflict UI + notifications.
4. **Phase 3**: DevSpace image integration; onboarding step ("Keep a second
   machine in sync") in desktop app + docs.


---

## 10. Review & Amendments (2026-07-06, second opinion)

Verdict: **the architecture is right and should proceed as written** — the
categorical `.git` exclusion, the two-layer split (files via Syncthing, git
state via git's own transport), and advisory-not-locking coordination are
the same conclusions reached independently from the 2026-07-04 incidents,
and the reconciler design here (peer remotes + auto-ff only when trees
already match, conflicts surfaced product-side) is stronger than a
bundle-based exchange: bundles fit offline couriering, while these peers are
always-on and already share a tailnet. The smart-HTTP-served-by-the-CLI-API
option should be the default (no SSH provisioning; token auth exists).

Amendments to fold in:

1. **Layer 3.5 — active-device lease (receive-only folders).** §4's advisory
   layer prevents *planned* concurrent work but not the echo-race class: the
   2026-07-04 `package.json` deletion was a **working-tree** file flapping
   mid-commit, and excluding `.git` does not fix that class. Syncthing
   folders support per-device **receive-only** mode; the code-sync service
   should hold a simple lease — the device with recent user/agent activity
   is send-receive, all other peers are flipped receive-only via the
   Syncthing REST API, and the lease follows activity (voice route, agent
   session, console focus). This makes stale-state echo *structurally
   impossible* instead of merely visible, and it is cheap: one REST PATCH
   per folder on lease change. Manual override in the console for split
   work across machines.
2. **Versioning as the undo net.** Synced work is *uncommitted* by design —
   it has no reflog. Enable Syncthing versioning on every managed folder so
   a bad deletion/overwrite propagated by sync is recoverable without git.
   Cost note: versions are created **only when an incoming sync replaces or
   deletes a file** — local edits never version — so this is not N× the
   folder; it is old copies of remotely-churned files only, and the
   storage-heavy patterns (node_modules, builds, weights, DBs) are excluded
   from sync entirely. Use **staggered** versioning with a max age (~30
   days) rather than a fixed keep-count, so history thins automatically and
   the bound is time, not copies. Point each folder's versions path at a
   central `~/.openbase/sync-versions/<folder-id>/` instead of the default
   in-folder `.stversions/` — keeps repos clean (no untracked junk in git
   status) and gives doctor/console one place to report versioning disk
   usage with a purge control. Surface "restore previous version" next to
   the conflict UI. This converts the scariest failure mode (sync
   propagates a deletion of never-committed work) from data loss into an
   undo.
3. **Case-sensitivity boundary.** macOS (APFS, case-insensitive) ⇄ cloud
   DevSpace (ext4, case-sensitive) can collide two files differing only by
   case. Enable Syncthing's `caseSensitiveFS` handling on managed folders
   and have `doctor` flag repos containing case-colliding paths before
   first sync to a Linux peer.
4. **Linux watcher limits.** The DevSpace image needs
   `fs.inotify.max_user_watches` raised (large workspaces exhaust the
   default and Syncthing silently degrades to periodic scans).
5. **Reconciler safety detail.** Auto-ff must require both (a) empty
   `git diff` between the fetched commit's tree and the local working tree
   (plan already states) and (b) the local branch head being an **ancestor**
   of the fetched commit — never move a diverged local branch, even with a
   matching tree, and never touch a repo with a merge/rebase in progress
   (`.git/MERGE_HEAD`/`rebase-merge` present).
6. **Config is product state.** Selected directories, per-folder overrides,
   and lease policy live in a schema-versioned `sync-config.json` beside
   `dispatcher-config.json` (same refuse-newer semantics), exposed at
   `/api/sync/settings/` for the console page.
7. **Interim guard now shipped.** §5's stglobalignore patterns were applied
   on 2026-07-06 (the ignore file itself syncs, so the mini inherits it);
   the `doctor` check in §6 remains the durable guard once code-sync owns
   config generation.
