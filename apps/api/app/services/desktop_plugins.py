"""Local, signed packages for declarative QQ delivery plans."""
import hashlib
import re
import sqlite3
import tempfile
import zlib
from contextlib import closing
from io import BytesIO
from pathlib import Path, PureWindowsPath
from threading import Lock
from typing import Annotated, Literal
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.paths import contained_data_path
from app.services.desktop_inventory import InventoryError

ID_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
VERSION_PATTERN = r"^(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})$"
PACKAGE_FILES = {"manifest.json": 24 * 1024, "manifest.sig": 256}
UPLOAD_LIMIT = 64 * 1024
ParameterType = Literal["short_link", "number", "nickname"]
CATALOG = [{
    "id": "qiuqiu-assist", "name": "球球助力",
    "description": "预演短链接、球球号和昵称的助力指令。",
    "requires": "正式执行需 QQ 机器人", "source": "从项目维护者获取插件包",
}]


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=60)
    verb: str = Field(min_length=1, max_length=30, pattern=r"^[^\r\n]+$")
    input: Literal["parameter", "rank"] = "parameter"


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=240)
    version: str = Field(pattern=VERSION_PATTERN)
    hostApi: Literal[1]
    kind: Literal["qq-delivery"]
    plans: dict[ParameterType, Annotated[list[Step], Field(min_length=1, max_length=3)]] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def valid_windows_name(cls, value):
        if PureWindowsPath(value).is_reserved():
            raise ValueError("插件 ID 是 Windows 保留名称")
        return value

    def summary(self):
        return self.model_dump(exclude={"plans"}) | {"parameterTypes": list(self.plans)}


def unpack_zip(data):
    try:
        with ZipFile(BytesIO(data)) as package:
            entries = package.infolist()
            if (len(entries) != len(PACKAGE_FILES)
                    or {entry.orig_filename for entry in entries} != PACKAGE_FILES.keys()
                    or any(entry.file_size > PACKAGE_FILES[entry.filename]
                           or entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED) for entry in entries)):
                raise InventoryError("插件 ZIP 应只包含根目录中的 manifest.json 和 manifest.sig")
            return {entry.filename: package.read(entry) for entry in entries}
    except (BadZipFile, RuntimeError, zlib.error) as exc:
        raise InventoryError("无法读取插件 ZIP") from exc


def read_small(path, limit):
    with path.open("rb") as source:
        content = source.read(limit + 1)
    if len(content) > limit:
        raise InventoryError("插件文件超过大小限制")
    return content


def preview_plan(manifest, parameter_type, value):
    steps = manifest.plans.get(parameter_type)
    if not steps:
        raise InventoryError("此插件不支持所选参数类型")
    value = value.strip()
    if not value or any(ord(char) < 32 for char in value):
        raise InventoryError("请输入一个有效的单行参数")
    if parameter_type == "number" and not re.fullmatch(r"[0-9]{5,20}", value):
        raise InventoryError("球球号应为 5 至 20 位数字")
    if parameter_type == "short_link" and not re.fullmatch(r"https?://[^\s/]+(?:/[^\s]*)?", value):
        raise InventoryError("请输入一个完整的短链接")
    return [
        {"title": step.title, "command": f"{step.verb} {value}" if step.input == "parameter" else None}
        for step in steps
    ]


class DesktopPlugins:
    def _connect_db(self):
        """Create a SQLite connection with a 5 s timeout.
        Centralising this logic avoids duplication and ensures a consistent timeout.
        """
        return sqlite3.connect(self.database, timeout=5)
    def __init__(self, program_root: Path, database: Path):
        self.program_root = program_root
        self.root = program_root / "plugins"
        self.database = database
        self.lock = Lock()

    def _path(self, relative):
        try:
            return contained_data_path(self.root, relative)
        except ValueError as exc:
            raise InventoryError("插件目录不允许链接、目录联接或越界路径") from exc

    def _publisher(self):
        try:
            path = contained_data_path(self.program_root, "plugin-publisher.pub")
            public_key = read_small(path, 128).decode("ascii")
            return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
        except (OSError, ValueError) as exc:
            raise InventoryError("请在程序旁配置维护者的 plugin-publisher.pub", 503) from exc

    def _verify(self, files, publisher):
        if files.keys() != PACKAGE_FILES.keys() or any(len(files[name]) > limit for name, limit in PACKAGE_FILES.items()):
            raise InventoryError("插件包应只包含 manifest.json 和 manifest.sig")
        try:
            publisher.verify(bytes.fromhex(files["manifest.sig"].decode("ascii")), files["manifest.json"])
        except (InvalidSignature, ValueError) as exc:
            raise InventoryError("插件签名校验失败") from exc
        try:
            return Manifest.model_validate_json(files["manifest.json"])
        except ValidationError as exc:
            raise InventoryError("插件清单无效或宿主版本不兼容") from exc

    def _read(self, plugin_id, version, publisher):
        relative = f"{plugin_id}/{version}"
        path = self._path(relative)
        if not path.is_dir():
            raise InventoryError("此插件版本尚未安装", 404)
        try:
            if {entry.name for entry in path.iterdir()} != PACKAGE_FILES.keys():
                raise InventoryError("插件目录中的文件与清单格式不符")
            files = {
                name: read_small(self._path(f"{relative}/{name}"), limit)
                for name, limit in PACKAGE_FILES.items()
            }
        except OSError as exc:
            raise InventoryError("无法读取本地插件文件") from exc
        manifest = self._verify(files, publisher)
        if (manifest.id, manifest.version) != (plugin_id, version):
            raise InventoryError("插件 ID 或版本与目录名称不符")
        return manifest, hashlib.sha256(files["manifest.json"]).hexdigest()

    def status(self):
        with self.lock, closing(self._connect_db()) as db:
            activations = {key: (version, digest) for key, version, digest in db.execute(
                "SELECT plugin_id, version, manifest_hash FROM desktop_plugin_activation"
            )}
            packages, issues = [], []
            try:
                publisher = self._publisher()
            except InventoryError as exc:
                return {"available": CATALOG, "installed": [], "issues": [], "publisherIssue": str(exc)}
            for folder in sorted(self._path(".").glob("*")):
                if not re.fullmatch(ID_PATTERN, folder.name):
                    continue
                try:
                    folder = self._path(folder.name)
                except InventoryError as exc:
                    issues.append({"path": folder.name, "message": str(exc)})
                    continue
                for version in sorted(folder.glob("*")):
                    if not re.fullmatch(VERSION_PATTERN, version.name):
                        continue
                    try:
                        manifest, digest = self._read(folder.name, version.name, publisher)
                        enabled = activations.get(folder.name) == (version.name, digest)
                        packages.append(manifest.summary() | {"enabled": enabled})
                    except InventoryError as exc:
                        issues.append({"path": f"{folder.name}/{version.name}", "message": str(exc)})
            return {"available": CATALOG, "installed": packages, "issues": issues, "publisherIssue": None}

    def install(self, files, *, inspect=False):
        with self.lock:
            publisher = self._publisher()
            manifest = self._verify(files, publisher)
            if not inspect:
                path = self._path(f"{manifest.id}/{manifest.version}")
                if path.exists():
                    try:
                        _, digest = self._read(manifest.id, manifest.version, publisher)
                        if digest == hashlib.sha256(files["manifest.json"]).hexdigest():
                            return manifest.summary()
                        raise InventoryError("同版本已存在，请发布新版本", 409)
                    except InventoryError as exc:
                        if exc.status == 409:
                            raise
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix=".install-", dir=path.parent) as staging:
                    candidate = Path(staging) / "package"
                    candidate.mkdir()
                    for name, contents in files.items():
                        (candidate / name).write_bytes(contents)
                    backup = None
                    if path.exists():
                        self._check_removable(path)
                        backup = self._path(f"{manifest.id}/.repair-{uuid4().hex}")
                        path.rename(backup)
                    try:
                        candidate.rename(path)
                    except OSError:
                        if backup is not None:
                            try:
                                backup.rename(path)
                            except OSError as exc:
                                raise InventoryError(f"旧插件文件保存在 {manifest.id}/{backup.name}，请手动恢复", 503) from exc
                        raise
                    if backup is not None:
                        for name in PACKAGE_FILES:
                            (backup / name).unlink(missing_ok=True)
                        backup.rmdir()
            return manifest.summary()

    def set_enabled(self, plugin_id, version, enabled):
        with self.lock, closing(sqlite3.connect(self.database, timeout=5)) as db, db:
            if enabled:
                _, digest = self._read(plugin_id, version, self._publisher())
                db.execute(
                    """INSERT INTO desktop_plugin_activation VALUES (?, ?, ?)
                    ON CONFLICT(plugin_id) DO UPDATE SET version=excluded.version, manifest_hash=excluded.manifest_hash""",
                    (plugin_id, version, digest),
                )
            else:
                self._disable(db, plugin_id, version)

    @staticmethod
    def _disable(db, plugin_id, version):
        db.execute("DELETE FROM desktop_plugin_activation WHERE plugin_id=? AND version=?", (plugin_id, version))

    def _check_removable(self, path):
        if not path.is_dir() or not {entry.name for entry in path.iterdir()} <= PACKAGE_FILES.keys():
            raise InventoryError("插件目录含有其他内容，请手动检查", 409)
        for name in PACKAGE_FILES:
            entry = self._path((path / name).relative_to(self.root).as_posix())
            if entry.exists() and not entry.is_file():
                raise InventoryError("插件文件格式异常，请手动检查", 409)

    def uninstall(self, plugin_id, version):
        with self.lock, closing(self._connect_db()) as db:
            path = self._path(f"{plugin_id}/{version}")
            if not path.exists():
                with db:
                    self._disable(db, plugin_id, version)
                return
            self._check_removable(path)
            with db:
                self._disable(db, plugin_id, version)
            with tempfile.TemporaryDirectory(prefix=".remove-", dir=path.parent) as staging:
                path.rename(Path(staging) / "package")

    def preview(self, plugin_id, version, parameter_type, value):
        with self.lock, closing(self._connect_db()) as db:
            manifest, digest = self._read(plugin_id, version, self._publisher())
            active = db.execute(
                "SELECT version, manifest_hash FROM desktop_plugin_activation WHERE plugin_id=?", (plugin_id,)
            ).fetchone()
            if active != (version, digest):
                raise InventoryError("请先启用此插件版本", 409)
            return preview_plan(manifest, parameter_type, value)
