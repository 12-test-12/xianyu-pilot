import base64
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.core import paths
from app.core.config import Settings
from app.desktop_app import create_desktop_app
from app.services import desktop_plugins

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
    key = Ed25519PrivateKey.generate()

    class Runtime:
        async def start(self):
            pass

        async def stop(self):
            pass

    app = create_desktop_app(Settings(runtime_mode="desktop"), web_dir=tmp_path / "web", platform_runtime=Runtime())
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
    assert result.json()["data"][0]["command"] == "查 12345678"

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
