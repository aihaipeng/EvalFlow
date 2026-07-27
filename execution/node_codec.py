"""Public serialization boundary for Node Structural definitions."""

from __future__ import annotations

import json
from typing import Protocol


class JsonModel(Protocol):
    def model_dump(self, *, mode: str, exclude: set[str]) -> dict: ...


def dump_node_definition(node: JsonModel) -> str:
    payload = node.model_dump(
        mode="json",
        exclude={"id", "type", "name", "description"},
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
