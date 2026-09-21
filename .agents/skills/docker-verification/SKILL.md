---
name: docker-verification
description: Use when live-verifying uncommitted backend (cli), console, or coder-react changes in an isolated Docker sandbox without touching the shared trunk services — including when a change needs a service restart to take effect, when concurrent agents make the developer install unsafe to exercise, or when seeding realistic thread data for perf work. Not for voice, native apps, or tailnet/peer paths.
---

# Docker Verification (isolated live QA sandbox)

Spin up a **parallel Openbase Coder runtime in a Docker container** to live-verify
working-tree changes without touching the developer's real install. The trunk's
no-restart constraint does not apply inside the container: restart it freely,
which is how restart-gated backend changes get exercised *before* they ship.

This lane sits between tier 1 (unit) and tier 3 (field tests) in
`dev-docs/testing-tiers.md`: heavier than unit tests, far lighter than a Tart VM,
and — unlike both — it verifies **uncommitted working-tree code** against a live
service. It is not a tier of record; it produces confidence, not regression pins.

## What this lane can and cannot test

**Test here:**

- `cli` Django API behavior: endpoints, caches, serialization, pagination,
  auth plumbing — including changes that need a service restart.
- codex-app-server / super-agents integration: rollout serving, thread reads,
  projection-DB behavior, RPC timing (`dispatch_timing` lines in `docker logs`).
- The web console (and `coder-react`) rendered against a live backend:
  network cadence, rendering, auth-fragment flow, pagination UX — drive it with
  the Chrome MCP tools against the container's port.
- Entrypoint/setup/env-file behavior, service wrapper generation, supervision.
- Perf work with realistic data: seed the container with real rollouts (below).

**Do NOT expect to test here:**

- **Voice.** No audio devices in a container, and the voice agent needs an
  audio-provider login plus a real client. The acoustic loop is tier 2/3
  (real phone / field test). Do not start `livekit-*` services here.
- **Native apps** (iOS/Android/desktop). A simulator on the host *can* point
  at the container's API port as its backend, but the app itself runs outside
  Docker; app-side verification is its own build + run.
- **Tailnet / peer / fleet paths**: origin-host discovery, device sync,
  netmesh, code-sync reconcile. The sandbox deliberately never joins a tailnet
  (`OPENBASE_CODER_NETWORK_MODE=local`); peer behavior needs two real devices.
- **Running turns / LLM work.** Read-only by default. Turns need a real cloud
  login; if ever required, use the dedicated field-test account per the
  `field-testing` skill — never the developer's account.
- Push notifications, launchd/systemd specifics, anything macOS-only.

## Isolation rules (parallel agents, worktrees)

Multiple agents and MWW worktrees may run this lane concurrently. Every
identifier must be **unique per sandbox**, and no host port may be chosen by
hand:

- **Slug**: derive one per run, e.g. `qa-<task>` (`qa-slowthreads`). Use it in
  the image tag, container name, and volume name. Never reuse the compose
  defaults (`openbase-coder`, `openbase-data`, port 7999) — the compose file is
  for end users, not QA sandboxes.
- **Ports**: bind ephemeral and loopback-only: `-p 127.0.0.1:0:7999`, then read
  the assigned port with `docker port <name> 7999`. This is collision-free by
  construction no matter how many sandboxes run. Never map 7999:7999 — the
  real local service owns 7999.
- **Worktrees**: build the image from *your* checkout (trunk or MWW) — the
  image copies the cli build context, so the sandbox tests exactly the tree
  you're editing. Two worktrees testing different branches = two slugs, two
  containers, zero interference.
- Never join a tailnet from the sandbox (`OPENBASE_CODER_NETWORK_MODE=local`).
  A sandbox that appears in the user's device fleet is a bug in your run.

## Recipe

All commands from the `cli` repo root of the checkout under test.

### 1. Build from the working tree

```sh
SLUG=qa-mytask
docker build -t openbase-coder:$SLUG .
```

The cli source (including uncommitted changes) is COPY'd into the image.
**Two things are cloned from GitHub instead, and must be injected locally:**

- **Console**: the image builds console/coder-react from remote `develop`.
  To test local frontend changes, build locally (`cd ../console && npx vite build`)
  and bind-mount `console/dist` over the served dir (step 2).
- **super-agents**: cloned from remote. The trunk cli often depends on
  uncommitted super-agents work (real incident: container crash-looped on a
  missing `super_agents.initial_context` another agent hadn't committed).
  After first boot, sync it from the local sibling:

  ```sh
  docker cp ../super-agents/src/super_agents $SLUG:/opt/openbase-coder/workspace/super-agents/src/
  docker exec -u root $SLUG bash -c 'chown -R openbase:openbase /opt/openbase-coder/workspace/super-agents/src/super_agents && find /opt/openbase-coder/workspace/super-agents/src -name __pycache__ -type d -exec rm -rf {} +'
  docker restart $SLUG
  ```

  (docker cp writes as root and drags host `__pycache__` along — the chown +
  pycache purge is required, not optional.)

### 2. Run isolated

```sh
docker run -d --name $SLUG --hostname $SLUG \
  -e OPENBASE_CODER_NETWORK_MODE=local \
  -e "OPENBASE_CODER_SERVICES=django-cli codex-app-server" \
  -p 127.0.0.1:0:7999 \
  -v $SLUG-data:/home/openbase/.openbase \
  -v "$PWD/../console/dist:/opt/openbase-coder/console-dist:ro" \
  openbase-coder:$SLUG
PORT=$(docker port $SLUG 7999 | head -1 | cut -d: -f2)
until curl -fsS http://localhost:$PORT/api/health/ >/dev/null; do sleep 3; done
```

`django-cli codex-app-server` is the full read-path stack. Add services only
when the change under test needs them; never the `livekit-*` pair (voice is
out of scope here).

### 3. Backend flavor — threads need the codex app-server

First-run setup defaults to `openbase-cloud` (cloud-proxied **Claude Code**),
which skips codex-app-server entirely and stores threads elsewhere. For the
thread read path (session manager → super-agents client → codex-app-server →
rollouts), switch to the `codex` backend:

```sh
docker exec $SLUG bash -c '
  sed -i "s/^OPENBASE_CODING_BACKEND=.*/OPENBASE_CODING_BACKEND=codex/" ~/.openbase/.env
  openbase-coder setup --backend codex --non-interactive'
docker restart $SLUG   # entrypoint regenerates the codex-app-server wrapper
```

(The setup rerun ends with a systemd error — expected and harmless; the
container supervises services itself.) No OpenAI/codex login is needed for
read-only serving. If a cloud-flavored backend must boot without login, a
dummy `OPENBASE_CLOUD_CODEX_API_KEY=<anything>` in `~/.openbase/.env`
satisfies the wrapper's token check — reads work, turns obviously don't.

### 4. Seed realistic threads

Copy real rollouts from the host (the developer's own data staying on their
own machine) into the container's codex home, preserving the
`sessions/YYYY/MM/DD/` layout. `~/.codex/sessions` inside the container is
symlinked to `~/.openbase/normal-codex-home/sessions` — either path works:

```sh
tar cf - -C /path/to/staged-rollouts . | \
  docker exec -i $SLUG bash -c 'mkdir -p ~/.codex/sessions && tar xf - -C ~/.codex/sessions'
docker exec $SLUG bash -c 'find ~/.codex/sessions -name "._*" -delete'   # macOS AppleDouble junk
docker restart $SLUG
```

**Threads list but show zero turns until loaded**: the app-server's projection
DB only populates on load/resume. Resume each seeded thread once via RPC:

```sh
docker exec $SLUG bash -c 'cd /opt/openbase-coder/workspace/cli && .venv/bin/python - <<PY
import asyncio, glob, os, re
async def main():
    from super_agents.app_server_client import CodexAppServerClient
    client = CodexAppServerClient()
    for p in glob.glob(os.path.expanduser("~/.codex/sessions/**/*.jsonl"), recursive=True):
        m = re.search(r"rollout-.*T\d\d-\d\d-\d\d-([0-9a-f-]{36})\.jsonl$", p)
        if m:
            try: await client.resume_thread(m.group(1))
            except Exception as e: print("FAILED", m.group(1), repr(e)[:120])
    await client.close()
asyncio.run(main())
PY'
```

### 5. Authenticate

API: mint the local capability token and pass it as a Bearer header:

```sh
TOKEN=$(docker exec $SLUG bash -c 'cd /opt/openbase-coder/workspace/cli && .venv/bin/python -c "from openbase_coder_cli.config.local_api_token import get_local_api_token; print(get_local_api_token())"')
curl -H "Authorization: Bearer $TOKEN" "http://localhost:$PORT/api/threads/?limit=10"
```

Browser console: the token travels in a URL fragment with a **required key**
(a bare `#<token>` bounces to the login page):

```
http://localhost:$PORT/#openbase-local-token=$TOKEN
```

The console will show "Expected service X is not running" banners for every
service you chose not to supervise — expected, ignore them.

### 6. Observe

- Backend timing: `docker logs $SLUG | grep dispatch_timing` —
  `super_agents_thread_read_response` / `_thread_page_response` /
  `app_server_rpc_response` carry `elapsed_ms` per stage.
- Cache behavior: count `method=thread/...` RPC lines against the number of
  HTTP requests issued.
- Frontend: Chrome MCP `read_network_requests` / `read_console_messages`
  against the console tab.

### 7. Tear down

```sh
docker rm -f $SLUG && docker volume rm $SLUG-data
docker rmi openbase-coder:$SLUG   # optional; keep for iterative runs
```

Leave nothing named running when the verification is reported — a lingering
sandbox is state another agent has to reverse-engineer.

## Reporting

State plainly what ran in the sandbox and what remains unverified (voice,
native apps, peer paths, turns). Sandbox verification does not satisfy the
workspace's live-installation completion criterion by itself when the change
has surfaces the sandbox cannot reach — say which criterion is still open.
