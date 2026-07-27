"""Atomic repository for Excel test-set display metadata."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Callable

from storage.atomic_files import atomic_write_text, path_lock_for


class ExcelSetMetaRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self._lock = path_lock_for(self.path)

    def load(self) -> dict[str, dict]:
        with self._lock:
            return deepcopy(self._load_unlocked())

    def save(self, meta: dict[str, dict]) -> None:
        with self._lock:
            self._write_unlocked(meta)

    def update(self, mutate: Callable[[dict[str, dict]], None]) -> dict[str, dict]:
        with self._lock:
            meta = self._load_unlocked()
            mutate(meta)
            self._write_unlocked(meta)
            return deepcopy(meta)

    def _load_unlocked(self) -> dict[str, dict]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(name): deepcopy(value)
            for name, value in payload.items()
            if isinstance(value, dict)
        }

    def _write_unlocked(self, meta: dict[str, dict]) -> None:
        serialized = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(self.path, serialized)
