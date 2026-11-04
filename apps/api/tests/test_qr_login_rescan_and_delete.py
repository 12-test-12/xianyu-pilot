"""Tests for QR login, rescan cookie recovery, and soft-delete/re-add consistency."""
from pathlib import Path
import re
import sqlite3
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.desktop_app import create_desktop_app
from app.core.xianyu_qr_login import (
    generate_qrcode,
    get_session_status,
    get_session_cookies,
    cleanup_all,
)
from app.core.cookie_crypto import encrypt_cookie_for_storage, decrypt_cookie_if_needed


class _FakeWorker:
    """替身浏览器会话：generate_qrcode 只依赖 start/wait_qr_ready/snapshot。"""

    def __init__(self, *, timeout=300):
        self.status = "new"
        self.qr_image = "data:image/png;base64,mock"
        self.cookies = None
        self.error = None
        self.cancelled = False

    def start(self):
        return self

    def cancel(self):
        self.cancelled = True

    def join(self, timeout=None):
        return None

    def snapshot(self):
        return {
            "status": self.status,
            "qr_image": self.qr_image,
            "cookies": self.cookies,
            "error": self.error,
        }

    def wait_qr_ready(self, timeout=None):
        return self.qr_image


@pytest.fixture
def console(tmp_path, monkeypatch):
    cleanup_all()
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
    cleanup_all()


def test_generate_qrcode_accepts_target_account_id():
    """Verify that generate_qrcode records target_account_id for rescan mode."""
    with patch("app.core.xianyu_qr_login._create_worker", _FakeWorker):
        result = generate_qrcode(
            user_id=1,
            owner_key="desktop-operator",
            target_account_id=99,
        )

    session_id = result["sessionId"]
    context = get_session_cookies(session_id)
    # Session cookies returns None before confirmation, but internal session_data holds target_account_id
    from app.core.xianyu_qr_login import _sessions
    assert _sessions[session_id]["target_account_id"] == 99


def test_rescan_updates_existing_account_credentials_and_recovers_cookie(console):
    """Test rescan flow: updating an existing account's cookie when it became expired."""
    client, config, app = console

    # 1. Seed existing account in DB with expired cookie status
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute(
            "INSERT INTO xianyu_account(id, external_uid, nickname, deleted, status) "
            "VALUES(11, 'fixture-unb-11', '测试卖家', 0, 1)"
        )
        db.execute(
            "INSERT INTO xianyu_account_auth(account_id, encrypted_cookie, cookie_status, "
            "last_login_status_code, last_login_status_message, deleted) "
            "VALUES(11, 'enc_old_cookie', 2, 'SESSION_EXPIRED', 'Cookie已过期', 0)"
        )
        db.execute(
            "INSERT INTO xianyu_account_runtime(account_id, cookie_status, "
            "last_login_status_code, last_login_status_message, deleted) "
            "VALUES(11, 2, 'SESSION_EXPIRED', 'Cookie已过期', 0)"
        )

    # 2. Call /api/qrlogin/generate with accountId=11 (rescan mode)
    with patch("app.core.xianyu_qr_login._create_worker", _FakeWorker):
        gen_resp = client.post("/api/qrlogin/generate", json={"accountId": 11})
        assert gen_resp.status_code == 200
        session_id = gen_resp.json()["data"]["sessionId"]

    # 3. Simulate QR scan confirmation
    from app.core.xianyu_qr_login import _sessions
    session_data = _sessions[session_id]
    session_data["saved_cookies"] = {
        "unb": "fixture-unb-11",
        "_m_h5_tk": "new_m_h5_tk_val",
        "cookie2": "new_cookie2_val",
    }
    session_data["terminal_result"] = {
        "status": "confirmed",
        "unb": "fixture-unb-11",
        "externalUid": "fixture-unb-11",
    }
    session_data["status"] = "confirmed"

    # 4. Poll status with accountId=11
    status_resp = client.post(f"/api/qrlogin/status/{session_id}", json={"accountId": 11})
    assert status_resp.status_code == 200
    data = status_resp.json()["data"]
    assert data["status"] == "confirmed"
    assert data["accountId"] == 11
    assert data["authUsable"] is True
    assert data["cookieStatus"] == 1
    assert data["loginStatusCode"] == "OK"
    assert "Cookie 已更新" in data["message"]

    # 5. Verify database was updated
    with sqlite3.connect(config.sqlite_path) as db:
        auth_row = db.execute(
            "SELECT cookie_status, last_login_status_code, deleted, encrypted_cookie "
            "FROM xianyu_account_auth WHERE account_id=11"
        ).fetchone()
        assert auth_row[0] == 1
        assert auth_row[1] == "OK"
        assert auth_row[2] == 0
        decrypted = decrypt_cookie_if_needed(auth_row[3])
        assert "unb=fixture-unb-11" in decrypted
        assert "_m_h5_tk=new_m_h5_tk_val" in decrypted

        runtime_row = db.execute(
            "SELECT cookie_status, last_login_status_code, deleted "
            "FROM xianyu_account_runtime WHERE account_id=11"
        ).fetchone()
        assert runtime_row[0] == 1
        assert runtime_row[1] == "OK"
        assert runtime_row[2] == 0


def test_delete_account_soft_deletes_and_rescan_restores_cleanly(console):
    """Test Problem 2: Delete an account, then scan QR code to re-add it."""
    client, config, app = console

    # 1. Seed existing account
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute(
            "INSERT INTO xianyu_account(id, external_uid, nickname, deleted, status) "
            "VALUES(12, 'fixture-unb-12', '即将删除账号', 0, 1)"
        )
        db.execute(
            "INSERT INTO xianyu_account_auth(account_id, encrypted_cookie, cookie_status, deleted) "
            "VALUES(12, 'enc_c', 1, 0)"
        )
        db.execute(
            "INSERT INTO xianyu_account_runtime(account_id, cookie_status, deleted) "
            "VALUES(12, 1, 0)"
        )

    # 2. Delete the account via DELETE /api/xianyu/accounts/{id}
    del_resp = client.delete("/api/xianyu/accounts/12")
    assert del_resp.status_code == 200
    assert del_resp.json()["data"]["message"] == "删除成功"

    # Verify soft delete
    with sqlite3.connect(config.sqlite_path) as db:
        acc = db.execute("SELECT deleted, status FROM xianyu_account WHERE id=12").fetchone()
        assert acc[0] == 1 and acc[1] == 0
        auth = db.execute("SELECT deleted FROM xianyu_account_auth WHERE account_id=12").fetchone()
        assert auth[0] == 1
        rt = db.execute("SELECT deleted FROM xianyu_account_runtime WHERE account_id=12").fetchone()
        assert rt[0] == 1

    # 3. User scans to re-add the deleted account (no target account id)
    with patch("app.core.xianyu_qr_login._create_worker", _FakeWorker):
        gen_resp = client.post("/api/qrlogin/generate", json={})
        assert gen_resp.status_code == 200
        session_id = gen_resp.json()["data"]["sessionId"]

    from app.core.xianyu_qr_login import _sessions
    session_data = _sessions[session_id]
    session_data["saved_cookies"] = {
        "unb": "fixture-unb-12",
        "_m_h5_tk": "new_tk_12",
        "cookie2": "new_ck2_12",
    }
    session_data["terminal_result"] = {
        "status": "confirmed",
        "unb": "fixture-unb-12",
        "externalUid": "fixture-unb-12",
    }
    session_data["status"] = "confirmed"

    # 4. Status poll restores the account cleanly
    status_resp = client.post(f"/api/qrlogin/status/{session_id}", json={})
    assert status_resp.status_code == 200
    data = status_resp.json()["data"]
    assert data["status"] == "confirmed"
    assert data["accountId"] == 12
    assert data["authUsable"] is True
    assert data["cookieStatus"] == 1
    assert data["loginStatusCode"] == "OK"

    # 5. Check database: account was restored, not duplicated
    with sqlite3.connect(config.sqlite_path) as db:
        accounts = db.execute("SELECT id, deleted, status FROM xianyu_account WHERE external_uid='fixture-unb-12'").fetchall()
        assert len(accounts) == 1
        assert accounts[0][0] == 12
        assert accounts[0][1] == 0  # deleted = 0 (restored)
        assert accounts[0][2] == 1  # status = 1 (normal)

        auth = db.execute("SELECT deleted, cookie_status, last_login_status_code FROM xianyu_account_auth WHERE account_id=12").fetchone()
        assert auth[0] == 0
        assert auth[1] == 1
        assert auth[2] == "OK"


def test_manual_add_restores_soft_deleted_account(console):
    """Test manual cookie add restores a soft-deleted account without error."""
    client, config, app = console

    # 1. Seed soft-deleted account
    with sqlite3.connect(config.sqlite_path) as db:
        db.execute(
            "INSERT INTO xianyu_account(id, external_uid, nickname, deleted, status) "
            "VALUES(15, 'unb-15-manual', '手动账号', 1, 0)"
        )

    # 2. Add account with cookie containing unb=unb-15-manual
    cookie_str = "unb=unb-15-manual; _m_h5_tk=tk_manual; cookie2=ck2_manual"
    resp = client.post("/api/xianyu/accounts", json={"cookie": cookie_str, "accountNote": "恢复备注"})
    assert resp.status_code == 200
    assert resp.json()["data"]["account_id"] == 15

    # 3. Verify it is restored in DB
    with sqlite3.connect(config.sqlite_path) as db:
        acc = db.execute("SELECT deleted, status, remark FROM xianyu_account WHERE id=15").fetchone()
        assert acc[0] == 0
        assert acc[1] == 1
        assert acc[2] == "恢复备注"

    # 4. If adding again while active (deleted=0), it should reject as duplicate
    dup_resp = client.post("/api/xianyu/accounts", json={"cookie": cookie_str})
    assert dup_resp.status_code == 200
    assert dup_resp.json()["code"] != 200
    assert "账号已存在" in (dup_resp.json().get("msg") or dup_resp.json().get("message") or "")


def test_account_delete_and_list_endpoints_filter_soft_deleted(console):
    """Test POST /api/account/delete and verify /api/account/list filters deleted rows."""
    client, config, app = console

    with sqlite3.connect(config.sqlite_path) as db:
        db.execute(
            "INSERT INTO xianyu_account(id, external_uid, nickname, deleted, status) "
            "VALUES(20, 'unb-20', '列表测试账号', 0, 1)"
        )
        db.execute(
            "INSERT INTO xianyu_account_auth(account_id, encrypted_cookie, cookie_status, deleted) "
            "VALUES(20, 'enc_c', 1, 0)"
        )

    # List shows account 20
    list_resp = client.post("/api/account/list")
    assert list_resp.status_code == 200
    account_ids = [a["id"] for a in list_resp.json()["data"]["accounts"]]
    assert 20 in account_ids

    # Delete via /api/account/delete
    del_resp = client.post("/api/account/delete", json={"account_id": 20})
    assert del_resp.status_code == 200
    assert del_resp.json()["code"] == 200

    # List no longer shows account 20
    list_resp2 = client.post("/api/account/list")
    account_ids2 = [a["id"] for a in list_resp2.json()["data"]["accounts"]]
    assert 20 not in account_ids2


def test_rescan_with_multiple_auth_rows_does_not_raise_multiple_results_found(console):
    """Verify that multiple historical auth rows do not crash the save process with MultipleResultsFound."""
    client, config, app = console

    with sqlite3.connect(config.sqlite_path) as db:
        db.execute(
            "INSERT INTO xianyu_account(id, external_uid, nickname, deleted, status) "
            "VALUES(30, 'unb-30-multi', '重复记录账号', 0, 1)"
        )
        # Insert 2 auth rows for the same account
        db.execute(
            "INSERT INTO xianyu_account_auth(id, account_id, encrypted_cookie, cookie_status, deleted) "
            "VALUES(101, 30, 'enc_old_1', 0, 0)"
        )
        db.execute(
            "INSERT INTO xianyu_account_auth(id, account_id, encrypted_cookie, cookie_status, deleted) "
            "VALUES(102, 30, 'enc_old_2', 0, 0)"
        )

    with patch("app.core.xianyu_qr_login._create_worker", _FakeWorker):
        gen_resp = client.post("/api/qrlogin/generate", json={"accountId": 30})
        session_id = gen_resp.json()["data"]["sessionId"]

    from app.core.xianyu_qr_login import _sessions
    session_data = _sessions[session_id]
    session_data["saved_cookies"] = {
        "unb": "unb-30-multi",
        "_m_h5_tk": "new_tk_30",
        "cookie2": "new_ck2_30",
    }
    session_data["terminal_result"] = {
        "status": "confirmed",
        "unb": "unb-30-multi",
        "externalUid": "unb-30-multi",
    }
    session_data["status"] = "confirmed"

    # Status poll must succeed without MultipleResultsFound
    status_resp = client.post(f"/api/qrlogin/status/{session_id}", json={"accountId": 30})
    assert status_resp.status_code == 200
    assert status_resp.json()["data"]["status"] == "confirmed"
    assert status_resp.json()["data"]["authUsable"] is True
