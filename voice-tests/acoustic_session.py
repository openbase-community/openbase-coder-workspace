"""Prevent competing captures or fixture downloads on shared acoustic hardware."""
from contextlib import contextmanager
import fcntl


@contextmanager
def acoustic_session(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("An acoustic session is active; finish it before recording or preparing speech fixtures") from error
        try:
            yield
        finally:
            fcntl.flock(lease, fcntl.LOCK_UN)
