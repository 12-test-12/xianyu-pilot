"""订单同步与批量刷新测试：远程同步触发、错误透出、VO 字段、已发货订单落库。"""
from pathlib import Path
import socket
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import Settings
from app.core.database import DatabaseRuntime, use_database_runtime
from app.desktop_storage import DesktopStore
from app.models.entities import XianyuTradeOrder, XianyuTradeOrderItem
from app.schemas.order import OrderVO
from app.services import xianyu_order_sync as order_sync


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network is forbidden in order sync tests")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """真实 SQLite 库（执行全量 desktop 迁移），并把 SOURCE_ROOT 指向临时程序目录。"""
    from app.core import paths

    program_root = tmp_path / "program"
    data_dir = program_root / "data"
    data_dir.mkdir(parents=True)
    path = data_dir / "app.sqlite3"
    DesktopStore(path).initialize()
    monkeypatch.setattr(paths, "SOURCE_ROOT", program_root)
    return path


@pytest.fixture
def runtime(db_path):
    """数据库运行时。

    注意：use_database_runtime 依赖 ContextVar，必须在测试体内进入，
    否则在 fixture 中设置的值不会传递到测试任务（每个 task 独立上下文）。
    """
    return DatabaseRuntime(Settings(runtime_mode="desktop"))


def seed_account(path, account_id=1, status=1):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO xianyu_account(id,nickname,status,deleted) VALUES(?,?,?,0)",
            (account_id, f"acct-{account_id}", status),
        )
        conn.commit()


def remote_order(
    order_id="remote-order-1",
    status_text="已发货",
    item_id="goods-1",
    title="远程商品标题",
    image="https://example.invalid/a.jpg",
    quantity=2,
    delivery_time="2026-01-02 03:04:05",
):
    return {
        "commonData": {
            "orderId": order_id,
            "orderStatus": status_text,
            "itemId": item_id,
            "itemTitle": title,
            "itemMainPic": image,
            "deliveryTime": delivery_time,
            "buyerMessage": "请尽快发货",
        },
        "buyerInfoVO": {"userNick": "买家甲", "buyerId": "buyer-1"},
        "priceVO": {"totalPrice": "19.90", "auctionPrice": "9.95", "buyNum": quantity},
        "itemInfoVO": {},
    }


def test_seller_order_permission_error_reaches_the_caller(monkeypatch):
    from app.services import xianyu_api_service as api

    monkeypatch.setattr(api, "_get_account_auth", lambda _: {"encrypted_cookie": "fixture"})
    monkeypatch.setattr(api, "_post_mtop_with_token_retry", lambda *args: {
        "success": False, "ret": ["PERMISSION_EXCEPTION::无权限访问"],
    })
    result = api.fetch_sold_orders_page(1)
    assert result["success"] is False
    assert result["errorCode"] == "ORDER_PERMISSION_DENIED"
    assert "卖家工作台" in result["error"]


def patch_page(monkeypatch, pages):
    """把 fetch_sold_orders_page 打桩成分页数据；pages 为 {page_number: [orders]}。"""
    calls = []

    def fake_fetch(account_id, page_number=1, page_size=30, **kwargs):
        calls.append((account_id, page_number))
        items = pages.get(page_number)
        if items is None:
            return {"success": True, "data": {"items": [], "nextPage": False, "totalCount": 0}}
        return {
            "success": True,
            "data": {
                "items": list(items),
                "nextPage": page_number < max(pages),
                "totalCount": sum(len(value) for value in pages.values()),
            },
        }

    monkeypatch.setattr(order_sync, "fetch_sold_orders_page", fake_fetch)
    return calls


@pytest.mark.asyncio
async def test_short_page_continues_and_later_failure_reports_committed_orders(runtime, db_path, monkeypatch):
    seed_account(db_path)
    order = remote_order()
    order["priceVO"]["realPayPrice"] = "12.50"

    def fetch(account_id, page_number, page_size):
        if page_number == 1:
            return {"success": True, "data": {"items": [order], "nextPage": True}}
        return {"success": False, "error": "平台超时", "errorCode": "PLATFORM_TIMEOUT"}

    monkeypatch.setattr(order_sync, "fetch_sold_orders_page", fetch)
    with use_database_runtime(runtime):
        result = await order_sync.sync_orders_for_account(1)
        assert not result["success"] and result["partial"] and result["total"] == 1
        assert result["errorCode"] == "PLATFORM_TIMEOUT" and "第 2 页" in result["error"]
        order["priceVO"] = {"buyNum": 2}
        assert (await order_sync.upsert_remote_order(1, order))["success"]
        await runtime.dispose()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT total_amount FROM xianyu_trade_order").fetchone() == ("12.50",)


def test_order_amount_distinguishes_unit_cents_zero_and_unknown():
    assert order_sync._parse_order_amount(quantity=2, common={"priceCent": 500}) == "10.00"
    assert order_sync._parse_order_amount("100", price_vo={"realPayCent": 8000}) == "80.00"
    assert order_sync._parse_order_amount("100", price_vo={"realPayPrice": 0}) == "0.00"
    assert order_sync._parse_order_amount("Infinity", unit_price="5", quantity=0) is None


def test_order_status_mapping_and_time_parsing():
    from datetime import datetime

    # Status mapping
    assert order_sync._map_order_status("TRADE_CLOSED_BY_TAOBAO") == 5
    assert order_sync._map_order_status("trade_finished") == 4
    assert order_sync._map_order_status("TRADE_SUCCESS") == 4
    assert order_sync._map_order_status("PAID") == 1
    assert order_sync._map_order_status(2) == 2
    assert order_sync._map_order_status("2") == 2
    assert order_sync._map_order_status("WAIT_BUYER_CONFIRM_GOODS", in_refund=True) == 6
    assert order_sync._map_order_status("UNKNOWN_STATUS") == 6

    # Order time parsing
    dt = datetime(2026, 1, 2, 3, 4, 5)
    assert order_sync._parse_order_time(dt) == dt
    assert order_sync._parse_order_time("2026-01-02 03:04:05") == dt
    assert order_sync._parse_order_time("2026-01-02T03:04:05") == dt
    assert order_sync._parse_order_time("2026-01-02T03:04:05Z") == dt
    # Millisecond timestamp
    ms = int(dt.timestamp() * 1000)
    assert order_sync._parse_order_time(ms) == dt
    assert order_sync._parse_order_time(str(ms)) == dt
    assert order_sync._parse_order_time(None) is None
    assert order_sync._parse_order_time("") is None


@pytest.mark.asyncio
async def test_dashboard_counts_sales_on_payment_date(runtime, db_path):
    from datetime import date
    from app.api.v1.routes.dashboard import get_dashboard_summary

    seed_account(db_path)
    order = remote_order(status_text="UNKNOWN")
    order["commonData"]["createTime"] = "2026-01-01 12:00:00"
    unpaid = remote_order(order_id="unpaid", status_text="WAIT_BUYER_PAY")
    unpaid["commonData"]["createTime"] = "2026-01-02 03:00:00"
    refunding = remote_order(order_id="refunding", status_text="TRADE_FINISHED")
    refunding["commonData"].update(
        createTime="2026-01-01 12:00:00",
        paySuccessTime="2026-01-02 03:00:00",
        inRefund="true",
    )
    with use_database_runtime(runtime):
        assert (await order_sync.upsert_remote_order(1, order))["success"]
        order["commonData"].update(
            orderStatus="WAIT_BUYER_CONFIRM_GOODS", paySuccessTime="2026-01-02 01:00:00", inRefund="false"
        )
        assert (await order_sync.upsert_remote_order(1, order))["action"] == "updated"
        assert (await order_sync.upsert_remote_order(1, unpaid))["success"]
        assert (await order_sync.upsert_remote_order(1, refunding))["success"]
        async with runtime.session() as db:
            result = await get_dashboard_summary(date(2026, 1, 2), 1, 1, db, {})
        await runtime.dispose()

    assert result.data["todayOrderCount"] == 1
    assert result.data["todaySalesAmount"] == 19.90


@pytest.mark.asyncio
async def test_goods_sync_persists_progress_without_contending_with_item_writes(
    runtime, db_path, monkeypatch, caplog
):
    from app.services import xianyu_goods_sync as goods_sync

    seed_account(db_path)
    items = [
        {"id": str(index), "title": f"商品 {index}", "itemStatus": status}
        for index, status in enumerate((0, 1, "2"), start=1)
    ]
    monkeypatch.setattr(goods_sync, "_refresh_m_h5_tk", lambda cookie: cookie)
    monkeypatch.setattr(goods_sync, "fetch_goods_list", lambda cookie: items)
    with use_database_runtime(runtime):
        result = await goods_sync.sync_goods_for_account(1, "unb=test", "test-goods-sync", None, False)
        await runtime.dispose()

    assert result["total"] == 3
    assert "同步任务状态落库失败" not in caplog.text
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT status FROM xianyu_goods ORDER BY external_goods_id").fetchall() == [
            (1,), (0,), (2,),
        ]


def patch_failure(monkeypatch, error="账号登录已失效，请重新登录后同步订单", code="COOKIE_EXPIRED"):
    def fake_fetch(account_id, page_number=1, page_size=30, **kwargs):
        return {"success": False, "error": error, "errorCode": code}

    monkeypatch.setattr(order_sync, "fetch_sold_orders_page", fake_fetch)


async def read_orders(runtime):
    from sqlalchemy import select

    async with runtime.session() as session:
        orders = (
            await session.execute(
                select(XianyuTradeOrder).where(XianyuTradeOrder.deleted == 0)
            )
        ).scalars().all()
        items = (
            await session.execute(
                select(XianyuTradeOrderItem).where(XianyuTradeOrderItem.deleted == 0)
            )
        ).scalars().all()
    return orders, items


@pytest.mark.asyncio
async def test_batch_refresh_triggers_remote_sync_and_persists_shipped_order(runtime, db_path, monkeypatch):
    """已发货(status=3)订单即使缺少 goods 记录也要落库，且 batchRefresh 触发远程同步。"""
    from app.api.v1.routes import order as order_routes

    seed_account(db_path)
    calls = patch_page(monkeypatch, {1: [remote_order()]})

    with use_database_runtime(runtime):
        try:
            async with runtime.session() as session:
                response = await order_routes.batch_refresh_orders(
                    data={"xianyuAccountId": 1}, db=session, current_user={"user_id": 1}
                )
            orders, items = await read_orders(runtime)
        finally:
            await runtime.dispose()

    payload = response.data
    assert calls and calls[0][0] == 1, "batchRefresh 必须触发远程同步"
    assert response.code == 200
    assert payload["refreshed_count"] == 1
    assert payload["refreshedCount"] == 1
    assert payload["records"][0]["externalOrderId"] == "remote-order-1"
    assert payload["syncErrors"] == []

    assert len(orders) == 1
    assert int(orders[0].order_status) == 3, "已发货订单状态必须正确落库"
    assert orders[0].ship_time is not None
    assert len(items) == 1, "缺少商品记录也不能丢弃订单项"
    assert items[0].goods_title == "远程商品标题"


@pytest.mark.asyncio
async def test_batch_refresh_reports_sync_errors_without_raising(runtime, db_path, monkeypatch):
    """远程同步失败不抛异常，错误原因放进 syncErrors，仍返回本地记录。"""
    from app.api.v1.routes import order as order_routes

    seed_account(db_path)
    patch_failure(monkeypatch)

    with use_database_runtime(runtime):
        try:
            async with runtime.session() as session:
                response = await order_routes.batch_refresh_orders(
                    data={"xianyuAccountId": 1}, db=session, current_user={"user_id": 1}
                )
        finally:
            await runtime.dispose()

    payload = response.data
    assert response.code == 200
    assert payload["refreshed_count"] == 0
    assert payload["syncErrors"], "同步失败必须透出错误原因"
    assert payload["syncErrors"][0]["accountId"] == 1
    assert payload["syncErrors"][0]["errorCode"] == "COOKIE_EXPIRED"
    assert "登录已失效" in payload["syncErrors"][0]["error"]


@pytest.mark.asyncio
async def test_batch_refresh_syncs_all_enabled_accounts_when_unspecified(runtime, db_path, monkeypatch):
    from app.api.v1.routes import order as order_routes

    seed_account(db_path, 1, 1)
    seed_account(db_path, 2, 1)
    seed_account(db_path, 3, 0)  # 已禁用，不应同步
    calls = patch_page(monkeypatch, {1: [remote_order("remote-order-1")]})

    with use_database_runtime(runtime):
        try:
            async with runtime.session() as session:
                response = await order_routes.batch_refresh_orders(
                    data={}, db=session, current_user={"user_id": 1}
                )
        finally:
            await runtime.dispose()

    synced = {account_id for account_id, _ in calls}
    assert synced == {1, 2}, "未指定账号时应同步全部启用账号"
    assert set(response.data["syncedAccounts"]) == {1, 2}


@pytest.mark.asyncio
async def test_sync_is_idempotent_and_updates_shipped_status(runtime, db_path, monkeypatch):
    seed_account(db_path)
    with use_database_runtime(runtime):
        try:
            patch_page(monkeypatch, {1: [remote_order(status_text="已付款")]})
            first = await order_sync.sync_orders_for_account(1)
            assert first["success"] and first["inserted"] == 1

            patch_page(monkeypatch, {1: [remote_order(status_text="已发货")]})
            second = await order_sync.sync_orders_for_account(1)
            assert second["success"] and second["updated"] == 1
            orders, items = await read_orders(runtime)
        finally:
            await runtime.dispose()

    assert len(orders) == 1, "重复同步不能产生重复订单"
    assert int(orders[0].order_status) == 3
    assert len(items) == 1, "重复同步不能产生重复订单项"


@pytest.mark.asyncio
async def test_upsert_remote_order_single_order_backfill(runtime, db_path):
    """WS 事件可复用的单笔落库函数。"""
    seed_account(db_path)
    with use_database_runtime(runtime):
        try:
            result = await order_sync.upsert_remote_order(1, remote_order("ws-order-1"))
            assert result["success"] is True
            assert result["action"] == "inserted"
            assert result["externalOrderId"] == "ws-order-1"

            again = await order_sync.upsert_remote_order(1, remote_order("ws-order-1"))
            assert again["success"] is True
            assert again["action"] == "updated"
            orders, _ = await read_orders(runtime)
        finally:
            await runtime.dispose()

    assert len(orders) == 1


@pytest.mark.asyncio
async def test_sync_order_by_external_id_finds_single_order(runtime, db_path, monkeypatch):
    seed_account(db_path)
    patch_page(monkeypatch, {1: [remote_order("other-order"), remote_order("target-order")]})
    with use_database_runtime(runtime):
        try:
            result = await order_sync.sync_order_by_external_id(1, "target-order")
            orders, _ = await read_orders(runtime)
        finally:
            await runtime.dispose()

    assert result["success"] is True and result["found"] is True
    assert [order.external_order_id for order in orders] == ["target-order"]


def test_batch_refresh_route_is_registered_and_not_retired():
    """batchRefresh 必须挂到 /api 路由上，且不再被 retired 410 拦截。"""
    from app.api.v1.api import api_router
    from app.core.route_registry import retired_surface_guidance

    def flatten(routes, prefix=""):
        """展开 FastAPI 0.139 的惰性 _IncludedRouter（其 path 为空）。"""
        for route in routes:
            original = getattr(route, "original_router", None)
            context = getattr(route, "include_context", None)
            if original is not None and context is not None:
                yield from flatten(original.routes, prefix + context.prefix)
            else:
                yield route, prefix + getattr(route, "path", "")

    registered = {
        path
        for route, path in flatten(api_router.routes)
        if "POST" in (getattr(route, "methods", set()) or set())
    }
    assert "/order/batchRefresh" in registered
    assert retired_surface_guidance("POST", "/api/order/batchRefresh") is None


def test_trade_order_to_vo_exposes_goods_and_shipping_fields():
    from app.api.v1.routes.order import trade_order_to_vo

    order = XianyuTradeOrder(
        id=7,
        account_id=1,
        external_order_id="order-7",
        order_status=3,
        total_amount="19.90",
        buyer_name="买家甲",
        buyer_id="buyer-1",
        ship_time=None,
        item_id="goods-1",
        is_bargain=0,
    )
    item = XianyuTradeOrderItem(
        id=1,
        order_id=7,
        goods_id=11,
        goods_title="商品标题",
        goods_image="https://example.invalid/a.jpg",
        goods_price="9.95",
        goods_count=2,
        quantity=2,
        deleted=0,
    )
    vo = trade_order_to_vo(
        order,
        item,
        {"externalGoodsId": "ext-11", "goodsImage": "https://example.invalid/b.jpg"},
    )

    assert isinstance(vo, OrderVO)
    assert vo.external_goods_id == "ext-11"
    assert vo.goods_title == "商品标题"
    assert vo.goods_image == "https://example.invalid/a.jpg"
    assert vo.quantity == 2
    assert vo.goods_count == 2
    assert vo.buyer_id == "buyer-1"

    dumped = vo.model_dump()
    assert dumped["externalGoodsId"] == "ext-11"
    assert dumped["goodsTitle"] == "商品标题"
    assert dumped["goodsImage"] == "https://example.invalid/a.jpg"
    assert dumped["buyerId"] == "buyer-1"
    assert "shipTime" in dumped
    assert "quantity" in dumped


def test_vo_without_item_keeps_backward_compatible_fields():
    from app.api.v1.routes.order import trade_order_to_vo

    order = XianyuTradeOrder(
        id=1,
        account_id=2,
        external_order_id="order-1",
        order_status=1,
        total_amount="5.00",
        buyer_name="买家乙",
        item_id=None,
        deleted=0,
    )
    dumped = trade_order_to_vo(order).model_dump()
    assert dumped["orderId"] == "order-1"
    assert dumped["xianyuAccountId"] == 2
    assert dumped["totalPrice"] == "5.00"
    assert dumped["goodsTitle"] is None
