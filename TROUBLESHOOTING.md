# Troubleshooting

This guide is for **agents** debugging a running Openbase Coder install from
this workspace: symptoms, log locations, bounded log checks, and fixes.
User-facing troubleshooting lives in the product docs at
`cli/docs/troubleshooting.md` (https://docs.openbase.cloud/troubleshooting/);
put anything an end user should read there, not here.

When reading logs under `~/.openbase/logs`, always use bounded reads
(`tail -n ...` piped to a filter) — the files are huge.

## iOS Call Stuck On "Connecting..."

The iOS app got a LiveKit room token and opened signaling, but WebRTC media
never connected.

The **user-facing symptom, expected Tailscale Serve routes, the LiveKit
listener (`lsof`) check, and the regenerate/restart fix are canonical in
`cli/docs/troubleshooting.md`** ("iPhone Stays On Connecting" and "iPhone
LiveKit Call Times Out Over Tailscale") — confirm and apply those first. This
section adds only the agent-side root cause and log signatures that confirm
the diagnosis; don't restate the routes/fix here.

Root cause (interface bug): `livekit-server` advertises the Tailscale node IP
in ICE candidates (e.g. `100.64.0.10:7882`) while `lsof` shows UDP bound only
on loopback, because its RTC `interfaces.includes` still lists a stale
interface (e.g. `en7`) instead of the active Tailscale `utunN`. After
`services regenerate && services install`, the running command
(`ps -ax -o pid,command | rg '[l]ivekit-server'`) should list `utunN` and
`lsof -nP -iUDP:7882` should show the Tailscale IP, not just `127.0.0.1`.

Distinguishing log signatures — media ICE failed but dispatch was fine:

- LiveKit server: phone signals in, then `removing participant without
  connection` / `reason: SIGNAL_SOURCE_CLOSE` / `dtls timeout: ... context
  deadline exceeded`.
- LiveKit agent (clean): `received job request` → `Connected to LiveKit room`
  → `AgentSession started`.
- Django (clean): `POST /api/livekit-room-token/ ... 200 OK`.

### Bounded Log Checks

Do not dump the full files in `~/.openbase/logs`; they can be large. Use bounded reads:

```sh
tail -n 360 ~/.openbase/logs/django-cli.log | rg -i 'livekit-room-token|error|warning'
tail -n 360 ~/.openbase/logs/livekit-agent.log | rg -i 'received job request|Connected to LiveKit room|AgentSession started|error|failed'
tail -n 360 ~/.openbase/logs/livekit-server.log | rg -i 'participant active|without connection|SIGNAL_SOURCE_CLOSE|dtls timeout|ice connection state change'
```

Useful connectivity checks:

```sh
tailscale serve status --json   # expect TCP :18080 HTTP + :7880 TCPForward -> 127.0.0.1:7880
tailscale status
tailscale ip -4
dig +short your-mac.tailnet-name.ts.net
nc -vz -w 2 100.64.0.10 7881
```

## iOS Call Stuck On "Waiting For Agent" (Dead Process Pool After Mac Sleep)

In this failure mode networking is completely healthy — Tailscale, LiveKit
server bindings, dispatch, and the iPhone's WebRTC connection all succeed —
but the agent worker's pool of pre-warmed job processes is full of dead
children left over from the Mac sleeping.

### Symptoms Seen

The agent log shows the sleep/wake kill burst (often overnight), one line
per pooled process, all within the same second:

```text
process is unresponsive, killing process
```

Then every subsequent call fails instantly. Each `received job request` is
followed within ~1ms by:

```text
failed to launch job on process, retrying with a new process (attempt 1)
failed to launch job on process, retrying with a new process (attempt 2)
failed to launch job on process after 3 attempts
job_request_fnc failed ... BrokenPipeError ... DuplexClosed
```

The three launch attempts land inside the same millisecond, so every retry
draws the *next* dead process from the pool — replacement processes take
~1 second to warm up and are never candidates in time. Each failed call
consumes 3 dead pool entries and triggers 3 fresh spawns
(`initializing process` / `process initialized` lines right after the
failure), so after enough failed calls the dead backlog drains and a call
"randomly" succeeds. Do not interpret an eventual success as recovery —
bounce the agent instead.

The LiveKit server log stays clean for the agent side: the iPhone reaches
`participant active` on every attempt, the job is `assigned job to worker`,
and no agent participant ever joins. (The iPhone's later
`dtls timeout` / `error reading data channel` warnings are just the phone
abandoning the call.)

### Checks

```sh
tail -n 400 ~/.openbase/logs/livekit-agent.log | rg -i 'unresponsive|failed to launch job|received job request|Connected to LiveKit room|BrokenPipe|DuplexClosed'
```

Diagnosis is confirmed by the `unresponsive, killing process` burst followed
by `failed to launch job ... after 3 attempts` with `BrokenPipeError`. If
you instead see the agent connect and then time out with
`wait_pc_connection`, see the next section.

### Fix

Restart the agent to reset the process pool:

```sh
./.venv/bin/openbase-coder services stop livekit-agent
./.venv/bin/openbase-coder services start livekit-agent
./.venv/bin/openbase-coder services status
```

The next call should show `received job request` →
`Connected to LiveKit room` → `dispatch_timing stage=agent_session_start_complete`.

Root cause note: after the sleep watchdog kills unresponsive children, the
livekit-agents proc pool still hands the dead executors to `launch_job`, and
the 3-attempt retry loop is instantaneous so it cannot outlast the corpses.
Observed on the 0.26.0 standalone runtime (livekit-agents Python SDK).

## iOS Call Stuck On "Waiting For Agent" (Agent WebRTC Timeout)

This is different from being stuck on "connecting...". In this state, the iPhone may have reached the LiveKit room and dispatched the agent job, but the Python LiveKit agent cannot complete its own WebRTC connection back into the room.

### Symptoms Seen

The LiveKit agent log shows a job was dispatched:

```text
received job request
```

But it never reaches:

```text
Connected to LiveKit room
dispatch_timing stage=agent_session_start_complete
```

Instead it exits after:

```text
failed to connect: Connection("wait_pc_connection timed out")
process exiting
```

The LiveKit server log can still show the iPhone participant joining and the job being assigned, so dispatch is not the broken part.

### Checks

Use bounded reads only:

```sh
tail -n 160 ~/.openbase/logs/livekit-agent.log | rg -i 'registered worker|received job request|Connected to LiveKit room|agent_session_start_complete|wait_pc_connection|process exiting|failed|error'
tail -n 160 ~/.openbase/logs/livekit-server.log | rg -i 'assigned job|participant active|agent-|ice connection state change|dtls timeout|failed|error'
```

Confirm Tailscale Serve still points at the correct local services:

```sh
tailscale serve status --json
```

Expected shape:

```text
18080 -> http://127.0.0.1:7999
7880  -> 127.0.0.1:7880
```

Confirm LiveKit is still bound to the Tailscale IP:

```sh
lsof -nP -iTCP:7880 -iTCP:7881 -iUDP:7882
```

Expected:

```text
UDP 127.0.0.1:7882
UDP 100.64.0.10:7882
UDP [TAILSCALE_IPV6]:7882
TCP *:7881 (LISTEN)
TCP 127.0.0.1:7880 (LISTEN)
```

### Fix

**This is now self-healing.** The `sync-workers` service runs a
`livekit_pool_watchdog` job (in
`cli/openbase_coder_cli/services/livekit_pool_watchdog.py`) that tails
`livekit-agent.log`, and on a newly-written `wait_pc_connection timed out`
bounces `livekit-agent` automatically — escalating to bouncing
`livekit-server` + `livekit-agent` if the signature recurs within 15 minutes.
It also proactively recycles the idle agent every ~45 minutes so the stale
pre-warmed pool never forms in the first place. Both paths are gated by an
active-call guard (never bounces mid-call; a signature that fires during a
live call is deferred and bounced once the call ends) and a rolling rate
limit (max 3 bounces / 30 min).

Look for its activity in the sync-workers log:

```sh
tail -n 200 ~/.openbase/logs/sync-workers.log | rg -i 'livekit_pool_watchdog'
```

You should see `bounce reason=stale_pool_signature`,
`reason=stale_pool_signature_escalated`, or `reason=idle_recycle`; `deferred`
(active call) and `rate_limited` lines explain why a bounce did **not** fire.

If the watchdog is rate-limited, or `sync-workers` itself is down, fall back
to bouncing the local LiveKit server and agent together by hand:

```sh
./.venv/bin/openbase-coder services stop livekit-agent
./.venv/bin/openbase-coder services stop livekit-server
./.venv/bin/openbase-coder services start livekit-server
./.venv/bin/openbase-coder services start livekit-agent
./.venv/bin/openbase-coder services status
```

Then retry the call. A healthy attempt should show:

```text
received job request
Connected to LiveKit room
dispatch_timing stage=agent_session_start_complete
```

## livekit-server Crash-Loops With No Log Output (Code Signature Invalid)

### Symptoms Seen

`openbase-coder services status` flaps between `running` and
`loaded (not running)`; `launchctl list com.openbase.coder.livekit-server`
shows `"LastExitStatus" = 9`; `~/.openbase/logs/livekit-server.log` gains no
new lines on start attempts (the process dies before LiveKit logs anything);
running `~/.openbase/bin/livekit-server --version` by hand prints nothing and
exits 137.

### Diagnosis

Check the newest `livekit-server-*.ips` crash report in
`~/Library/Logs/DiagnosticReports`. The tell is:

```text
"signal": "SIGKILL (Code Signature Invalid)", "termination": {"namespace": "CODESIGNING", "indicator": "Invalid Page"}
```

macOS kills the binary at page-in because its content no longer matches its
code signature. Root cause: the pinned-livekit installer used to
`shutil.copy2` the new binary over the old signed file in place, leaving the
kernel's per-vnode signature cache poisoned (the running server can even keep
executing the *old* version's cached pages until a restart exposes the
corruption). Fixed in cli `6dd3386` (stage + rename into place), but any
binary corrupted before that fix stays broken. Note `codesign -v` may still
report the file as valid on disk — trust the crash report, not codesign.

### Fix

Delete and reinstall the binary, then bounce server and agent together (see
the WebRTC-timeout section above — that section's `livekit_pool_watchdog`
only bounces existing binaries, so a corrupt-signature crash-loop still needs
this manual reinstall first):

```sh
rm ~/.openbase/bin/livekit-server
./.venv/bin/python -c 'from openbase_coder_cli.livekit_install import ensure_pinned_livekit_server; print(ensure_pinned_livekit_server())'
~/.openbase/bin/livekit-server --version   # must print the pinned version
```

Also check the livekit-agent: while the server was down it may have exhausted
its reconnect attempts ("failed to connect to livekit, retrying" then
"Error in _connection_task" in `livekit-agent.log`) and, on installs
predating cli `6dd3386`, it then lingers forever without re-registering —
restart it. Newer installs exit and relaunch via the worker watchdog
automatically.

## Dispatcher Amnesia ("I didn't start that agent") On The Claude Backend

### Symptom

Mid-day, in a new call, the dispatcher denies knowledge of work it did in an
earlier call — e.g. it claims it never started a Super Agent that it
demonstrably launched, or answers "I don't have any context about X" for a
topic it handled an hour before. It can still see the agent in the live
`super_agents_recent` list, so it describes the thread accurately while
denying having started it.

### Root cause

The dispatcher's Claude conversation is one shared native session
(`~/.claude/projects/-Users-<user>/<session>.jsonl`), but
several LiveKit worker processes (and any long-lived MCP server holding a
`ClaudeAgentSdkClient`) each keep their own Claude CLI subprocess attached to
it. Concurrent writers interleave the transcript's parent chains, and a CLI
left connected past its worker's lifetime flushes buffered entries (e.g. a
stop-hook summary) after another worker's turns. Claude Code resumes from the
chain of the *last line* in the file, so the next call forks the conversation
from a stale leaf and every turn recorded on the other branch becomes
invisible to the model.

### Diagnosis

In the session jsonl, look for an entry whose timestamp is older than the
entries physically before it (a late flush), and trace `parentUuid` from the
first post-gap user message — it will point at the stale leaf, skipping the
"forgotten" turns.

### Fix

Fixed on staging (super-agents `e8cced8`, cli `2ecff2d`): the store tracks
which client instance ran each session's last turn so stale cached CLIs
disconnect and re-resume, `ClaudeAgentSdkClient.close()` flushes CLIs at room
end via `LiveKitVoiceRouter.close()`, and a per-session flock serializes
turns across processes. If this recurs on an install predating those
commits, update it; the forked (orphaned) turns cannot be re-attached.

## Onboarding Says "Logged In With Openbase Cloud" But Other Surfaces Disagree

### Symptom

The desktop onboarding login step (or `GET /api/onboarding/status/`) reports
the user is signed in to Openbase Cloud, while the dispatcher voice agent,
console, or cloud heartbeat report "not logged in" / "sign in to Openbase
Cloud again".

### Root cause (historical)

Before cli/desktop staging 2026-07-20, onboarding surfaces only checked that
`~/.openbase/auth.json` contained a token string (presence), while every
runtime surface actually refreshed the token against
`app.openbase.cloud` (validity). A refresh token the server had
expired/rotated/revoked stayed on disk forever, so presence checks said
"logged in" indefinitely.

### Source of truth (current)

`TokenManager.login_status()` (cli `config/token_manager.py`) is the single
answer: `logged_in` / `logged_out` / `login_expired`, validated against the
cloud with a short cache. A definitive refresh rejection is persisted as
`refresh_rejected_at` in `auth.json`, so every process — including the
desktop Electron app, which shells out to `openbase-coder auth status
--json` and falls back to reading the file — reports the same state.
`/api/auth/session/`, `/api/onboarding/status/` (`authenticated` +
`auth_status`), `openbase-coder doctor`, and desktop onboarding all consume
it.

### Diagnosis

Run `openbase-coder auth status --json`. If `login_expired`, the stored
refresh token was rejected — run `openbase-coder login` again. If surfaces
still disagree, the install predates the consolidation; update it.

## Stale Peer Trees, Resurrected Deleted Files, Or Branch Switches Not Propagating (Syncthing Stall)

The user-facing explanation, the 2 GiB disk floor, where the stall surfaces
(dashboard banner, Sync page, `sync status`, `/api/sync/status/`), and the
baseline fix (free disk, restart `code-sync`) are canonical in
`cli/docs/code-sync.md` ("File sync stalled" and "Reading the reconcile
heartbeat"). Symptoms on a two-machine pair: the peer's checkouts lag; files a
commit deleted reappear as *untracked* copies with pre-deletion mtimes
(breaking builds on files nobody edited); `*.sync-conflict-*` copies pile up;
branch switches stop mirroring — because git-state sync rides Syncthing
(repository manifests are synced files), a file-sync stall freezes both layers.

Agent-side diagnosis beyond the user doc:

1. `openbase-coder sync status` — a red `ERROR:` under a folder names the
   stall; a climbing `Reconcile: awaiting_files` means files are behind git
   state.
2. Engine detail: `curl -H "X-API-Key: $(sed -n 's/.*<apikey>\(.*\)<\/apikey>.*/\1/p' ~/.openbase/code-sync/config.xml)" "http://127.0.0.1:8385/rest/db/status?folder=<folder-id>"`
   — the `error` field names the stall reason.
3. Reconcile heartbeat: `grep "code_sync tick_complete" ~/.openbase/logs/sync-workers.log | tail`
   — no lines means the sync-workers service is down; `errors>0` lines are
   explained by an adjacent `code_sync tick_errors` warning naming the repo.

Remedy beyond the baseline: the classic low-disk cause is often Docker VM
images under `~/Library/Containers/com.docker.docker` (multi-hundred-GB). After
freeing disk and restarting `code-sync`, if a deleted file was resurrected,
remove the stray untracked copies on **both** machines (SSH to the peer) or
Syncthing round-trips them back.
