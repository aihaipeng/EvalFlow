"""Application service for local YAML configuration and input paths."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from storage.local_config import LocalConfigError, LocalConfigRepository
from web.files import PROJECT_ROOT, get_input_path


CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_INPUT_PATH = "inputs/testcases.xlsx"
DEFAULT_SHEET_NAME = "Sheet1"


def _default_config() -> dict:
    return {
        "excel": {
            "input_path": DEFAULT_INPUT_PATH,
            "sheet_name": DEFAULT_SHEET_NAME,
        }
    }


def _repository() -> LocalConfigRepository:
    return LocalConfigRepository(CONFIG_PATH, _default_config)


def load_local_config() -> dict:
    try:
        return _repository().load()
    except LocalConfigError as exc:
        raise HTTPException(500, str(exc)) from exc


def save_local_config(config: dict) -> None:
    try:
        _repository().save(config)
    except LocalConfigError as exc:
        raise HTTPException(500, str(exc)) from exc


def update_local_config(mutate) -> dict:
    try:
        return _repository().update(mutate)
    except LocalConfigError as exc:
        raise HTTPException(500, str(exc)) from exc


def input_path_for(filename: str) -> Path:
    return get_input_path(filename)
