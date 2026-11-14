"""Generic JSON-file-backed list storage — the fallback persistence layer used when
Supabase isn't configured/reachable (Phase 2). Not a database: no concurrent-write
safety beyond a single-process file lock, which is adequate for a local prototype and
for isolated pytest fixtures (each test gets its own tmp_path directory), but would
need replacing before any multi-process or production deployment.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any

_locks: dict[str, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    # RLock, not Lock: append() calls read_all() while already holding the lock
    # for the same path — a plain Lock would deadlock on that nested acquire.
    key = str(path)
    if key not in _locks:
        _locks[key] = threading.RLock()
    return _locks[key]


class JsonListStore:
    """Stores a list of plain dicts (already-serialized Pydantic models) in one JSON file."""

    def __init__(self, directory: str, filename: str):
        self.path = Path(directory) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([])

    def _write(self, records: list[dict[str, Any]]) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, default=str)
        os.replace(tmp_path, self.path)

    def read_all(self) -> list[dict[str, Any]]:
        with _lock_for(self.path):
            if not self.path.exists():
                return []
            with open(self.path, encoding="utf-8") as f:
                content = f.read().strip()
                return json.loads(content) if content else []

    def append(self, record: dict[str, Any]) -> None:
        with _lock_for(self.path):
            records = self.read_all()
            records.append(record)
            self._write(records)

    def replace_all(self, records: list[dict[str, Any]]) -> None:
        with _lock_for(self.path):
            self._write(records)
