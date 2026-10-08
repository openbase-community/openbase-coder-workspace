# Workspace git hooks

Every repo in this multi workspace (the root and each sub-repo, in the trunk, in every MWW and in fresh clones) runs the hooks in this directory. `multi.json` declares it (`"hooks": {"path": ".githooks"}`) and multi installs it: `multi sync`, `multi init` and `multi worktree add` set `core.hooksPath` in every repo. Never set `core.hooksPath` or edit `.git/hooks` in a sub-repo by hand.

```bash
multi hooks status    # every repo should say "installed"; exits 1 otherwise
multi hooks install   # repair
```

## What runs

- `pre-commit`: `gitleaks git --staged` over the staged changes, then the public-repo `.reports/` guard (refuses while any `.reports/` path is in the index), then the repo's own `pre-commit` if it has one.
- `pre-push`: for each pushed ref, `gitleaks` over the commits the remote does not have yet and the same `.reports/` guard over those commits, then the repo's own `pre-push` with the same input.

Findings print with the secret value redacted. A scan of a typical staged change or push takes well under a second.

## Repo-local hooks

A sub-repo can keep its own hooks in `<repo>/.githooks/` (for example `desktop/.githooks/pre-push`, which standalone clones install through their `prepare` script). The workspace hooks run them after their own checks. The workspace root repo's own hooks live in `root/` here, because this directory is the root repo's `.githooks/`.

## Configuration

- `private-repos` lists the private repos (origin `owner/name`). The `.reports/` guard skips them; every other repo counts as public.
- False positives: add a narrow allowlist to that repo's `.gitleaks.toml` (gitleaks reads it from the repo root), or end the line with a `gitleaks:allow` comment. Do not weaken the rules globally.

## Missing gitleaks and the emergency bypass

The hooks refuse to commit or push without gitleaks: `brew install gitleaks`. In an emergency, `OPENBASE_SKIP_SECRET_HOOKS=1 git commit ...` (or `git push`) skips only the secret scan and prints a loud warning; the `.reports/` and boundary guards still run.

The same hook scripts live in every Openbase multi workspace; only `private-repos` differs. Change them together. Tests: `node --test scripts/githooks.test.mjs`.
