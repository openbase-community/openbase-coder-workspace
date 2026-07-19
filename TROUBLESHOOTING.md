# Troubleshooting

This guide is for **agents** debugging a running Openbase Coder install from
this workspace: symptoms, log locations, bounded log checks, and fixes.
User-facing troubleshooting lives in the product docs at
`cli/docs/troubleshooting.md` (https://docs.openbase.cloud/troubleshooting/);
put anything an end user should read there, not here.

When reading logs under `~/.openbase/logs`, always use bounded reads
(`tail -n ...` piped to a filter) — the files are huge.

## iOS Call Stuck On "Connecting..."

This issue can happen when the iOS app successfully gets a LiveKit room token and opens signaling, but WebRTC media never connects.

### Expected Network Targets

The iOS app default backend host is:

```text
your-mac.tailnet-name.ts.net
```

Expected ports:

```text
http://your-mac.tailnet-name.ts.net:18080 -> Django/Openbase API on 127.0.0.1:7999
ws://your-mac.tailnet-name.ts.net:7880   -> LiveKit signaling on 127.0.0.1:7880
100.64.0.10:7881                         -> LiveKit TCP RTC
100.64.0.10:7882                         -> LiveKit UDP RTC
```

Check Tailscale Serve:

```sh
tailscale serve status --json
```

Expected shape:

```json
{
  "TCP": {
    "18080": { "HTTP": true },
    "7880": { "TCPForward": "127.0.0.1:7880" }
  },
  "Web": {
    "your-mac.tailnet-name.ts.net:18080": {
      "Handlers": {
        "/": { "Proxy": "http://127.0.0.1:7999" }
      }
    }
  }
}
```

### Symptoms Seen

The phone was stuck on "connecting..." even though Django returned room tokens:

```text
POST /api/livekit-room-token/ HTTP/1.1" 200 OK
```

LiveKit server logs showed the iPhone signaling into the room, then disconnecting before WebRTC completed:

```text
removing participant without connection
reason: SIGNAL_SOURCE_CLOSE
dtls timeout: read/write timeout: context deadline exceeded
```

The LiveKit agent did receive the job and joined the room, so dispatch was not the problem:

```text
received job request
Connected to LiveKit room
LiveKit AgentSession started
```

### Root Cause

The LiveKit server had stale Tailscale interface configuration. It advertised the Tailscale node IP in ICE candidates:

```text
100.64.0.10:7882
100.64.0.10:7881
```

But `lsof` showed UDP was only bound on loopback:

```text
UDP 127.0.0.1:7882
TCP *:7881
TCP 127.0.0.1:7880
```

The running `livekit-server` command was using the wrong interface in its RTC config:

```text
interfaces:
  includes:
    - lo0
    - en7
```

The active Tailscale interface was actually `utun4`.

### Fix

Regenerate and reload the Openbase launchd service wrappers:

```sh
./.venv/bin/openbase-coder services regenerate
./.venv/bin/openbase-coder services install
```

Then confirm LiveKit is running with the Tailscale interface:

```sh
ps -ax -o pid,command | rg '[l]ivekit-server'
```

The command should include:

```text
interfaces:
  includes:
    - lo0
    - utun4
```

Confirm UDP is bound to the Tailscale IP:

```sh
lsof -nP -iTCP:7880 -iTCP:7881 -iUDP:7882
```

Expected after the fix:

```text
UDP 127.0.0.1:7882
UDP 100.64.0.10:7882
UDP [TAILSCALE_IPV6]:7882
TCP *:7881 (LISTEN)
TCP 127.0.0.1:7880 (LISTEN)
```

After this, a new call should show the iPhone participant becoming active, media tracks publishing, and audio tracks subscribing instead of `removing participant without connection`.

### Bounded Log Checks

Do not dump the full files in `~/.openbase/logs`; they can be large. Use bounded reads:

```sh
tail -n 360 ~/.openbase/logs/django-cli.log | rg -i 'livekit-room-token|error|warning'
tail -n 360 ~/.openbase/logs/livekit-agent.log | rg -i 'received job request|Connected to LiveKit room|AgentSession started|error|failed'
tail -n 360 ~/.openbase/logs/livekit-server.log | rg -i 'participant active|without connection|SIGNAL_SOURCE_CLOSE|dtls timeout|ice connection state change'
```

Useful connectivity checks:

```sh
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

If the bindings and Tailscale Serve config are correct, bounce the local LiveKit server and agent together:

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
the WebRTC-timeout section above):

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
(`~/.openbase/claude_config/projects/-Users-<user>/<session>.jsonl`), but
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
