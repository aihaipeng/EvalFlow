import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import yaml

from storage import atomic_files
from storage.excel_set_meta import ExcelSetMetaRepository
from storage.local_config import LocalConfigRepository


def test_local_config_concurrent_updates_preserve_every_value(tmp_path):
    path = tmp_path / "config.yaml"

    def repository():
        return LocalConfigRepository(path, lambda: {"values": {}})

    def update(index: int) -> None:
        repository().update(
            lambda config: config.setdefault("values", {}).__setitem__(str(index), index)
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(update, range(32)))

    assert repository().load()["values"] == {str(index): index for index in range(32)}
    assert isinstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict)


def test_excel_set_meta_concurrent_updates_preserve_every_file(tmp_path):
    path = tmp_path / ".sets_meta.json"

    def update(index: int) -> None:
        ExcelSetMetaRepository(path).update(
            lambda meta: meta.__setitem__(
                f"set-{index}.xlsx", {"description": f"description-{index}"}
            )
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(update, range(32)))

    payload = ExcelSetMetaRepository(path).load()
    assert len(payload) == 32
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_atomic_replace_failure_preserves_previous_config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    repository = LocalConfigRepository(path, dict)
    repository.save({"version": 1})

    def fail_replace(_source, _target):
        raise PermissionError("locked")

    monkeypatch.setattr(atomic_files.os, "replace", fail_replace)

    with pytest.raises(Exception, match="locked"):
        repository.save({"version": 2})

    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {"version": 1}
    assert list(tmp_path.glob("*.tmp")) == []
