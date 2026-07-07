# Cross-Repo Engineering Specs

Durable architecture and contract documents for features spanning multiple
workspace repos. This directory is **committed to a public repository** —
write for a public audience.

## What belongs here

- Cross-repo API contracts and data shapes (endpoint schemas, event
  protocols, config file formats).
- Architecture decisions with their rationale — the "why" a maintainer or
  agent on any machine (including cloud workspaces, which have no access to
  local-only files) needs before changing the design.
- Per-repo work-item breakdowns for the feature.

## What does NOT belong here

- Incident forensics, day-by-day operational notes, personal usernames,
  machine names, or local filesystem paths. Keep planning scratch and
  post-mortems in the workspace-local `.local/` directory (gitignored) —
  and never reference `.local/` files from committed docs.
- Secrets of any kind, ever.
- Anything better owned by a runbook: developer workflow → `DEV_RUNBOOK.md`,
  release/update mechanics → `AUTO_UPDATE.md`, recurring terminology →
  `GLOSSARY.md`, agent conventions → `AGENTS.md`.

## Conventions

- One directory per feature (`specs/<feature>/`), with `README.md` as the
  entry point; additional files (`cloud-api.md`, `work-items.md`, `PLAN.md`)
  as needed.
- Status sections must carry a date (`## Status (updated YYYY-MM-DD)`) and
  be refreshed when reality moves — a stale "blockers" list is worse than
  none. If a spec is fully shipped and stable, say so at the top.
- Specs describe intent at design time; code is the truth afterward. When
  they diverge, update the spec or mark the section historical.

## Current specs

- `onboarding/` — cross-device onboarding rendezvous: cloud device
  registry, CLI/desktop/iOS flows. Shipped.
- `code-sync/` — managed Syncthing sync of selected directories between a
  user's machines, with git-state reconciliation. Implemented; rolling out.
