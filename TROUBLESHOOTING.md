# Troubleshooting

This guide is for **agents** debugging a running Openbase install from
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

## iOS Call Stuck On "Waiting For Agent"

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
