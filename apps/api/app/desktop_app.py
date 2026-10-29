"""Desktop startup foundation using the original API's storage and model schema.

No platform clients, server migration runner, Redis or automatic send loops are
loaded here. Original business routes are enabled only as they are adapted.
"""
import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.database import DatabaseRuntime
from app.core.instance_lock import SingleInstance
from app.core.response import ResultObject
from app.desktop_storage import DesktopStore
from app.desktop_inventory_api import router as inventory_router
from app.desktop_delivery_api import router as delivery_router
from app.services.desktop_delivery import DesktopDeliveryStore
from app.services.desktop_inventory import InventoryError

logger = logging.getLogger(__name__)


def create_desktop_app(config=None, *, web_dir=None):
    config = config or settings
    if not config.is_desktop:
        raise ValueError("桌面应用需要显式选择 desktop 模式")
    runtime = DatabaseRuntime(config)
    store = DesktopStore(config.sqlite_path)
    web_dir = Path(web_dir) if web_dir is not None else Path(__file__).resolve().parents[2] / "web" / "dist"
    origins = {f"http://127.0.0.1:{config.desktop_port}", f"http://localhost:{config.desktop_port}"}

    @asynccontextmanager
    async def lifespan(app):
        with SingleInstance(config.desktop_data_path):
            try:
                await asyncio.to_thread(store.initialize)
                await asyncio.to_thread(DesktopDeliveryStore(config.sqlite_path).recover_interrupted)
                async with runtime.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                app.state.ready = True
                yield
            finally:
                app.state.ready = False
                await runtime.dispose()

    app = FastAPI(title="闲鱼助手 · 个人桌面端", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ready = False
    app.state.database = runtime
    app.state.desktop_store = store
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if (origin and origin not in origins) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "只允许本机桌面工作区访问"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith(("/api/cards", "/api/auto-delivery/", "/api/orders")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(InventoryError)
    async def inventory_error(request, exc):
        return JSONResponse(ResultObject.failed(str(exc), code=exc.status).model_dump(), status_code=exc.status)

    @app.exception_handler(sqlite3.Error)
    async def inventory_storage_error(request, exc):
        # Do not log bound card contents, SQL text or raw SQLite error messages.
        logger.error("Desktop inventory storage failed: %s", type(exc).__name__)
        return JSONResponse(ResultObject.failed("本地库存操作失败，事务已回滚，请检查数据库状态", code=503).model_dump(), status_code=503)

    @app.get("/health")
    @app.get("/health/live")
    async def live():
        return {"status": "ok", "mode": "desktop"}

    async def status():
        schema = await asyncio.to_thread(store.status)
        async with runtime.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"mode": "desktop", "storage": "sqlite", "schema": schema,
                "phase": "local-delivery-state", "automaticDeliveryEnabled": False,
                "realPlatformConnections": False, "businessRoutesEnabled": True,
                "enabledBusinessModules": ["cards", "delivery-rules", "orders-read", "delivery-records-read"],
                "deliveryExecutionMode": "offline-tests-only",
                "externalServicesRequired": [], "uiBuilt": (web_dir / "index.html").is_file()}

    @app.get("/health/ready")
    async def ready():
        if not app.state.ready:
            return JSONResponse({"status": "not_ready"}, status_code=503)
        try:
            current = await status()
            if not current["schema"]["current"]:
                return JSONResponse({"status": "not_ready"}, status_code=503)
            return {"status": "ready", **current}
        except Exception:
            return JSONResponse({"status": "not_ready", "reason": "desktop_storage_unavailable"}, status_code=503)

    @app.get("/api/desktop/status")
    async def desktop_status():
        return ResultObject.success(await status())

    app.include_router(inventory_router)
    app.include_router(delivery_router)

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def not_adapted(path: str):
        del path
        return JSONResponse(ResultObject(code=503, msg="原业务接口正在适配 SQLite，当前尚未启用",
            data={"reason": "desktop_feature_not_adapted", "retrySafe": False}).model_dump(by_alias=True), status_code=503)

    @app.get("/")
    async def index():
        return ResultObject.success(await status())

    return app
