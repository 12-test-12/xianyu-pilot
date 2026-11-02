"""业务操作日志（operation_log）落库与读取端契约测试。

覆盖：
* ``operation_log_service.record_operation`` / ``record_delivery_outcome`` 写入完整业务字段；
* 审计写入失败（表缺失、SQL 异常）不影响主业务流程；
* ``GET /api/operation-logs`` 返回 status/requestParams/responseResult/requiresReconciliation/durationMs；
* 老库缺列（只有 8 个旧列）时读取端不 500；
* 桌面迁移 007 的 SQL 可被 ``sqlite3.complete_statement`` 逐条执行。
"""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.routes import frontend_compat
from app.desktop_storage import DesktopStore
from app.services import operation_log_service as ops

MIGRATION_007 = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "desktop_migrations"
    / "007_operation_log_business.sql"
)

LEGACY_SCHEMA = """
CREATE TABLE operation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator VARCHAR(100),
    operation_type VARCHAR(100),
    operation_desc TEXT,
    target_type VARCHAR(100),
    target_id VARCHAR(100),
    ip_address VARCHAR(50),
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def _run(coro):
    return asyncio.run(coro)


def _engine(path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _desktop_db(tmp_path: Path) -> Path:
    path = tmp_path / "app.sqlite3"
    DesktopStore(path).initialize()
    return path


def _legacy_db(tmp_path: Path) -> Path:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO operation_log(operator,operation_type,operation_desc) "
            "VALUES(?,?,?)",
            (
                "本机管理员",
                "HTTP_MUTATION_STARTED",
                json.dumps({"requestId": "legacy-1"}),
            ),
        )
    return path


def _client(db_path: Path) -> TestClient:
    """最小 FastAPI 应用：只挂 frontend_compat 路由，覆写鉴权与数据库依赖。"""
    engine, factory = _engine(db_path)
    app = FastAPI()
    app.include_router(frontend_compat.router, prefix="/api")

    async def _db_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[frontend_compat.get_db] = _db_override
    app.dependency_overrides[frontend_compat.get_current_user] = lambda: {
        "id": 1,
        "username": "tester",
    }
    client = TestClient(app)
    client._operation_log_engine = engine  # noqa: SLF001 - 测试内释放连接池
    return client


def _close_client(client: TestClient) -> None:
    engine = getattr(client, "_operation_log_engine", None)
    if engine is not None:
        engine.sync_engine.dispose()


def test_record_delivery_failure_persists_all_business_fields(tmp_path):
    path = _desktop_db(tmp_path)
    engine, factory = _engine(path)

    async def scenario():
        async with factory() as db:
            record_id = await ops.record_delivery_outcome(
                db,
                order_id="order-9001",
                outcome_status="failed",
                item_id="item-88",
                buyer="买家甲",
                amount="12.50",
                attempt_id=7,
                delivery_mode="card",
                error_code="DELIVERY_CONTENT_MISSING",
                error_message="卡密库存不足",
                retry_safe=True,
                retry_scope="same_intent",
                operator="本机管理员",
                request_params={"orderId": "order-9001", "password": "secret"},
                duration_ms=321,
            )
            await db.commit()
            assert isinstance(record_id, int) and record_id > 0
        await engine.dispose()

    _run(scenario())

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT operation_type, operation_desc, target_type, target_id, status,"
            " request_params, response_result, requires_reconciliation, duration_ms"
            " FROM operation_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row[0] == ops.DELIVERY_FAILED
    assert "order-9001" in row[1] and "买家甲" in row[1] and "卡密库存不足" in row[1]
    assert row[2] == ops.TARGET_DELIVERY and row[3] == "order-9001"
    assert row[4] == ops.STATUS_FAILED
    assert "order-9001" in row[5] and "secret" not in row[5]
    response = json.loads(row[6])
    assert response["errorCode"] == "DELIVERY_CONTENT_MISSING"
    assert response["retrySafe"] is True
    assert row[7] == 1
    assert row[8] == 321


def test_record_delivery_outcome_maps_success_and_unknown(tmp_path):
    path = _desktop_db(tmp_path)
    engine, factory = _engine(path)

    async def scenario():
        async with factory() as db:
            await ops.record_delivery_outcome(
                db,
                order_id="order-1",
                outcome_status="succeeded",
                item_id="item-1",
                buyer="买家乙",
                amount=9.9,
                message_confirmed=True,
                platform_confirmed=True,
            )
            await ops.record_delivery_outcome(
                db,
                order_id="order-2",
                outcome_status="unknown",
                item_id="item-2",
                buyer="买家丙",
                error_code="SEND_TIMEOUT",
            )
            await db.commit()
        await engine.dispose()

    _run(scenario())

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT operation_type, status, requires_reconciliation FROM operation_log"
            " ORDER BY id ASC"
        ).fetchall()
    assert [row[0] for row in rows] == [
        ops.DELIVERY_SUCCEEDED,
        ops.DELIVERY_STARTED,
    ]
    assert rows[0][1] == ops.STATUS_COMPLETED and rows[0][2] == 0
    assert rows[1][1] == ops.STATUS_UNKNOWN and rows[1][2] == 1


def test_audit_write_failure_never_breaks_business_flow(tmp_path, monkeypatch):
    """表不存在 / INSERT 抛错时，业务代码必须照常继续。"""
    path = tmp_path / "empty.sqlite3"
    sqlite3.connect(path).close()
    engine, factory = _engine(path)
    business_state = {"continued": False}

    async def scenario():
        async with factory() as db:
            record_id = await ops.record_operation(
                db,
                operation_type=ops.DELIVERY_FAILED,
                description="自动发货失败：订单 order-1",
                target_type=ops.TARGET_DELIVERY,
                target_id="order-1",
            )
            assert record_id is None
            business_state["continued"] = True
        await engine.dispose()

    _run(scenario())
    assert business_state["continued"] is True

    def _boom(*args, **kwargs):
        raise RuntimeError("audit storage exploded")

    monkeypatch.setattr(ops, "_insert", _boom)
    engine, factory = _engine(_desktop_db(tmp_path))

    async def scenario_with_boom():
        async with factory() as db:
            record_id = await ops.record_delivery_started(
                db, order_id="order-2", item_id="item-2", buyer="买家丁"
            )
            assert record_id is None
            business_state["continued"] = True
        await engine.dispose()

    _run(scenario_with_boom())
    assert business_state["continued"] is True


def test_operation_logs_endpoint_returns_business_fields(tmp_path):
    path = _desktop_db(tmp_path)
    engine, factory = _engine(path)

    async def scenario():
        async with factory() as db:
            await ops.record_delivery_failed(
                db,
                order_id="order-777",
                item_id="item-777",
                buyer="买家戊",
                error_code="SHIP_FAILED",
                error_message="平台拒绝发货",
                request_params={"orderId": "order-777"},
                duration_ms=88,
            )
            await db.commit()
        await engine.dispose()

    _run(scenario())

    client = _client(path)
    try:
        with client:
            response = client.get("/api/operation-logs", params={"size": 5})
    finally:
        _close_client(client)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 200, payload
    data = payload["data"]
    record = data["records"][0]
    assert record["operationType"] == ops.DELIVERY_FAILED
    assert record["status"] == "执行失败"
    assert record["requiresReconciliation"] is True
    assert "order-777" in record["description"]
    assert "order-777" in (record["requestParams"] or "")
    assert json.loads(record["responseResult"])["errorCode"] == "SHIP_FAILED"
    assert record["durationMs"] == 88
    assert data["requiresReconciliationTotal"] >= 1


def test_operation_logs_endpoint_tolerates_legacy_schema(tmp_path):
    path = _legacy_db(tmp_path)
    client = _client(path)
    try:
        with client:
            response = client.get("/api/operation-logs", params={"size": 5})
            exported = client.get("/api/operation-logs/export")
    finally:
        _close_client(client)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 200, payload
    record = payload["data"]["records"][0]
    assert record["operationType"] == "HTTP_MUTATION_STARTED"
    assert record["status"] == "执行结果待核对"
    assert record["requiresReconciliation"] is True
    assert record["requestParams"] is None
    assert record["responseResult"] is None
    assert record["durationMs"] is None
    assert payload["data"]["requiresReconciliationTotal"] is None
    assert exported.status_code == 200, exported.text


def test_desktop_migration_007_is_executable_on_legacy_schema():
    sql = MIGRATION_007.read_text(encoding="utf-8")
    statements = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer.strip())
            buffer = ""
    assert buffer.strip() == "", "007 迁移存在未结束的 SQL 语句"
    assert len(statements) == 7, statements

    with sqlite3.connect(":memory:") as connection:
        connection.executescript(LEGACY_SCHEMA)
        for statement in statements:
            connection.execute(statement)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(operation_log)")
        }
        assert {
            "status",
            "request_params",
            "response_result",
            "requires_reconciliation",
            "duration_ms",
        } <= columns
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(operation_log)")
        }
        assert {"idx_operation_log_type_id", "idx_operation_log_reconciliation"} <= indexes
        connection.execute(
            "INSERT INTO operation_log(operator,operation_type,operation_desc) "
            "VALUES('本机管理员','fixture','老写入点仍然可用')"
        )
        assert connection.execute(
            "SELECT requires_reconciliation FROM operation_log"
        ).fetchone()[0] == 0
