from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web.files import get_existing_input_path, project_relative, resolve_config_input_path
from web.local_config_service import (
    CONFIG_PATH,
    DEFAULT_INPUT_PATH,
    DEFAULT_SHEET_NAME,
    input_path_for,
    load_local_config,
    save_local_config,
    update_local_config,
)

router = APIRouter(prefix="/api/config", tags=["config"])

class CurrentConfigRequest(BaseModel):
    """设置当前测试集和 sheet 的请求体。"""

    filename: str
    sheet_name: str


class CurrentConfigResponse(BaseModel):
    """当前测试集和 sheet 配置。"""

    filename: str
    sheet_name: str


# Compatibility aliases for callers outside the production route modules.
_load_yaml = load_local_config
_save_yaml = save_local_config
_get_input_path = input_path_for


@router.get("/current", response_model=CurrentConfigResponse)
def get_current_config() -> CurrentConfigResponse:
    """获取当前使用的测试集文件和 sheet 名。"""
    config = load_local_config()
    excel = config.get("excel", {})
    input_path = excel.get("input_path", DEFAULT_INPUT_PATH)
    try:
        filename = resolve_config_input_path(input_path).name
    except HTTPException:
        filename = Path(str(input_path)).name
    sheet_name = excel.get("sheet_name", DEFAULT_SHEET_NAME)
    return CurrentConfigResponse(filename=filename, sheet_name=sheet_name)


@router.post("/current")
def set_current_config(body: CurrentConfigRequest) -> dict:
    """设置当前使用的测试集文件和 sheet 名。

    Args:
        body: 包含 ``filename`` 和 ``sheet_name`` 的请求体。

    Returns:
        确认信息。

    Raises:
        HTTPException 400: 文件或 sheet 不存在。
    """
    input_path = get_existing_input_path(body.filename)

    import openpyxl

    wb = openpyxl.load_workbook(input_path, read_only=True)
    sheet_names = wb.sheetnames
    wb.close()

    if body.sheet_name not in sheet_names:
        raise HTTPException(400, f"Sheet 不存在: {body.sheet_name}。可用: {', '.join(sheet_names)}")

    def mutate(config: dict) -> None:
        config.setdefault("excel", {})["input_path"] = project_relative(input_path)
        config["excel"]["sheet_name"] = body.sheet_name

    update_local_config(mutate)
    return {"ok": True}
