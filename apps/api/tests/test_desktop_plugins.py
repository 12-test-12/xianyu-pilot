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
        assert client.get(ENDPOINT).json()["data"]["publisherIssue"]
        (tmp_path / "plugin-publisher.pub").write_text(key.public_key().public_bytes_raw().hex(), encoding="ascii")
        yield client, key, tmp_path


def post_zip(client, target, contents):
    return client.post(target, content=contents, headers={"Content-Type": "application/zip", "X-Request-Id": "plugin-test"})


def test_zip_install_preview_version_switch_and_uninstall(desktop):
    client, key, root = desktop
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


def test_rejects_unsafe_packages_and_revalidates_manual_install(desktop):
    client, key, root = desktop
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
