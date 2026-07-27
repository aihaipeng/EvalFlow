from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import threading
import time

import yaml
from fastapi.testclient import TestClient
from openpyxl import Workbook

from web import files, local_config_service, routes_excel
from web.app import app


def _workbook_bytes() -> bytes:
    output = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Cases"
    sheet.append(["case_id", "question"])
    sheet.append(["case_001", "示例问题"])
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _patch_local_state(tmp_path, monkeypatch):
    inputs_dir = tmp_path / "inputs"
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(files, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(files, "INPUTS_DIR", inputs_dir)
    monkeypatch.setattr(routes_excel, "INPUTS_DIR", inputs_dir)
    monkeypatch.setattr(routes_excel, "SETS_META_FILE", inputs_dir / ".sets_meta.json")
    monkeypatch.setattr(local_config_service, "CONFIG_PATH", config_path)
    return inputs_dir, config_path


def test_missing_local_config_uses_safe_defaults(tmp_path, monkeypatch):
    _, config_path = _patch_local_state(tmp_path, monkeypatch)

    response = TestClient(app).get("/api/config/current")

    assert response.status_code == 200
    assert response.json() == {"filename": "testcases.xlsx", "sheet_name": "Sheet1"}
    assert not config_path.exists()


def test_first_upload_creates_local_config(tmp_path, monkeypatch):
    inputs_dir, config_path = _patch_local_state(tmp_path, monkeypatch)

    response = TestClient(app).post(
        "/api/excel/upload",
        files={
            "file": (
                "public-sample.xlsx",
                _workbook_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    assert (inputs_dir / "public-sample.xlsx").is_file()
    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == {
        "excel": {
            "input_path": "inputs\\public-sample.xlsx",
            "sheet_name": "Cases",
        }
    }


def test_slow_excel_upload_does_not_block_async_routes(tmp_path, monkeypatch):
    _patch_local_state(tmp_path, monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    original_detect_sheets = routes_excel._detect_sheets

    def slow_detect_sheets(path):
        entered.set()
        assert release.wait(timeout=2)
        return original_detect_sheets(path)

    monkeypatch.setattr(routes_excel, "_detect_sheets", slow_detect_sheets)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        upload = executor.submit(
            client.post,
            "/api/excel/upload",
            files={
                "file": (
                    "slow-sample.xlsx",
                    _workbook_bytes(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert entered.wait(timeout=2)

        fallback_release = threading.Timer(0.6, release.set)
        fallback_release.start()
        started = time.monotonic()
        try:
            response = client.get("/")
            elapsed = time.monotonic() - started
            release.set()
            upload_response = upload.result(timeout=2)
        finally:
            release.set()
            fallback_release.cancel()

    assert response.status_code == 200
    assert elapsed < 0.3
    assert upload_response.status_code == 200
