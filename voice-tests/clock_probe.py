"""Causal clock samples over a warmed SSH channel, excluding connection setup."""
import selectors
import shlex
import subprocess
import time


def calibration_from_samples(samples):
    """Retain offset movement between probe batches instead of intersecting hours."""
    batches = []
    for sample in sorted(samples, key=lambda s: s["host_before_ms"]):
        if not batches or sample["host_before_ms"] - batches[-1][-1]["host_after_ms"] > 1000:
            batches.append([])
        batches[-1].append(sample)
    intervals = []
    for batch in batches:
        lower = max(s["lower_ms"] for s in batch)
        upper = min(s["upper_ms"] for s in batch)
        if lower > upper:
            raise ValueError("VM clock bounds conflict within a probe batch")
        intervals.append({"lower_ms": lower, "upper_ms": upper,
            "host_before_ms": batch[0]["host_before_ms"], "host_after_ms": batch[-1]["host_after_ms"]})
    lower, upper = min(b["lower_ms"] for b in intervals), max(b["upper_ms"] for b in intervals)
    return {"server": {"offset_ms": (lower + upper) / 2, "uncertainty_ms": (upper - lower) / 2,
        "method": "envelope of causal SSH probe batches; assumes no larger clock excursion between probes"},
        "samples": samples, "batches": intervals}


class ClockTransportError(RuntimeError):
    def __init__(self, evidence):
        super().__init__('VM clock SSH transport failed')
        self.evidence = evidence


def sample_vm_clock(guest_helper, vm, count=10):
    failures = []
    for attempt in range(3):
        try:
            samples = _sample_vm_clock_once(guest_helper, vm, count)
            if failures:
                samples[0]['startup_retry_events'] = failures
            return samples
        except ClockTransportError as error:
            failures.append(error.evidence)
            if attempt == 2:
                raise
            time.sleep(.2)


def _sample_vm_clock_once(guest_helper, vm, count):
    program = "import sys,time\nprint('READY',flush=True)\nfor line in sys.stdin:\n print(time.time_ns()/1e6,flush=True)"
    command = "~/Developer/openbase-coder-workspace/.venv/bin/python -u -c " + shlex.quote(program)
    process = subprocess.Popen([str(guest_helper), "ssh", vm, command], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    def read():
        if not selector.select(timeout=20):
            raise TimeoutError("VM clock channel did not respond")
        line = process.stdout.readline().strip()
        if not line:
            code = process.wait(timeout=5)
            if code == 255:
                stderr = process.stderr.read(1024)
                raise ClockTransportError({'host_observed_unix_ms':time.time_ns()/1e6,
                    'ssh_exit_code':code,'authentication_rejected':'Permission denied' in stderr,
                    'finding':'Clock probe channel closed; retry only this read-only observation'})
            raise RuntimeError("VM clock channel closed")
        return line
    try:
        if read() != "READY":
            raise RuntimeError("VM clock channel did not become ready")
        samples = []
        for _ in range(count):
            before = time.time_ns() / 1e6
            process.stdin.write("probe\n")
            process.stdin.flush()
            remote = float(read())
            after = time.time_ns() / 1e6
            samples.append({"lower_ms": remote - after, "upper_ms": remote - before,
                "host_before_ms": before, "host_after_ms": after, "server_ms": remote})
        return samples
    finally:
        selector.close()
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
