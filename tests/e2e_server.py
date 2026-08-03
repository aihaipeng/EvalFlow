from __future__ import annotations

import os
import tempfile
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.app import create_app


root = Path(tempfile.mkdtemp(prefix="agent-bench-e2e-"))
app = create_app(
    database_path=root / "database.sqlite3",
    execution_root=root / "workflow-executions",
)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("EVALFLOW_E2E_PORT", "8765")),
        log_level="warning",
    )
