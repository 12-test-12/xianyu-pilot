import base64
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import sqlite3
import subprocess
from subprocess import CompletedProcess, TimeoutExpired
from threading import Thread
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.core import paths, secret_store
from app.core.config import Settings
from app.desktop_app import create_desktop_app
from app.services import desktop_plugins
from app.desktop_storage import DesktopStore, MIGRATIONS

ENDPOINT = "/api/desktop/plugins"
PACKAGE = f"{ENDPOINT}/package"
INSTALLED = f"{ENDPOINT}/qiuqiu-assist/0.1.0"
MANIFEST = Path(__file__).resolve().parents[3] / "plugin-packages/qiuqiu-assist/manifest.json"


def signed_files(key, **overrides):
    manifest = json.dumps(json.loads(MANIFEST.read_bytes()) | overrides).encode()
    return {"manifest.json": manifest, "manifest.sig": key.sign(manifest).hex().encode()}


def archive(files):
    result = BytesIO()
    with ZipFile(result, "w") as package:
        for name, content in files.items():
            package.writestr(name, content)
    return result.getvalue()


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SOURCE_ROOT", tmp_path)
    config = Settings(runtime_mode="desktop")
    monkeypatch.setattr(secret_store, "settings", config)
    key = Ed25519PrivateKey.generate()

    class Runtime:
        async def start(self):
            pass

        async def stop(self):
            pass

    app = create_desktop_app(config, web_dir=tmp_path / "web", platform_runtime=Runtime())
    with TestClient(app, base_url="http://127.0.0.1:15177") as client:
        assert client.get(ENDPOINT).status_code == 401
        client.headers["Authorization"] = f"Bearer {app.state.desktop_token}"
        yield client, key, tmp_path


@pytest.fixture
def external_publisher(desktop):
    _, key, root = desktop
    (root / "plugin-publisher.pub").write_text(key.public_key().public_bytes_raw().hex(), encoding="ascii")
    return desktop


def post_zip(client, target, contents):
    return client.post(target, content=contents, headers={"Content-Type": "application/zip", "X-Request-Id": "plugin-test"})


def test_qq_target_survives_restart_and_draft_uses_the_saved_robot(desktop, monkeypatch):
    client, _, root = desktop
    path = f"{ENDPOINT}/qq/target"
    target = {"robotQq": "20002", "robotName": "球球机器人"}
    opened = []

    def open_draft(robot, command):
        opened.append((robot, command))
        return {"state": "draft_ready"}

    monkeypatch.setattr(desktop_plugins, "open_qq_draft", open_draft)
    assert client.get(path, headers={"Authorization": ""}).status_code == 401
    assert client.get(path).json()["data"] is None
    assert client.put(path, json=target, headers={"Origin": "https://example.com"}).status_code == 403
    assert client.put(path, json=target | {"robotQq": "20002;invalid"}).status_code == 422
    assert client.put(path, json=target).json()["data"] == target
    assert desktop_plugins.DesktopPlugins(root, root / "data/app.sqlite3").qq_target() == target

    plugin = client.post(f"{ENDPOINT}/catalog/qiuqiu-assist/install", json={}).json()["data"]
    installed = f"{ENDPOINT}/{plugin['id']}/{plugin['version']}"
    assert client.patch(installed, json={"enabled": True}).status_code == 200
    draft_url = f"{installed}/qq-draft"
    draft = {"target": target, "parameterType": "number", "value": "78901", "stepIndex": 0}
    assert client.post(draft_url, json=draft | {"target": target | {"robotQq": "99999"}}).status_code == 409
    assert client.post(draft_url, json=draft | {"stepIndex": 1}).status_code == 400
    assert client.post(draft_url, json=draft | {"parameterType": "nickname", "value": "foo\u2028助力 bar"}).status_code == 400
    assert not opened
    assert client.post(draft_url, json=draft).json()["data"] == {"state": "draft_ready"}
    assert opened == [(target, "助力 78901")]

    newer = {"robotQq": "30003", "robotName": ""}
    assert client.put(path, json=newer).json()["data"] == newer
    assert client.post(draft_url, json=draft).status_code == 409
    assert client.get(path).json()["data"] == newer


def test_desktop_draft_script_loads_utf8_and_handles_subprocess_results(monkeypatch, tmp_path):
    from app.services.qq_bridge import desktop_draft
    assert desktop_draft.SCRIPT.exists()
    content = desktop_draft.SCRIPT.read_text(encoding="utf-8-sig")
    assert "Open-QQDraft" in content
    assert "Paste-Editor" in content
    monkeypatch.setattr(desktop_draft, "SCRIPT", tmp_path / "Win's QQ 草稿.ps1")
    escaped_path = tmp_path / "Win''s QQ 草稿.ps1"

    # Changing the shared os module would also change pathlib and pytest.
    platform = SimpleNamespace(name="posix", environ={})
    monkeypatch.setattr(desktop_draft, "os", platform)
    with pytest.raises(desktop_draft.InventoryError) as exc:
        desktop_draft.open_qq_draft({"robotQq": "12345"}, "test command")
    assert "Windows 电脑 QQ" in str(exc.value)

    platform.name = "nt"
    result = CompletedProcess(args=[], returncode=0, stdout=b"qq_closed\n")
    no_window = 0x08000000

    def run(args, **kwargs):
        launch = base64.b64decode(args[-1]).decode("utf-16-le")
        assert launch == (f"& ([scriptblock]::Create([IO.File]::ReadAllText('{escaped_path}', [System.Text.Encoding]::UTF8)))"
                          f" -helperPath '{escaped_path.with_suffix('.cs')}'")
        assert kwargs["creationflags"] == no_window
        return result

    process = SimpleNamespace(
        run=run, CREATE_NO_WINDOW=no_window, TimeoutExpired=TimeoutExpired,
    )
    monkeypatch.setattr(desktop_draft, "subprocess", process)
    with pytest.raises(desktop_draft.InventoryError) as exc:
        desktop_draft.open_qq_draft({"robotQq": "12345"}, "test command")
    assert "请先打开并登录电脑 QQ" in str(exc.value)

    result.stdout = b"draft_ready\r\n"
    assert desktop_draft.open_qq_draft({"robotQq": "12345"}, "test command") == {"state": "draft_ready"}

    def time_out(args, *, timeout, **kwargs):
        raise TimeoutExpired(args, timeout)

    process.run = time_out
    with pytest.raises(desktop_draft.InventoryError, match="等待 QQ 草稿操作超时"):
        desktop_draft.open_qq_draft({"robotQq": "12345"}, "test command")

    def receipt_timeout(args, *, timeout, **kwargs):
        raise TimeoutExpired(args, timeout, output=b"send_confirmed\r\n")

    process.run = receipt_timeout
    assert desktop_draft.send_qq_command({"robotQq": "12345"}, "test command", "window:1:2:3") == {"state": "submitted"}


@pytest.mark.skipif(os.name != "nt", reason="tests the native Windows PowerShell script")
def test_qq_script_checks_receipt_and_send_context_without_interacting_with_qq():
    fixture = Path(__file__).with_name("qq_draft_review.ps1")
    script_path = str(fixture).replace("'", "''")
    launch = f"& ([scriptblock]::Create([IO.File]::ReadAllText('{script_path}')))"
    # The fixture reads the production script relative to its own repository path.
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand",
         base64.b64encode(launch.encode("utf-16-le")).decode("ascii")],
        cwd=fixture.parents[3], capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_qq_target_migration_preserves_an_existing_robot(tmp_path):
    database = tmp_path / "app.sqlite3"
    older = tmp_path / "migrations"
    older.mkdir()
    for migration in MIGRATIONS.glob("00[1-9]*.sql"):
        (older / migration.name).write_bytes(migration.read_bytes())
    DesktopStore(database, older).initialize()
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO desktop_plugin_qq_connection VALUES (1, ?, ?, ?, ?, ?, ?)",
                   ("http://127.0.0.1:3000", "10001", "20002", "球球机器人", "old-token", "checked"))
    DesktopStore(database).initialize()
    plugins = desktop_plugins.DesktopPlugins(tmp_path, database)
    assert plugins.qq_target() == {"robotQq": "20002", "robotName": "球球机器人"}
    profile, = plugins.qq_profiles()
    assert profile == {"id": profile["id"], "qqAccount": "", "robotQq": "20002", "robotName": "球球机器人", "backup": False}
    assert plugins.qq_connection()["qqAccount"] == "10001"


@pytest.mark.parametrize("previous_receipt", [False, True])
def test_qq_receipt_migration_upgrades_both_predecessors(tmp_path, previous_receipt):
    database = tmp_path / "app.sqlite3"
    older = tmp_path / "migrations"
    older.mkdir()
    for migration in MIGRATIONS.glob("*.sql"):
        if migration.name.startswith("012_"):
            continue
        sql = migration.read_text(encoding="utf-8")
        if previous_receipt and migration.name.startswith("011_"):
            sql = sql.replace("'uncertain'))", "'uncertain', 'receipt_success', 'receipt_capped'))")
        (older / migration.name).write_text(sql, encoding="utf-8")
    DesktopStore(database, older).initialize()
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO desktop_plugin_qq_send_attempt VALUES ('id', 'original', ?)",
                   ("receipt_success" if previous_receipt else "submitted",))
        db.execute("INSERT INTO desktop_plugin_qq_send_attempt VALUES ('unresolved', 'other', 'uncertain')")
    store = DesktopStore(database)
    assert store.initialize()["current"] and store.initialize()["current"]
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT * FROM desktop_plugin_qq_send_attempt ORDER BY id").fetchall() == [
            ("id", "original", "submitted"), ("unresolved", "other", "uncertain"),
        ]
        db.execute("UPDATE desktop_plugin_qq_send_attempt SET state='receipt_success' WHERE id='id'")


def test_qq_profiles_batch_preview_and_idempotent_send(desktop, monkeypatch):
    client, _, root = desktop
    profiles = f"{ENDPOINT}/qq/profiles"
    windows = f"{ENDPOINT}/qq/windows"
    common = {"qqAccount": "10001", "robotQq": "20002", "robotName": "球球机器人"}
    primary = client.post(profiles, json=common).json()["data"]
    backup = client.post(profiles, json=common | {"robotQq": "40004", "backup": True}).json()["data"]
    other = client.post(profiles, json=common | {"qqAccount": "30003"}).json()["data"]
    assert client.post(profiles, json=common).status_code == 409
    assert client.post(profiles, json=common | {"robotQq": "10001"}).status_code == 400
    assert desktop_plugins.DesktopPlugins(root, root / "data/app.sqlite3").qq_profiles() == [primary, other, backup]

    plugin = client.post(f"{ENDPOINT}/catalog/qiuqiu-assist/install", json={}).raise_for_status().json()["data"]
    installed = f"{ENDPOINT}/{plugin['id']}/{plugin['version']}"
    client.patch(installed, json={"enabled": True}).raise_for_status()
    batch = {"parameterType": "number", "values": ["78901", "98765", " 78901 "]}
    for kind in ("number", "nickname", "short_link"):
        preview = client.post(f"{installed}/preview-batch", json=batch | {"parameterType": kind}).json()["data"]
        assert [(group["value"], group["steps"][0]["command"]) for group in preview] == [
            ("78901", "助力 78901"), ("98765", "助力 98765"),
        ]
    assert client.post(f"{installed}/preview-batch", json=batch | {"values": ["78901", "bad"]}).status_code == 400

    window = "window:1:2:3"
    attempts = f"{ENDPOINT}/qq-send/attempts"
    monkeypatch.setattr(desktop_plugins, "bind_qq_window", lambda: window)
    opens = []

    def submit(target, command, bound_window, value=None):
        opens.append((target, command, bound_window, value))
        if command == "助力 98765":
            raise desktop_plugins.InventoryError("QQ 发送结果待核查", 503)
        return {"state": "receipt_success" if value else "submitted"}

    monkeypatch.setattr(desktop_plugins, "send_qq_command", submit)
    send = f"{installed}/qq-send"
    request = {"parameterType": "number", "value": "78901", "stepIndex": 0, "target": backup,
               "attemptId": "qq-send-" + "a" * 32}
    assert client.post(send, json=request).status_code == 409
    assert client.get(f"{attempts}/{request['attemptId']}").json()["data"] == {"state": "not_found"}
    assert client.put(f"{windows}/10001", json={}).raise_for_status().json()["data"] == ["10001"]
    assert client.put(f"{windows}/30003", json={}).status_code == 409
    assert client.post(send, json=request | {"target": backup | {"robotQq": "99999"}}).status_code == 409
    for _ in range(2):
        assert client.post(send, json=request).json()["data"] == {"state": "receipt_success"}
    assert client.get(f"{attempts}/{request['attemptId']}").json()["data"] == {"state": "receipt_success"}
    assert client.post(f"{send}/clear", json=request).status_code == 409
    assert opens == [(backup, "助力 78901", window, "78901")]
    repeat = request | {"attemptId": "qq-send-" + "e" * 32}
    assert client.post(send, json=repeat).json()["data"] == {"state": "submitted"}
    assert opens[-1] == (backup, "助力 78901", window, None)
    uncertain = request | {"value": "98765", "attemptId": "qq-send-" + "b" * 32}
    assert client.post(send, json=uncertain).status_code == 503
    assert client.post(send, json=uncertain).status_code == 409
    assert client.post(send, json=uncertain | {"attemptId": "qq-send-" + "c" * 32}).status_code == 409
    assert client.get(f"{attempts}/{uncertain['attemptId']}").json()["data"] == {"state": "uncertain"}
    assert opens[-1] == (backup, "助力 98765", window, "98765")
    assert len(opens) == 3
    assert client.post(f"{send}/clear", json={key: value for key, value in uncertain.items() if key != "attemptId"}).status_code == 200
    assert client.post(send, json=uncertain | {"attemptId": "qq-send-" + "d" * 32}).status_code == 503
    assert opens[-1] == (backup, "助力 98765", window, None)
    assert client.delete(f"{profiles}/{backup['id']}", headers={"X-Request-Id": "qq-test"}).status_code == 200
    assert client.post(send, json=request).status_code == 409


def test_qq_connection_checks_login_and_robot_friend_before_saving(desktop):
    client, _, root = desktop
    path = f"{ENDPOINT}/qq/connection"
    token = "fixture-onebot-token"
    state = {"online": True, "calls": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                self.rfile.read(content_length)
            state["calls"].append(self.path)
            if self.headers.get("Authorization") != f"Bearer {token}":
                self.send_error(401)
                return
            data = {
                "/get_status": {"online": state["online"]},
                "/get_login_info": {"user_id": 10001},
                "/get_friend_list": [{"user_id": 20002, "nickname": "球球机器人"}],
            }[self.path]
            body = json.dumps({"status": "ok", "retcode": 0, "data": data}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = {"endpoint": f"http://127.0.0.1:{server.server_port}", "qqAccount": "10001", "robotQq": "20002"}
            assert client.get(path, headers={"Authorization": ""}).status_code == 401
            assert client.get(path).json()["data"] is None
            assert client.put(path, json=payload | {"endpoint": "http://example.com:3000", "accessToken": token}).status_code == 422
            assert client.put(path, json=payload | {"accessToken": token}, headers={"Origin": "https://example.com"}).status_code == 403
            result = client.put(path, json=payload | {"accessToken": token})
            assert result.status_code == 200, result.text
            saved = result.json()["data"]
            assert saved == payload | {"robotName": "球球机器人", "checkedAt": saved["checkedAt"]}
            assert state["calls"] == ["/get_status", "/get_login_info", "/get_friend_list"]
            with sqlite3.connect(root / "data/app.sqlite3") as db:
                encrypted, = db.execute("SELECT encrypted_token FROM desktop_plugin_qq_connection").fetchone()
                assert encrypted.startswith("secret:v1:") and token not in encrypted
            assert client.put(path, json=payload).status_code == 200
            for overrides in ({"accessToken": "wrong"}, {"robotQq": "99999"}, {"qqAccount": "99999", "accessToken": token}):
                assert client.put(path, json=payload | overrides).status_code == 422
            state["online"] = False
            assert client.put(path, json=payload).status_code == 422
            assert client.get(path).json()["data"]["robotQq"] == "20002"
            assert client.delete(path, headers={"X-Request-Id": "qq-test"}).status_code == 200
            assert client.get(path).json()["data"] is None
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_bundled_plugin_installs_and_runs_without_a_publisher_file(desktop, monkeypatch):
    client, _, root = desktop
    status = client.get(ENDPOINT).json()["data"]
    plugin, = status["available"]
    assert plugin["id"] == "qiuqiu-assist"
    assert set(plugin["parameterTypes"]) == {"short_link", "number", "nickname"}
    assert not status["installed"]
    assert status["publisherIssue"] is None
    assert status["catalogIssue"] is None

    headers = {"X-Request-Id": "plugin-test"}
    assert client.post(f"{ENDPOINT}/catalog/unknown/install", headers=headers).status_code == 404
    assert client.post(f"{ENDPOINT}/catalog/qiuqiu-assist/install").status_code == 415
    publisher_file = root / "plugin-publisher.pub"
    publisher_file.write_text("invalid", encoding="ascii")
    install_url = f"{ENDPOINT}/catalog/qiuqiu-assist/install"
    for _ in range(2):
        assert client.post(install_url, headers=headers).json()["data"] == plugin
    installed_url = f"{ENDPOINT}/{plugin['id']}/{plugin['version']}"
    assert client.patch(installed_url, json={"enabled": True}).status_code == 200
    assert client.get(ENDPOINT).json()["data"]["installed"] == [plugin | {"enabled": True}]
    result = client.post(f"{installed_url}/preview", json={"parameterType": "number", "value": "12345678"})
    assert result.json()["data"][0]["command"] == "助力 12345678"

    monkeypatch.setattr(desktop_plugins, "BUNDLED_PACKAGE", root / "missing.zip")
    status = client.get(ENDPOINT).json()["data"]
    assert not status["available"]
    assert status["catalogIssue"]
    assert status["publisherIssue"]
    assert status["installed"] == [plugin | {"enabled": True}]
    assert client.post(install_url, headers=headers).status_code == 503
    assert client.patch(installed_url, json={"enabled": False}).status_code == 200
    assert client.delete(installed_url, headers=headers).status_code == 200
    assert not client.get(ENDPOINT).json()["data"]["installed"]


def test_zip_install_preview_version_switch_and_uninstall(external_publisher):
    client, key, root = external_publisher
    package = archive(signed_files(key))
    assert post_zip(client, f"{PACKAGE}/inspect", package).json()["data"]["id"] == "qiuqiu-assist"
    assert not (root / "plugins").exists()
    assert post_zip(client, PACKAGE, package).status_code == 200
    assert post_zip(client, PACKAGE, package).status_code == 200
    data = client.get(ENDPOINT).json()["data"]
    assert data["available"][0]["id"] == "qiuqiu-assist"
    assert data["installed"][0]["enabled"] is False

    preview = {"parameterType": "number", "value": "12345678"}
    assert client.post(f"{INSTALLED}/preview", json=preview).status_code == 409
    assert client.patch(INSTALLED, json={"enabled": True}).status_code == 200
    steps = client.post(f"{INSTALLED}/preview", json=preview).json()["data"]
    assert [step["command"] for step in steps] == ["查 12345678", None]
    assert client.post(f"{INSTALLED}/preview", json=preview | {"value": "123\n45"}).status_code == 400

    files = signed_files(key, version="0.2.0")
    folder = {name: base64.b64encode(data).decode() for name, data in files.items()}
    assert client.post(PACKAGE, json=folder).status_code == 200
    update = f"{ENDPOINT}/qiuqiu-assist/0.2.0"
    assert client.patch(update, json={"enabled": True}).status_code == 200
    assert client.post(f"{INSTALLED}/preview", json=preview).status_code == 409
    assert client.patch(update, json={"enabled": False}).status_code == 200
    assert client.delete(update, headers={"X-Request-Id": "plugin-test"}).status_code == 200
    assert not (root / "plugins/qiuqiu-assist/0.2.0").exists()
    assert (root / "plugins/qiuqiu-assist/0.1.0/manifest.json").is_file()


def test_rejects_unsafe_packages_and_revalidates_manual_install(external_publisher):
    client, key, root = external_publisher
    valid = signed_files(key)
    for files in (
        valid | {"../outside": b"outside"},
        valid | {"manifest.sig": b"0" * 128},
        signed_files(key, id="con"),
        signed_files(key, hostApi=2),
        signed_files(Ed25519PrivateKey.generate()),
    ):
        assert post_zip(client, PACKAGE, archive(files)).status_code == 400
    assert post_zip(client, PACKAGE, b"x" * (64 * 1024 + 1)).status_code == 413
    assert not (root / "plugins").exists()

    folder = root / "plugins/qiuqiu-assist/0.1.0"
    folder.mkdir(parents=True)
    for name, data in valid.items():
        (folder / name).write_bytes(data)
    assert client.get(ENDPOINT).json()["data"]["installed"][0]["enabled"] is False
    assert client.patch(INSTALLED, json={"enabled": True}, headers={"Origin": "https://example.com"}).status_code == 403
    assert client.patch(INSTALLED, json={"enabled": True}).status_code == 200
    other = signed_files(key, name="Different")
    assert post_zip(client, PACKAGE, archive(other)).status_code == 409
    (folder / "manifest.json").write_bytes(other["manifest.json"])
    status = client.get(ENDPOINT).json()["data"]
    assert not status["installed"]
    assert status["issues"][0]["path"] == "qiuqiu-assist/0.1.0"
    assert client.patch(INSTALLED, json={"enabled": True}).status_code == 400
    assert post_zip(client, PACKAGE, archive(valid)).status_code == 200
    recovered = client.get(ENDPOINT).json()["data"]
    assert recovered["installed"][0]["version"] == "0.1.0"
    assert not recovered["issues"]


def test_repair_preserves_local_files_and_restores_original_on_failed_install(external_publisher, monkeypatch):
    client, key, root = external_publisher
    package = archive(signed_files(key))
    assert post_zip(client, PACKAGE, package).status_code == 200
    folder = root / "plugins/qiuqiu-assist/0.1.0"
    note = folder / "notes.txt"
    note.write_bytes(b"user file")
    assert post_zip(client, PACKAGE, package).status_code == 409
    assert note.read_bytes() == b"user file"
    note.unlink()

    manifest = folder / "manifest.json"
    manifest.write_bytes(b"damaged")
    rename = Path.rename

    def fail_publish(path, destination):
        if path.name == "package" and destination == folder:
            raise PermissionError("simulated Windows sharing lock")
        return rename(path, destination)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", fail_publish)
        assert post_zip(client, PACKAGE, package).status_code == 503
    assert manifest.read_bytes() == b"damaged"
    assert post_zip(client, PACKAGE, package).status_code == 200
