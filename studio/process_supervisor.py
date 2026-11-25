"""Linux Studio child reaper. Invoked with -I; no checkout imports."""

import ctypes
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path


def supervise():
    # PR_SET_CHILD_SUBREAPER: Harbor/Compose clients may start new sessions.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), "Cannot supervise evaluator children")
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    children.read_text()  # Fail before launching if process ownership is unavailable.
    process = subprocess.Popen(sys.argv[2:], start_new_session=True)
    try:
        code = process.wait(timeout=float(sys.argv[1]))
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        code = None
    # Orphans are adopted here, not by the threaded queue process. Kill only
    # direct, unreaped children (their PIDs cannot yet have been recycled).
    deadline = time.monotonic() + 5
    while children.read_text().strip():
        for child in children.read_text().split():
            with suppress(ProcessLookupError):
                os.kill(int(child), signal.SIGKILL)
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    break
            except ChildProcessError:
                break
        if time.monotonic() >= deadline:
            raise RuntimeError("Evaluator process cleanup could not be confirmed")
        time.sleep(0.01)
    if code is None:
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGALRM)
    return code if code >= 0 else 128 - code


if __name__ == "__main__":
    sys.exit(supervise())
