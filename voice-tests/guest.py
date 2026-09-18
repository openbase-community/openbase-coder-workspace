"""Bounded retries for read-only guest observations, never ambiguous mutations."""
import subprocess
import time


def read_guest(helper, vm, command, *, input=None):
    for attempt in range(3):
        result = subprocess.run([str(helper), "ssh", vm, command], text=True,
            capture_output=True, input=input, timeout=30)
        if result.returncode == 0:
            return result.stdout
        if result.returncode != 255 or attempt == 2:
            raise subprocess.CalledProcessError(result.returncode, result.args,
                output=result.stdout, stderr=result.stderr)
        time.sleep(.2)
