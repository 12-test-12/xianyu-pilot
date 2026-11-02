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
