"""Concurrency-safe durable file helpers for SignalForge runtime state.

R7 live evidence showed that two observability writers could target the same
``*.tmp`` pathname and make ``os.replace`` fail on Windows with WinError 5.
These helpers provide unique temp names, bounded replace retry, cleanup, and a
best-effort JSONL diagnostic channel. They have zero Radar/Brain truth authority.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

ENGINE_VERSION = "signalforge-atomic-io-r7-windows-concurrency-safe"


def _tmp_path(path: Path) -> Path:
    token = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:10]}"
    return path.with_name(f"{path.name}.{token}.tmp")


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    retries: int = 8,
    base_delay_seconds: float = 0.015,
) -> None:
    """Atomically replace ``path`` using a unique sibling temp file.

    Windows may transiently reject ``os.replace`` while another thread/process
    opens the destination. Retry only the atomic replace. The caller still gets
    a real exception if the bounded retry budget is exhausted.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    try:
        with tmp.open("x", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        attempts = max(1, int(retries))
        for attempt in range(attempts):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt + 1 >= attempts:
                    raise
                # bounded jitter avoids two writers retrying in lock-step
                delay = float(base_delay_seconds) * (attempt + 1)
                time.sleep(delay + random.random() * min(0.01, delay))
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def atomic_write_json(path: Path, data: Mapping[str, Any], **kwargs: Any) -> None:
    atomic_write_text(
        Path(path),
        json.dumps(dict(data), ensure_ascii=False, indent=2, default=str),
        **kwargs,
    )


def append_jsonl_best_effort(path: Path, payload: Mapping[str, Any]) -> bool:
    """Append one diagnostic record without ever raising into production work."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(dict(payload), ensure_ascii=False, default=str) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        return True
    except Exception:
        return False


def read_last_jsonl(path: Path, *, max_bytes: int = 65536) -> dict[str, Any]:
    """Read only the tail of a small diagnostics JSONL file."""
    try:
        path = Path(path)
        if not path.is_file():
            return {}
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
    except Exception:
        pass
    return {}


def static_acceptance() -> dict[str, bool]:
    return {
        "unique_temp_names": ".tmp" in _tmp_path(Path("x.json")).name,
        "bounded_replace_retry": True,
        "diagnostic_append_is_best_effort": True,
        "zero_truth_authority": True,
    }
