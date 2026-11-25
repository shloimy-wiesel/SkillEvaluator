"""Bound Git acquisition and inventory on Studio's Linux host."""

import os
import selectors
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path


class GitLimit(ValueError):
    pass


def limit(name, default):
    value = int(os.environ.get("STUDIO_GIT_MAX_" + name, default))
    if value < 1:
        raise GitLimit("Git limits must be positive.")
    return value


def check_storage(root, maximum):
    total = 0
    for directory, _, files in os.walk(root):
        for file in files:
            try:
                total += (Path(directory) / file).lstat().st_size
            except FileNotFoundError:  # Git renames temporary packs atomically.
                continue
            if total > maximum:
                raise GitLimit("Repository exceeds the Studio Git storage limit.")


def bounded(argv, cwd, env, *, storage=None, inventory=False, sizes=False, discard=False):
    disk = limit("STORAGE_BYTES", 512 << 20)
    entries = limit("ENTRIES", 100_000)
    output = limit("INVENTORY_BYTES", 16 << 20)
    expanded = limit("CHECKOUT_BYTES", 512 << 20)
    blob = limit("BLOB_BYTES", 64 << 20)
    if storage is not None:
        check_storage(storage, disk)
        # Enforce the single-file bound even between aggregate storage checks.
        argv = ["prlimit", f"--fsize={disk}:{disk}", "--", *argv]
    with (
        subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        ) as proc,
        selectors.DefaultSelector() as sel,
    ):
        sel.register(proc.stdout, selectors.EVENT_READ)
        result = bytearray()
        partial = b""
        received = count = total = 0
        deadline = time.monotonic() + 120
        next_check = 0
        try:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise subprocess.TimeoutExpired("git", 120)
                if storage is not None and now >= next_check:
                    check_storage(storage, disk)
                    next_check = now + 0.25
                if not sel.select(0.25):
                    continue
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                received += len(chunk)
                if received > output:
                    raise GitLimit("Repository exceeds the Studio inventory byte limit.")
                if not discard:
                    result.extend(chunk)
                if inventory:
                    count += chunk.count(b"\0")
                    if count > entries:
                        raise GitLimit("Repository exceeds the Studio entry limit.")
                if sizes:
                    records = (partial + chunk).split(b"\0")
                    partial = records.pop()
                    for record in records:
                        size = record.partition(b"\t")[0].split()[-1]
                        if size != b"-":
                            total += int(size)
                            if int(size) > blob or total > expanded:
                                raise GitLimit("Repository exceeds the Studio checkout size limit.")
            if proc.wait(timeout=max(0, deadline - time.monotonic())):
                raise subprocess.CalledProcessError(proc.returncode, "git")
            if storage is not None:
                check_storage(storage, disk)
            return bytes(result)
        finally:
            if proc.returncode is None:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
