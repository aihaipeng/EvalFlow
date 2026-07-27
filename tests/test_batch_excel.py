from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from storage.excel import ExcelSheetRepository


def _workbook(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Cases"
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def test_excel_sheet_repository_preserves_headers_rows_and_json_types(tmp_path: Path) -> None:
    path = tmp_path / "cases.xlsx"
    _workbook(
        path,
        [
            ["case_id", "question", "score", "enabled", "created_at"],
            ["C-1", "退款", 2.5, True, datetime(2026, 7, 27, 12, 30)],
            [None, None, None, None, None],
            ["C-2", "查询", 3, False, None],
        ],
    )

    snapshot = ExcelSheetRepository(path, "Cases").read_snapshot()

    assert snapshot.headers == ("case_id", "question", "score", "enabled", "created_at")
    assert snapshot.header_mode == "HEADER"
    assert [row.row_number for row in snapshot.rows] == [2, 4]
    assert snapshot.rows[0].values == {
        "case_id": "C-1",
        "question": "退款",
        "score": 2.5,
        "enabled": True,
        "created_at": "2026-07-27T12:30:00",
    }


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        (["case_id", "", "question"], "空列名"),
        (["case_id", "case_id"], "不能重复"),
    ],
)
def test_excel_sheet_repository_rejects_invalid_headers(
    tmp_path: Path, headers: list[str], message: str
) -> None:
    path = tmp_path / "invalid.xlsx"
    _workbook(path, [headers, ["C-1", "value"]])

    with pytest.raises(ValueError, match=message):
        ExcelSheetRepository(path, "Cases").read_snapshot()


def test_excel_sheet_repository_rejects_missing_sheet(tmp_path: Path) -> None:
    path = tmp_path / "cases.xlsx"
    _workbook(path, [["case_id"], ["C-1"]])

    with pytest.raises(ValueError, match="Sheet 不存在"):
        ExcelSheetRepository(path, "Missing").read_snapshot()


def test_excel_sheet_repository_generates_legacy_headers_when_first_row_is_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "headerless.xlsx"
    _workbook(
        path,
        [
            ["C-1", "退款", "support", None, None],
            ["C-2", "查询", "sales", None, None],
        ],
    )

    snapshot = ExcelSheetRepository(path, "Cases", "AUTO").read_snapshot()

    assert snapshot.header_mode == "DATA"
    assert snapshot.headers == ("case_id", "question", "column_3")
    assert [row.row_number for row in snapshot.rows] == [1, 2]
    assert snapshot.rows[0].values == {
        "case_id": "C-1",
        "question": "退款",
        "column_3": "support",
    }


def test_excel_sheet_repository_allows_trailing_empty_header_columns(tmp_path: Path) -> None:
    path = tmp_path / "trailing-empty.xlsx"
    _workbook(path, [["case_id", "question", None, None], ["C-1", "退款", None, None]])

    snapshot = ExcelSheetRepository(path, "Cases", "HEADER").read_snapshot()

    assert snapshot.headers == ("case_id", "question")
    assert snapshot.rows[0].values == {"case_id": "C-1", "question": "退款"}


def test_excel_sheet_repository_header_mode_can_override_auto_detection(tmp_path: Path) -> None:
    path = tmp_path / "custom-header.xlsx"
    _workbook(path, [["record", "prompt"], ["C-1", "退款"]])

    as_header = ExcelSheetRepository(path, "Cases", "HEADER").read_snapshot()
    as_data = ExcelSheetRepository(path, "Cases", "DATA").read_snapshot()

    assert as_header.headers == ("record", "prompt")
    assert [row.row_number for row in as_header.rows] == [2]
    assert as_data.headers == ("case_id", "question")
    assert [row.row_number for row in as_data.rows] == [1, 2]
