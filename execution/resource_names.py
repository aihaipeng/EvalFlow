"""Shared user-visible resource naming rules."""

from __future__ import annotations


def next_copy_name(
    source_name: str,
    existing_names: set[str],
    *,
    max_length: int = 200,
) -> str:
    """Append ``_copy`` until the resource name is unique."""

    candidate = source_name + "_copy"
    while candidate in existing_names:
        candidate += "_copy"
    if len(candidate) > max_length:
        raise ValueError(f"名称追加 _copy 后不能超过 {max_length} 个字符")
    return candidate
