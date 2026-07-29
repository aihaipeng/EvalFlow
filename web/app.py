from contextlib import asynccontextmanager
from pathlib import Path

from execution import DEFAULT_DATABASE_PATH, DEFAULT_EXECUTION_ROOT
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from web.routes_config import router as config_router
from web.routes_excel import router as excel_router
from web.routes_files import router as files_router
from web.routes_local_clipboard import router as local_clipboard_router
from web.routes_model_providers import router as model_providers_router
from web.routes_testcases import router as testcases_router
from web.routes_test_sets import router as test_sets_router
from web.routes_workflows import router as workflows_router
from web.routes_batch_runs import router as batch_runs_router
from web.workflow_services import WorkflowServices

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(
    *,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    execution_root: str | Path = DEFAULT_EXECUTION_ROOT,
) -> FastAPI:
    """创建并配置 FastAPI 应用。

    Returns:
        已注册路由、中间件和静态文件的应用实例。
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = WorkflowServices(database_path, execution_root)
        app.state.workflow_services = services
        try:
            yield
        finally:
            try:
                services.shutdown()
            finally:
                del app.state.workflow_services

    app = FastAPI(title="Agent Bench", lifespan=lifespan)

    app.include_router(excel_router)
    app.include_router(config_router)
    app.include_router(files_router)
    app.include_router(local_clipboard_router)
    app.include_router(model_providers_router)
    app.include_router(testcases_router)
    app.include_router(test_sets_router)
    app.include_router(workflows_router)
    app.include_router(batch_runs_router)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    # 静态文件 — 显式路由，避免 StaticFiles mount 拦截 API 的 PUT/DELETE
    # 添加 Cache-Control 头，防止浏览器缓存旧版文件
    _NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    @app.get("/")
    async def index():
        """返回首页 HTML。"""
        return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)

    @app.get("/style.css")
    async def style_css():
        """返回样式表。"""
        return FileResponse(STATIC_DIR / "style.css", headers=_NO_CACHE)

    @app.get("/app.js")
    async def app_js():
        """返回前端 JS。"""
        return FileResponse(STATIC_DIR / "app.js", headers=_NO_CACHE)

    @app.get("/execution.css")
    async def execution_css():
        """返回运行编排样式表。"""
        return FileResponse(STATIC_DIR / "execution.css", headers=_NO_CACHE)

    @app.get("/execution.js")
    async def execution_js():
        """返回运行编排前端逻辑。"""
        return FileResponse(STATIC_DIR / "execution.js", headers=_NO_CACHE)

    @app.get("/model-providers.css")
    async def model_providers_css():
        """返回模型管理样式。"""
        return FileResponse(STATIC_DIR / "model-providers.css", headers=_NO_CACHE)

    @app.get("/model-providers.js")
    async def model_providers_js():
        """返回模型管理前端逻辑。"""
        return FileResponse(STATIC_DIR / "model-providers.js", headers=_NO_CACHE)

    return app


app = create_app()
