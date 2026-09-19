"""Small stdlib-only cross-process file lock used by SignalForge durable ledgers.

The lock is advisory but process-wide on both Windows and POSIX.  It is only used
for short critical sections around append/read-modify-write operations that must
serialize across FastAPI, MCP and acceptance worker processes.
"""
from __future__ import annotations

import os
import time
import asyncio
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def cross_process_file_lock(path: Path, *, timeout: float = 30.0, poll: float = 0.05) -> Iterator[None]:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    deadline = time.monotonic() + max(0.1, float(timeout))
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(b"\0")
                fh.flush()
                os.fsync(fh.fileno())
            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring cross-process lock: {lock_path}")
                    time.sleep(poll)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out acquiring cross-process lock: {lock_path}")
                    time.sleep(poll)
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()
        else:
            fh.close()


@asynccontextmanager
async def async_cross_process_file_lock(path: Path, *, timeout: float = 30.0, poll: float = 0.05):
    """Async-safe wrapper around the same OS-level lock domain.

    Acquisition/release run in worker threads so an API coroutine never blocks
    the event loop while another process owns the lock.
    """
    cm = cross_process_file_lock(path, timeout=timeout, poll=poll)
    await asyncio.to_thread(cm.__enter__)
    try:
        yield
    finally:
        await asyncio.to_thread(cm.__exit__, None, None, None)
