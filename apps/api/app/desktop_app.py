"""Desktop startup foundation using the original API's storage and model schema.

No platform clients, server migration runner, Redis or automatic send loops are
loaded here. Original business routes are enabled only as they are adapted.
"""
import asyncio
import logging
import sqlite3
import secrets
from contextlib import nullcontext
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse,FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import settings
from app.core.database import DatabaseRuntime, use_database_runtime
from app.core.instance_lock import SingleInstance
from app.core.response import ResultObject
from app.desktop_storage import DesktopStore
from app.desktop_inventory_api import router as inventory_router
from app.desktop_delivery_api import router as delivery_router
from app.services.desktop_delivery import DesktopDeliveryStore
from app.services.desktop_inventory import InventoryError
from app.desktop_safety_api import router as safety_router

logger = logging.getLogger(__name__)


def create_desktop_app(config=None, *, web_dir=None, platform_runtime=None, instance_lock=None, host_gate=None):
    config = config or settings
    if not config.is_desktop:
        raise ValueError("桌面应用需要显式选择 desktop 模式")
    if instance_lock is not None and (instance_lock.file is None or instance_lock.path.parent!=config.desktop_data_path):
        raise ValueError("桌面宿主必须已持有同一 data 目录的实例锁")
    runtime = DatabaseRuntime(config)
    from app.desktop_console import ConsoleServices
    from app.services.delivery_gate import DeliveryGate
    runtime.delivery_gate=host_gate if host_gate is not None else DeliveryGate()
    console_services=ConsoleServices(runtime.delivery_gate) if platform_runtime is None else None
    store = DesktopStore(config.sqlite_path)
    web_dir = Path(web_dir) if web_dir is not None else Path(__file__).resolve().parents[2] / "web" / "dist"
    origins = {f"http://127.0.0.1:{config.desktop_port}", f"http://localhost:{config.desktop_port}"}

    @asynccontextmanager
    async def lifespan(app):
        with use_database_runtime(runtime), nullcontext() if instance_lock is not None else SingleInstance(config.desktop_data_path):
            try:
                await asyncio.to_thread(store.initialize)
                from app.core.desktop_secrets import encryption_secret
                await asyncio.to_thread(encryption_secret)
                await asyncio.to_thread(DesktopDeliveryStore(config.sqlite_path).recover_interrupted)
                async with runtime.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                if platform_runtime is not None:
                    await platform_runtime.start()
                elif console_services is not None:
                    await console_services.start()
                app.state.ready = True
                yield
            finally:
                app.state.ready = False
                if platform_runtime is not None:
                    await platform_runtime.stop()
                elif console_services is not None:
                    await console_services.stop()
                await runtime.dispose()

    app = FastAPI(title="闲鱼助手 · 个人桌面端", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ready = False
    app.state.desktop_stopping = False
    app.state.database = runtime
    app.state.desktop_store = store
    app.state.platform_runtime=platform_runtime
    app.state.console_services=console_services
    app.state.safety_action_token=secrets.token_urlsafe(32)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if (origin and origin not in origins) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "只允许本机桌面工作区访问"}, status_code=403)
        with use_database_runtime(runtime):
            response = await call_next(request)
        if request.url.path.startswith(("/api/cards", "/api/auto-delivery/", "/api/orders","/api/desktop/safety")):
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
        lifecycle=await lifecycle_status()
        return {"mode": "desktop", "storage": "sqlite", "schema": schema,
                "phase": "original-web-console", "automaticDeliveryEnabled": lifecycle["state"]=="running",
                "deliveryLifecycle":lifecycle,
                "realPlatformConnections":bool(lifecycle.get('connectedCount',0) or (platform_runtime and any(c.is_connected for c in platform_runtime.clients.values()))), "businessRoutesEnabled": True,
                "enabledBusinessModules": ["accounts","goods","orders","messages","cards","delivery-rules","goods-config","ai-auto-reply","logs","orders-read","delivery-records-read"],
                "deliveryExecutionMode": "official-verification" if platform_runtime else "offline-tests-only",
                "externalServicesRequired": [], "uiBuilt": (web_dir / "index.html").is_file(),
                "safetyUiBuilt":(web_dir/"desktop-safety.html").is_file(),"safetyPage":"/desktop/safety"}

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

    async def lifecycle_status():
        if platform_runtime and hasattr(platform_runtime,"desktop_status"):
            return await platform_runtime.desktop_status()
        if console_services is not None:
            return await console_services.desktop_status()
        return {"state":"offline","pauseReasons":[],"accountCount":0}

    @app.get("/api/desktop/lifecycle")
    async def desktop_lifecycle():
        return ResultObject.success(await lifecycle_status())

    @app.get("/api/desktop/monitor-status")
    def monitor_status():
        from app.services.official_delivery_store import OfficialDeliveryStore
        with OfficialDeliveryStore(config.sqlite_path).connection() as conn:
            data=[]
            for r in conn.execute("SELECT * FROM delivery_monitor_state ORDER BY account_id"):
                counts=conn.execute("""SELECT COALESCE(SUM(r.workflow_state='stock_blocked'),0),COALESCE(SUM(r.workflow_state='needs_review'),0)
                    FROM delivery_record r JOIN xianyu_trade_order o ON o.id=r.order_id WHERE o.account_id=? AND r.desktop_managed=1""",(r["account_id"],)).fetchone()
                data.append({"accountId":r["account_id"],"state":r["state"],"reason":r["reason"],"updatedAt":r["updated_at"],
                    "stockBlockedCount":counts[0],"needsReviewCount":counts[1]})
            return ResultObject.success(data)

    app.include_router(inventory_router)
    app.include_router(delivery_router)
    app.include_router(safety_router)

    @app.get("/desktop/safety")
    async def safety_page():
        target=web_dir/"desktop-safety.html"
        if not target.is_file():
            return JSONResponse({"detail":"安全工作台尚未构建，请先构建 apps/web"},status_code=503)
        return FileResponse(target,headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

    if (web_dir/"assets").is_dir():
        app.mount("/assets",StaticFiles(directory=web_dir/"assets"),name="desktop-ui-assets")

    from app.desktop_console import register_console
    register_console(app,config,runtime,web_dir)

    return app
