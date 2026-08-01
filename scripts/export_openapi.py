"""Export the FastAPI contract used by the generated browser clients."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from web.app import app  # noqa: E402

OUTPUT = PROJECT_ROOT / "web" / "frontend" / "generated" / "openapi.json"


def canonical_schema() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(canonical_schema(), encoding="utf-8")
