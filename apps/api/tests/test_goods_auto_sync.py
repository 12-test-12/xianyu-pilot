"""商品自动同步接口（POST /api/item/autoSync）的行为测试。

覆盖用户真实问题：进入商品页时应能自动拿到平台最新商品，且并发/重复触发
不能把平台接口打爆。这里用桌面端真实的 SQLite 库 + 打桩 sync_goods_for_account，
断言节流、复用、返回结构与列表同步状态。
"""
import datetime
import re
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.desktop_app import create_desktop_app

ACCOUNT_ID = 11


@pytest.fixture
def console(tmp_path, monkeypatch):
    from app.core import paths

    monkeypatch.setattr(paths, "SOURCE_ROOT", tmp_path)
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    original = Path(__file__).resolve().parents[2] / "web/index.html"
    (web / "index.html").write_bytes(original.read_bytes())
    (web / "assets/module.js").write_text("export {}", encoding="utf-8")
    (web / "xya/brand").mkdir(parents=True)
    (web / "xya/brand/icon.png").write_bytes(b"fixture image")
    config = Settings(runtime_mode="desktop")
    app = create_desktop_app(config, web_dir=web)
    with TestClient(app, base_url="http://127.0.0.1:15177") as client:
        html = client.get("/")
        marker = re.search(r'name="xianyu-desktop-bootstrap" content="([^"]+)"', html.text)[1]
        session = client.post("/api/desktop/session", json={}, headers={"X-Desktop-Bootstrap": marker})
        client.headers["Authorization"] = "Bearer " + session.json()["data"]["token"]
        yield client, config, app


@pytest.fixture
def sync_calls(monkeypatch):
    """打桩 sync_goods_for_account，只记录调用，不真的访问闲鱼。"""
    calls = []

    async def fake_sync(account_id, cookie_str, sync_id, db_session_factory=None, async_fetch_detail=True):
        calls.append({"account_id": account_id, "sync_id": sync_id})
        return {"sync_id": sync_id, "total": 0, "new": 0, "updated": 0}

    from app.services import xianyu_goods_sync

    monkeypatch.setattr(xianyu_goods_sync, "sync_goods_for_account", fake_sync)
    return calls


def _seed_account(config, *, with_auth=True):
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute(
            "INSERT INTO xianyu_account (id, external_uid, nickname, deleted, status)"
            " VALUES (?, 'uid-11', '测试账号', 0, 1)",
            (ACCOUNT_ID,),
        )
        if with_auth:
            db.execute(
                "INSERT INTO xianyu_account_auth (id, account_id, encrypted_cookie, deleted)"
                " VALUES (1, ?, '_m_h5_tk=abc_123', 0)",
                (ACCOUNT_ID,),
            )
        db.commit()


def _seed_completed_task(config, *, finished_at):
    """插入一条已完成任务，模拟"上次成功同步时间"。"""
    stamp = finished_at.strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute(
            "INSERT INTO xianyu_goods_sync_task"
            " (id, sync_id, account_id, status, progress, total_count, new_count, updated_count,"
            " skipped_count, off_shelf_count, detail_synced_count, duration_seconds,"
            " started_time, finished_time, deleted, created_time, updated_time)"
            " VALUES (1, 'old-sync-1', ?, 'completed', 100, 10, 2, 3, 0, 1, 10, 1.5, ?, ?, 0, ?, ?)",
            (ACCOUNT_ID, stamp, stamp, stamp, stamp),
        )
        db.commit()


def _seed_running_task(config, *, status="queued"):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute(
            "INSERT INTO xianyu_goods_sync_task"
            " (id, sync_id, account_id, status, progress, deleted, started_time, created_time, updated_time)"
            " VALUES (2, 'running-sync-1', ?, ?, 0, 0, ?, ?, ?)",
            (ACCOUNT_ID, status, now, now, now),
        )
        db.commit()


def _auto_sync(client, payload=None):
    response = client.post("/api/item/autoSync", json=payload or {})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 200, body
    return body["data"]


def test_auto_sync_returns_expected_shape_and_starts_sync(console, sync_calls):
    client, config, _ = console
    _seed_account(config)

    data = _auto_sync(client, {"xianyuAccountId": ACCOUNT_ID})

    assert set(data) >= {
        "started",
        "syncing",
        "status",
        "lastSyncTime",
        "syncId",
        "syncIds",
        "intervalSeconds",
        "message",
    }
    assert data["started"] is True
    assert data["syncing"] is True
    assert data["status"] == "started"
    assert data["lastSyncTime"] is None
    assert data["intervalSeconds"] == 60
    assert data["syncId"] == data["syncIds"][0]

    # 后台任务确实被启动，且任务行已落库（供列表/进度接口读取）
    deadline = time.time() + 5
    while time.time() < deadline and not sync_calls:
        time.sleep(0.05)
    assert [call["account_id"] for call in sync_calls] == [ACCOUNT_ID]
    with sqlite3.connect(config.sqlite_path) as db:
        rows = db.execute(
            "SELECT status FROM xianyu_goods_sync_task WHERE account_id = ?", (ACCOUNT_ID,)
        ).fetchall()
    assert rows and rows[0][0] in ("queued", "running", "completed")


def test_auto_sync_skips_within_threshold(console, sync_calls):
    client, config, _ = console
    _seed_account(config)
    _seed_completed_task(config, finished_at=datetime.datetime.now())

    data = _auto_sync(client, {"xianyuAccountId": ACCOUNT_ID})

    assert data["started"] is False
    assert data["status"] == "fresh"
    assert data["lastSyncTime"] is not None
    time.sleep(0.2)
    assert sync_calls == [], "阈值内不应重复触发平台同步"


def test_auto_sync_triggers_after_threshold(console, sync_calls):
    client, config, _ = console
    _seed_account(config)
    _seed_completed_task(config, finished_at=datetime.datetime.now() - datetime.timedelta(seconds=120))

    data = _auto_sync(client, {"xianyuAccountId": ACCOUNT_ID})

    assert data["started"] is True
    assert data["status"] == "started"
    assert data["lastSyncTime"] is not None
    deadline = time.time() + 5
    while time.time() < deadline and not sync_calls:
        time.sleep(0.05)
    assert len(sync_calls) == 1


def test_auto_sync_reuses_running_task_instead_of_duplicating(console, sync_calls):
    client, config, _ = console
    _seed_account(config)
    _seed_running_task(config, status="running")

    data = _auto_sync(client, {"xianyuAccountId": ACCOUNT_ID})

    assert data["started"] is False
    assert data["syncing"] is True
    assert data["status"] == "syncing"
    time.sleep(0.2)
    assert sync_calls == []
    with sqlite3.connect(config.sqlite_path) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM xianyu_goods_sync_task WHERE account_id = ?", (ACCOUNT_ID,)
        ).fetchone()[0]
    assert count == 1, "已有同步在跑时不应再插入新任务"


def test_auto_sync_concurrent_calls_start_only_one_sync(console, sync_calls):
    client, config, _ = console
    _seed_account(config)

    first = _auto_sync(client, {"xianyuAccountId": ACCOUNT_ID})
    second = _auto_sync(client, {"xianyuAccountId": ACCOUNT_ID})

    assert first["started"] is True
    assert second["started"] is False
    assert second["status"] == "syncing"
    time.sleep(0.2)
    assert len(sync_calls) == 1, "重复点击/并发调用只能启动一次同步"
    with sqlite3.connect(config.sqlite_path) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM xianyu_goods_sync_task WHERE account_id = ?", (ACCOUNT_ID,)
        ).fetchone()[0]
    assert count == 1


def test_auto_sync_without_login_cookie_does_not_start(console, sync_calls):
    client, config, _ = console
    _seed_account(config, with_auth=False)

    data = _auto_sync(client, {"xianyuAccountId": ACCOUNT_ID})

    assert data["started"] is False
    assert data["status"] == "no_account"
    time.sleep(0.2)
    assert sync_calls == []


def test_goods_list_carries_sync_state_and_last_sync_time(console, sync_calls):
    client, config, _ = console
    _seed_account(config)
    _seed_completed_task(config, finished_at=datetime.datetime.now())

    response = client.get("/api/goods")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 200, body
    data = body["data"]
    assert "records" in data
    assert "syncState" in data
    assert "lastSyncTime" in data
    assert data["syncState"] == "idle"
    assert data["lastSyncTime"] is not None

    # 有排队/运行中的同步时，列表应反映 syncing 状态
    _seed_running_task(config, status="running")
    response = client.get("/api/goods")
    assert response.json()["data"]["syncState"] == "syncing"


@pytest.mark.parametrize("platform_updated", [True, False])
def test_fish_shop_edit_only_saves_platform_confirmed_changes(console, monkeypatch, platform_updated):
    from app.api.v1.routes import fish_shop
    from app.core.database import use_database_runtime
    from app.services import xianyu_goods_sync as sync

    client, config, app = console
    _seed_account(config)
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("UPDATE xianyu_account SET fish_shop_user = 1 WHERE id = ?", (ACCOUNT_ID,))
        db.executemany(
            "INSERT INTO xianyu_goods"
            " (id, account_id, external_goods_id, title, stock, quantity, deleted, auto_relist_enabled, has_snapshot)"
            " VALUES (?, ?, ?, '旧标题', 5, 5, 0, 0, 0)",
            [(1, ACCOUNT_ID, "101"), (2, ACCOUNT_ID, "102")],
        )

    images = ["https://example.com/new-cover.jpg", "https://example.com/new-detail.jpg"]
    category = dict(catId="91000001", catName="测试叶子分类", channelCatId="92000001", tbCatId="93000001")
    submissions = []
    readbacks = []

    def edit_remote(cookie, api, version, item, *, is_edit):
        assert is_edit and item["itemId"] == "101"
        assert item["itemSkuList"][0]["skuId"] == "301"
        assert item["itemSkuList"][0]["inventoryId"] == "401"
        submissions.append(item)
        return {"data": {"itemId": "101"}}

    def read_remote(cookie, item_id):
        assert item_id == "101"
        readbacks.append(item_id)
        item = submissions[0]
        if not platform_updated:
            item = {**item, "itemTextDTO": {"title": "旧标题", "desc": "旧描述"},
                    "itemSkuList": [{**item["itemSkuList"][0], "quantity": 5}]}
        return {"data": item}

    monkeypatch.setattr(sync.XianyuItemPublisher, "upload_images_to_xianyu", lambda *_: images)
    monkeypatch.setattr(sync.XianyuItemPublisher, "resolve_category_for_publish", lambda *_: category)
    monkeypatch.setattr(fish_shop, "call_fish_shop_api", edit_remote)
    monkeypatch.setattr(fish_shop, "call_fish_shop_edit_detail", read_remote)
    edit = client.post("/api/fish-shop/edit", json={
        "xianyuAccountId": ACCOUNT_ID, "itemId": "101", "title": "新标题", "description": "新描述",
        "imageUrls": ["https://example.com/input.jpg"], "shippingMode": "none",
        "location": dict(prov="北京市", city="北京市", area="东城区", divisionId="110101", gps="116.4,39.9", poiName="东城区"),
        "itemProperties": [{"propertyName": "颜色", "propertyValues": [{"propertyValue": "红色"}]}],
        "itemSkuList": [{"price": "12.50", "quantity": 0, "skuId": "301", "inventoryId": "401",
                         "propertyList": [{"propertyText": "颜色", "valueText": "红色"}]}],
    }).json()
    assert len(submissions) == 1
    if not platform_updated:
        assert edit["code"] == 409, edit
        assert "标题、描述、规格、价格或库存" in edit["msg"]
        assert readbacks == ["101", "101"]
        item = client.get("/api/goods/1").json()["data"]
        assert item["title"] == "旧标题"
        assert item["stock"] == 5
        with sqlite3.connect(config.sqlite_path) as db:
            assert db.execute("SELECT COUNT(*) FROM xianyu_goods_edit_snapshot").fetchone()[0] == 0
        return
    assert edit["code"] == 200, edit
    assert readbacks == ["101"]

    def assert_edited_fields():
        item = client.get("/api/goods/1").json()["data"]
        assert item["title"] == "新标题"
        assert item["description"] == item["detailInfo"] == "新描述"
        assert item["imageUrls"] == images
        assert item["coverPic"] == images[0]
        assert item["soldPrice"] == "12.50"
        assert item["stock"] == 0
        return item

    assert_edited_fields()
    stale = {"id": "101", "title": "旧标题", "price": "5.00", "quantity": 5, "desc": "旧描述",
             "coverPic": "https://example.com/old.jpg", "viewCount": 8}
    other = {"id": "102", "title": "正常同步"}
    cards = [stale, other]
    monkeypatch.setattr(sync, "_refresh_m_h5_tk", lambda cookie: cookie)
    monkeypatch.setattr(sync, "fetch_goods_list", lambda _: cards)
    monkeypatch.setattr(sync, "fetch_item_detail", lambda *_: {"itemDO": {"desc": "旧详情", "quantity": 5, "viewCount": 9}})

    async def sync_goods(sync_id, detail=False):
        with use_database_runtime(app.state.database):
            await sync.sync_goods_for_account(ACCOUNT_ID, "fixture", sync_id, None, async_fetch_detail=False)
            if detail:
                await sync._async_fetch_details("fixture", [stale], ACCOUNT_ID, sync_id)

    client.portal.call(sync_goods, "stale-after-edit", True)
    assert assert_edited_fields()["viewCount"] == 9
    assert client.get("/api/goods/2").json()["data"]["title"] == "正常同步"

    cards[:] = [other]
    client.portal.call(sync_goods, "missing-after-edit")
    assert_edited_fields()

    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("UPDATE xianyu_goods_edit_snapshot SET created_time = datetime('now', '-2 minutes')")
    cards[:] = [{"id": "101", "title": "平台上的后续修改"}, other]
    client.portal.call(sync_goods, "fresh-after-edit")
    item = client.get("/api/goods/1").json()["data"]
    assert item["title"] == "平台上的后续修改"
    assert item["stock"] == 0


def test_update_synced_goods_handles_empty_and_unsafe_updates_gracefully(console):
    import time
    from app.core.database import use_database_runtime, async_session
    from app.models.entities import XianyuGoods, XianyuGoodsEditSnapshot
    from app.services import xianyu_goods_sync as sync

    client, config, app = console
    _seed_account(config)
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute(
            "INSERT INTO xianyu_goods (id, account_id, external_goods_id, title, stock, quantity, deleted, auto_relist_enabled, has_snapshot)"
            " VALUES (99, ?, '999', '本地编辑标题', 1, 1, 0, 0, 1)",
            (ACCOUNT_ID,),
        )
        db.execute(
            "INSERT INTO xianyu_goods_edit_snapshot (id, account_id, external_goods_id, source, account_type, snapshot_json, deleted, created_time)"
            " VALUES (99, ?, '999', 'edit', 'fish_shop', '{}', 0, datetime('now'))",
            (ACCOUNT_ID,),
        )

    async def execute_updates():
        with use_database_runtime(app.state.database):
            async with async_session() as db:
                # 1. 传空 values：直接返回，不抛异常
                await sync._update_synced_goods(db, 99, {}, time.monotonic())
                # 2. 传无 safe_fields 的字典（仅 title）：因近期有编辑快照，跳过非安全字段，不产生空 UPDATE 语句
                await sync._update_synced_goods(db, 99, {"title": "尝试覆盖的旧标题"}, time.monotonic())
                await db.commit()

    client.portal.call(execute_updates)

    item = client.get("/api/goods/99").json()["data"]
    assert item["title"] == "本地编辑标题"


def test_fish_shop_detail_normalizes_image_urls_fallback(console, monkeypatch):
    from app.api.v1.routes import fish_shop

    client, config, app = console
    _seed_account(config)

    # 模拟远程 editdetail 失败触发本地降级
    monkeypatch.setattr(fish_shop, "fetch_fish_shop_edit_detail", lambda *args, **kwargs: None)

    with sqlite3.connect(config.sqlite_path) as db:
        db.execute("UPDATE xianyu_account SET fish_shop_user = 1 WHERE id = ?", (ACCOUNT_ID,))
        # 1. image_urls 存储 JSON 列表
        db.execute(
            "INSERT INTO xianyu_goods (id, account_id, external_goods_id, title, image_urls, stock, quantity, deleted, auto_relist_enabled, has_snapshot)"
            " VALUES (101, ?, 'ext-101', '商品101', '[\"https://example.com/p1.jpg\", \"https://example.com/p2.jpg\"]', 1, 1, 0, 0, 0)",
            (ACCOUNT_ID,),
        )
        # 2. image_urls 为空，image_url 存逗号分隔并带空白的字符串
        db.execute(
            "INSERT INTO xianyu_goods (id, account_id, external_goods_id, title, image_url, stock, quantity, deleted, auto_relist_enabled, has_snapshot)"
            " VALUES (102, ?, 'ext-102', '商品102', 'https://example.com/c1.jpg,  https://example.com/c2.jpg ', 1, 1, 0, 0, 0)",
            (ACCOUNT_ID,),
        )
        # 3. 仅有 cover_pic 兜底
        db.execute(
            "INSERT INTO xianyu_goods (id, account_id, external_goods_id, title, cover_pic, stock, quantity, deleted, auto_relist_enabled, has_snapshot)"
            " VALUES (103, ?, 'ext-103', '商品103', 'https://example.com/cover.jpg', 1, 1, 0, 0, 0)",
            (ACCOUNT_ID,),
        )

    res101 = client.post("/api/fish-shop/detail", json={"xianyuAccountId": ACCOUNT_ID, "itemId": "ext-101"}).json()
    assert res101["code"] == 200
    assert res101["data"]["imageUrls"] == ["https://example.com/p1.jpg", "https://example.com/p2.jpg"]

    res102 = client.post("/api/fish-shop/detail", json={"xianyuAccountId": ACCOUNT_ID, "itemId": "ext-102"}).json()
    assert res102["code"] == 200
    assert res102["data"]["imageUrls"] == ["https://example.com/c1.jpg", "https://example.com/c2.jpg"]

    res103 = client.post("/api/fish-shop/detail", json={"xianyuAccountId": ACCOUNT_ID, "itemId": "ext-103"}).json()
    assert res103["code"] == 200
    assert res103["data"]["imageUrls"] == ["https://example.com/cover.jpg"]
