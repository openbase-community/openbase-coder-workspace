#!/usr/bin/env python3
"""Headless steer harness: steer a running turn through the local API and measure.

Runs against any Openbase Coder local API (a dev install, a Tart VM through an
SSH tunnel, a Maritime workspace) with no phone: starts a turn that does
several slow tool calls, sends a steer part-way through, and reports whether
the steer was accepted, how long until the agent acknowledged it, whether the
behaviour changed, and whether anything was lost, duplicated, queued until the
end, or left the thread stuck at running.

    uv run scripts/steer_harness.py --api http://127.0.0.1:17999 --token-file ~/vm2-token \
        --directory /Users/admin/Desktop/steer-harness --backend openbase_cloud

Each run creates its own thread in ``--directory`` (which must exist on the
API host); files are written under a fresh run subfolder so runs never collide.
Prints one JSON line per run (``--json``) or a short human summary.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

TASK = (
    "Create five text files one at a time in the current folder, named one.txt, two.txt, "
    "three.txt, four.txt and five.txt. Each file contains just its number spelled out in "
    "English. Between files run `sleep {pause}` in the shell so the work is paced. Do not "
    "create any file ahead of time. When finished, say 'Done.'"
)
STEER = (
    "Change of plan: do not create any more numbered files after the one you are on. "
    "Instead create README.md containing the single line 'steered' and then stop."
)
STEER_ACK_WORDS = ("readme", "change of plan", "steer", "stop", "instead")


@dataclass
class RunResult:
    api: str
    backend: str | None
    thread_id: str | None = None
    turn_id: str | None = None
    steer_sent_at_s: float | None = None
    steer_http_ms: int | None = None
    steer_accepted: bool = False
    steer_response: dict = field(default_factory=dict)
    ack_after_steer_s: float | None = None
    files_before_steer: list[str] = field(default_factory=list)
    files_final: list[str] = field(default_factory=list)
    behaviour_changed: bool | None = None
    steer_recorded_on_turn: bool | None = None
    extra_turns: int = 0
    queued_turns_at_end: int = 0
    final_status: str | None = None
    stuck_running: bool = False
    total_s: float | None = None
    error: str | None = None
    injection: dict | None = None
    steer_attempts: int = 0
    expect: str = "steer"

    @property
    def passed(self) -> bool:
        if self.expect == "clean_failure":
            # Failure injection: the turn must end in a terminal state with a
            # reason, never stuck at running, and never duplicated.
            return (
                self.error is None
                and not self.stuck_running
                and self.final_status in ("failed", "cancelled", "completed")
                and self.extra_turns == 0
            )
        return (
            self.error is None
            and self.steer_accepted
            and self.behaviour_changed is True
            and not self.stuck_running
            and self.extra_turns == 0
            and self.queued_turns_at_end == 0
        )


class Api:
    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 30) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.base}/api{path}",
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"error": raw.decode(errors="replace")}
            raise RuntimeError(f"{method} {path} -> {exc.code}: {payload}") from None
        return json.loads(raw) if raw else {}


def _turn_key(turn: dict) -> str | None:
    return turn.get("turn_id") or turn.get("id")


def _assistant_text_after_steer(turn: dict | None) -> str:
    """Assistant text that follows the steer's own user message on the turn."""
    if not turn:
        return ""
    messages = turn.get("messages") or turn.get("items") or []
    seen_steer = False
    chunks = []
    for message in messages:
        text = message.get("text") or message.get("content") or ""
        if not isinstance(text, str):
            continue
        if message.get("role") == "user" and text.startswith(STEER[:20]):
            seen_steer = True
            continue
        if seen_steer and message.get("role") == "assistant":
            chunks.append(text.lower())
    return "\n".join(chunks)


def _run_injection(command: str | None, result: RunResult) -> None:
    """Run a failure-injection shell command right before the steer (e.g. an
    SSH command that restarts django-cli on the API host, or kills the
    backend's CLI child). Its outcome is recorded, never fatal."""
    if not command:
        return
    import shlex
    import subprocess

    started = time.monotonic()
    try:
        completed = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=60)
        result.injection = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip()[-300:],
            "stderr": completed.stderr.strip()[-300:],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001
        result.injection = {"command": command, "error": f"{type(exc).__name__}: {exc}"}


def run_once(
    api: Api,
    *,
    directory: str,
    backend: str | None,
    model: str | None,
    pause: int,
    steer_after: float,
    deadline: float,
    list_files,
    inject: str | None = None,
    steer_retries: int = 0,
) -> RunResult:
    result = RunResult(api=api.base, backend=backend)
    started = time.monotonic()
    try:
        body = {"directory": directory}
        if backend:
            body["backend"] = backend
        if model:
            body["model"] = model
        created = api.call("POST", "/threads/", body)
        result.thread_id = thread_id = created["thread_id"]
        turn = api.call("POST", f"/threads/{thread_id}/turns/", {"prompt": TASK.format(pause=pause)})
        result.turn_id = turn_id = turn["turn_id"]

        # Wait until the agent has actually started producing files, then steer.
        while time.monotonic() - started < steer_after:
            time.sleep(0.5)
        result.files_before_steer = list_files()
        _run_injection(inject, result)
        steer_started = time.monotonic()
        steer: dict = {}
        for attempt in range(steer_retries + 1):
            try:
                steer = api.call("POST", f"/threads/{thread_id}/turns/steer/", {"prompt": STEER})
                result.steer_accepted = bool(steer.get("steered"))
                result.steer_attempts = attempt + 1
                break
            except (RuntimeError, OSError) as exc:
                steer = {"error": str(exc)}
                result.steer_attempts = attempt + 1
                if attempt < steer_retries:
                    time.sleep(2.0)
        result.steer_http_ms = int((time.monotonic() - steer_started) * 1000)
        result.steer_sent_at_s = round(steer_started - started, 2)
        result.steer_response = steer

        ack_at = None
        while True:
            detail = api.call("GET", f"/threads/{thread_id}/")
            current = detail.get("current_turn")
            history = detail.get("turn_history") or []
            turns = [t for t in ([current] if current else []) + history if t]
            this_turn = next((t for t in turns if _turn_key(t) == turn_id), None)
            texts = _assistant_text_after_steer(this_turn)
            if ack_at is None and any(word in texts for word in STEER_ACK_WORDS):
                ack_at = time.monotonic()
                result.ack_after_steer_s = round(ack_at - steer_started, 2)
            status = detail.get("status")
            result.final_status = status
            result.queued_turns_at_end = len(detail.get("queued_turns") or [])
            if this_turn is not None:
                steers = this_turn.get("steers") or []
                result.steer_recorded_on_turn = any(STEER[:20] in (s.get("text") or "") for s in steers)
            result.extra_turns = len([t for t in turns if _turn_key(t) != turn_id])
            if status not in ("running", "waiting", "in_progress") and current is None:
                break
            if time.monotonic() - started > deadline:
                result.stuck_running = True
                break
            time.sleep(1.0)
        result.files_final = list_files()
        numbered = [f for f in result.files_final if f in ("three.txt", "four.txt", "five.txt")]
        result.behaviour_changed = "README.md" in result.files_final and len(numbered) <= 1
    except Exception as exc:  # noqa: BLE001 - the harness reports, never crashes
        result.error = f"{type(exc).__name__}: {exc}"
    result.total_s = round(time.monotonic() - started, 2)
    return result


async def run_inprocess(
    *,
    backend: str,
    directory: str,
    store_path: str,
    pause: int,
    steer_after: float,
    deadline: float,
    list_files,
    inject: str | None = None,
) -> RunResult:
    """Drive super-agents directly (no local API): the backend's own steer path."""
    import asyncio
    import os

    from pathlib import Path

    from super_agents.agent_store import Store
    from super_agents.app_models import LabelQueryInput

    result = RunResult(api=f"inprocess:{backend}", backend=backend)
    started = time.monotonic()
    client = None
    try:
        os.environ.setdefault("OPENBASE_CODING_BACKEND", backend)
        if backend == "claude_code":
            from super_agents.claude_sdk import ClaudeAgentSdkClient

            client = ClaudeAgentSdkClient(store=Store(Path(store_path)))
        else:
            from super_agents.app_server_client import CodexAppServerClient

            client = CodexAppServerClient(backend_identity=backend)
        name = f"steer-harness-{int(time.time())}"
        thread = await client.start_thread({"name": name, "cwd": directory})
        result.thread_id = thread_id = thread.get("threadId") or (thread.get("thread") or {}).get("id")
        # Claude resolves a thread id; the Codex client keys label queries by name.
        query = (lambda **extra: LabelQueryInput(thread_id=thread_id, **extra)) if backend == "claude_code" else (
            lambda **extra: LabelQueryInput(label=name, cwd=directory, **extra)
        )
        turn = await client.start_turn_by_label(query(), {"prompt": TASK.format(pause=pause), "cwd": directory})
        if not isinstance(turn, dict) or not (turn.get("turnId") or turn.get("turn_id")):
            raise RuntimeError(f"unexpected start_turn result: {str(turn)[:200]}")
        result.turn_id = turn_id = turn.get("turnId") or turn.get("turn_id")

        while time.monotonic() - started < steer_after:
            await asyncio.sleep(0.5)
        result.files_before_steer = list_files()
        _run_injection(inject, result)
        steer_started = time.monotonic()
        try:
            steer = await client.steer_by_label(query(turn_id=turn_id, prefer="latest_active"), STEER, {"cwd": directory})
            # Claude answers {"steered": true}; the Codex app-server answers with the
            # steered turn's id (turn/steer result), so either counts as accepted.
            result.steer_accepted = bool(steer.get("steered")) or steer.get("turnId") == turn_id
        except Exception as exc:  # noqa: BLE001 - report, never crash
            steer = {"error": f"{type(exc).__name__}: {exc}"}
        result.steer_http_ms = int((time.monotonic() - steer_started) * 1000)
        result.steer_sent_at_s = round(steer_started - started, 2)
        result.steer_response = {k: v for k, v in steer.items() if k in ("steered", "turnId", "queued", "delivery", "confirmed", "error", "reason")}

        while True:
            try:
                progress = await client.progress_by_label(query())
            except ValueError as exc:
                if "No active Super Agents session" in str(exc):
                    # Codex: the turn finished and the label is no longer active.
                    result.final_status = "completed"
                    break
                raise
            if not isinstance(progress, dict):
                raise RuntimeError(f"unexpected progress result: {str(progress)[:200]}")
            turns = progress.get("turns") or []
            if not turns and isinstance(progress.get("turn"), dict):
                turns = [progress["turn"]]
            this_turn = next((t for t in turns if (t.get("turnId") or t.get("id")) == turn_id), None)
            if this_turn is not None:
                result.steer_recorded_on_turn = any(STEER[:20] in (s.get("text") or "") for s in (this_turn.get("steers") or []))
                status = this_turn.get("status")
                if this_turn.get("error") or this_turn.get("lastError") or this_turn.get("errorKind"):
                    result.steer_response = {**result.steer_response, "turnError": this_turn.get("lastError") or this_turn.get("error"), "errorKind": this_turn.get("errorKind")}
            else:
                status = progress.get("status")
            result.final_status = status
            result.extra_turns = len([t for t in turns if (t.get("turnId") or t.get("id")) != turn_id])
            if result.ack_after_steer_s is None:
                text = (this_turn or {}).get("lastUsefulMessage") or progress.get("lastUsefulMessage") or ""
                if any(word in text.lower() for word in STEER_ACK_WORDS):
                    result.ack_after_steer_s = round(time.monotonic() - steer_started, 2)
            if status in ("completed", "failed", "cancelled"):
                break
            if time.monotonic() - started > deadline:
                result.stuck_running = True
                break
            await asyncio.sleep(1.0)
        result.files_final = list_files()
        numbered = [f for f in result.files_final if f in ("three.txt", "four.txt", "five.txt")]
        result.behaviour_changed = "README.md" in result.files_final and len(numbered) <= 1
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    pass
    result.total_s = round(time.monotonic() - started, 2)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", help="local API base, e.g. http://127.0.0.1:7999")
    parser.add_argument("--token-file", help="file holding the local API token")
    parser.add_argument("--inprocess", choices=["claude_code", "codex"], help="drive super-agents directly instead of the API")
    parser.add_argument("--store", default=None, help="in-process mode: scratch Super Agents store path")
    parser.add_argument("--directory", required=True, help="project folder on the API host (must exist)")
    parser.add_argument("--backend", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--pause", type=int, default=6, help="seconds the agent sleeps between files")
    parser.add_argument("--steer-after", type=float, default=12.0, help="seconds after start to send the steer")
    parser.add_argument("--deadline", type=float, default=90.0, help="seconds before the run is called stuck")
    parser.add_argument("--list-files-cmd", required=True, help="shell command printing the run folder's file names, one per line")
    parser.add_argument("--inject", default=None, help="failure injection: shell command run just before the steer (restart the API, kill the CLI child, ...)")
    parser.add_argument("--steer-retries", type=int, default=0, help="API mode: retry the steer POST this many times, 2 s apart, when it fails")
    parser.add_argument("--expect", choices=["steer", "clean_failure"], default="steer", help="pass criterion: a landed steer, or a clean terminal failure (for injections)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    import shlex
    import subprocess

    def list_files() -> list[str]:
        out = subprocess.run(shlex.split(args.list_files_cmd), capture_output=True, text=True, timeout=20)
        return sorted(line.strip() for line in out.stdout.splitlines() if line.strip())

    if args.inprocess:
        import asyncio

        result = asyncio.run(
            run_inprocess(
                backend=args.inprocess,
                directory=args.directory,
                store_path=args.store or f"{args.directory}/.steer-harness-store.sqlite3",
                pause=args.pause,
                steer_after=args.steer_after,
                deadline=args.deadline,
                list_files=list_files,
                inject=args.inject,
            )
        )
    else:
        if not args.api or not args.token_file:
            parser.error("--api and --token-file are required unless --inprocess is given")
        with open(args.token_file) as handle:
            token = handle.read().strip()
        api = Api(args.api, token)
        result = run_once(
            api,
            directory=args.directory,
            backend=args.backend,
            model=args.model,
            pause=args.pause,
            steer_after=args.steer_after,
            deadline=args.deadline,
            list_files=list_files,
            inject=args.inject,
            steer_retries=args.steer_retries,
        )
    result.expect = args.expect
    payload = asdict(result)
    payload["passed"] = result.passed
    if args.json:
        print(json.dumps(payload))
    else:
        print(f"{'PASS' if result.passed else 'FAIL'} thread={result.thread_id} turn={result.turn_id}")
        print(f"  steer accepted={result.steer_accepted} http={result.steer_http_ms} ms sent at {result.steer_sent_at_s} s")
        print(f"  ack after steer={result.ack_after_steer_s} s  behaviour changed={result.behaviour_changed}")
        print(f"  files before={result.files_before_steer} final={result.files_final}")
        print(f"  steer on turn={result.steer_recorded_on_turn} extra turns={result.extra_turns} queued={result.queued_turns_at_end}")
        print(f"  final status={result.final_status} stuck={result.stuck_running} total={result.total_s} s error={result.error}")
        if result.injection:
            print(f"  injection={result.injection} steer attempts={result.steer_attempts} response={result.steer_response}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
