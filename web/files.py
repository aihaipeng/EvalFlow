import subprocess
from pathlib import Path

from fastapi import HTTPException


def open_directory_in_explorer(path: Path) -> str:
    """在 Windows 资源管理器中直接打开指定目录。"""
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise HTTPException(404, f"目录不存在: {resolved.name}")
    try:
        subprocess.Popen(["explorer", str(resolved)])
    except Exception as exc:
        raise HTTPException(500, "无法打开资源管理器") from exc
    return str(resolved)
