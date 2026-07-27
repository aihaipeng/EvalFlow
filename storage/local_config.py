"""Atomic repository for the local YAML application configuration."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Callable

import yaml

from storage.atomic_files import atomic_write_text, path_lock_for


class LocalConfigError(RuntimeError):
    pass


class LocalConfigRepository:
    def __init__(self, path: str | Path, default_factory: Callable[[], dict]):
        self.path = Path(path).resolve()
        self.default_factory = default_factory
        self._lock = path_lock_for(self.path)

    def load(self) -> dict:
        with self._lock:
            return deepcopy(self._load_unlocked())

    def save(self, config: dict) -> None:
        with self._lock:
            self._write_unlocked(config)

    def update(self, mutate: Callable[[dict], bool | None]) -> dict:
        with self._lock:
            config = self._load_unlocked()
            changed = mutate(config)
            if changed is not False:
                self._write_unlocked(config)
            return deepcopy(config)

    def _load_unlocked(self) -> dict:
        if not self.path.is_file():
            default = self.default_factory()
            if not isinstance(default, dict):
                raise LocalConfigError("默认配置必须是 object")
            return deepcopy(default)
        try:
            raw = self.path.read_text(encoding="utf-8")
            config = yaml.safe_load(raw)
        except (OSError, yaml.YAMLError) as exc:
            raise LocalConfigError(f"配置文件不可读取: {exc}") from exc
        if not isinstance(config, dict):
            raise LocalConfigError("config.yaml 格式错误")
        return config

    def _write_unlocked(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise LocalConfigError("配置必须是 object")
        try:
            serialized = yaml.safe_dump(
                config,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            atomic_write_text(self.path, serialized)
        except (OSError, yaml.YAMLError) as exc:
            raise LocalConfigError(f"配置文件无法保存: {exc}") from exc
