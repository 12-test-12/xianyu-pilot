"""Local, signed packages for declarative QQ delivery plans."""
import hashlib
import re
import sqlite3
import tempfile
import zlib
from contextlib import closing, contextmanager
from datetime import datetime, timezone
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
from app.core.secret_store import decrypt_secret, encrypt_secret
from app.services.desktop_inventory import InventoryError
from app.services.qq_bridge.desktop_draft import SUBMITTED_STATES, bind_qq_window, open_qq_draft, send_qq_command
from app.services.qq_bridge.onebot import ConnectorError, OneBotClient, validate_endpoint

ID_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"
VERSION_PATTERN = r"^(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})$"
PACKAGE_FILES = {"manifest.json": 24 * 1024, "manifest.sig": 256}
UPLOAD_LIMIT = 64 * 1024
ParameterType = Literal["short_link", "number", "nickname"]
BUNDLED_ID = "qiuqiu-assist"
BUNDLED_PACKAGE = Path(__file__).resolve().parents[1] / "resources" / "qiuqiu-assist.zip"
BUNDLED_LEGACY_MANIFEST_HASH = "fe3faba1fdbd3f015931f798268ec47f52d23b3e74546d61a4c97c66c990b72c"
# Public key from the signed Qiuqiu Assist trial. Its trust is limited to that plugin ID.
BUNDLED_PUBLISHER = Ed25519PublicKey.from_public_bytes(
    bytes.fromhex("839a44c4c2944f3ddd66c5c1c2d38319ff88bf4834006ec199234d0bc144089a")
)


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


def preview_plan(manifest, parameter_type, value, *, direct_number=False):
    steps = manifest.plans.get(parameter_type)
    if not steps:
        raise InventoryError("此插件不支持所选参数类型")
    value = value.strip()
    if not value or any(ord(char) < 32 for char in value):
        raise InventoryError("请输入一个有效的单行参数")
    is_pure_number = bool(re.fullmatch(r"[0-9]{5,20}", value))
    # The original signed package declared a rank lookup for IDs the robot now accepts directly.
    if direct_number and is_pure_number:
        return [{"title": "按球球号发起助力", "command": f"助力 {value}"}]
    if parameter_type == "number" and not is_pure_number:
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
        self.qq_lock = Lock()
        self.qq_draft_lock = Lock()
        self.qq_windows = {}

    def qq_connection(self):
        with closing(self._connect_db()) as db:
            row = db.execute("""
                SELECT endpoint, qq_account, robot_qq, robot_name, checked_at
                FROM desktop_plugin_qq_connection WHERE id = 1
            """).fetchone()
        if row is None:
            return None
        return dict(zip(("endpoint", "qqAccount", "robotQq", "robotName", "checkedAt"), row))

    def connect_qq(self, endpoint, qq_account, robot_qq, token):
        purpose = "desktop.plugin.qq.token"
        with self.qq_lock:
            try:
                endpoint = f"http://127.0.0.1:{validate_endpoint(endpoint.strip())}"
                if qq_account == robot_qq:
                    raise ConnectorError("机器人 QQ 号应填写好友的 QQ 号")
                if not token:
                    with closing(self._connect_db()) as db:
                        saved = db.execute("""
                            SELECT encrypted_token FROM desktop_plugin_qq_connection
                            WHERE id = 1 AND endpoint = ? AND qq_account = ?
                        """, (endpoint, qq_account)).fetchone()
                    if saved is None:
                        raise ConnectorError("请填写当前 OneBot 地址和账号对应的 Access Token")
                    token = decrypt_secret(saved[0], purpose=purpose)
                if token.startswith("secret:v1:"):
                    raise ConnectorError("请填写 OneBot 提供的原始 Access Token")
                client = OneBotClient(endpoint, token)
                status = client.call("get_status", {})
                if not isinstance(status, dict) or status.get("online") is not True:
                    raise ConnectorError("OneBot 已响应，QQ 当前未在线")
                target = f"{qq_account}:direct:{robot_qq}"
                robot = next((friend for friend in client.friends(qq_account) if friend["conversation_id"] == target), None)
                if robot is None:
                    raise ConnectorError("QQ 好友列表中找不到这个机器人，请核对 QQ 号和好友关系")
                encrypted = encrypt_secret(token, purpose=purpose)
            except ConnectorError as exc:
                raise InventoryError(str(exc), 422) from exc
            except RuntimeError as exc:
                raise InventoryError("无法读取或保存 QQ 凭据，请核对桌面凭据密钥", 503) from exc
            checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with closing(self._connect_db()) as db, db:
                db.execute("""
                    INSERT OR REPLACE INTO desktop_plugin_qq_connection
                    (id, endpoint, qq_account, robot_qq, robot_name, encrypted_token, checked_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?)
                """, (endpoint, qq_account, robot_qq, robot["name"], encrypted, checked_at))
            return self.qq_connection()

    def disconnect_qq(self):
        with self.qq_lock, closing(self._connect_db()) as db, db:
            db.execute("DELETE FROM desktop_plugin_qq_connection WHERE id = 1")

    def qq_target(self):
        with closing(self._connect_db()) as db:
            row = db.execute("SELECT robot_qq, robot_name FROM desktop_plugin_qq_profile WHERE qq_account = ''").fetchone()
        return {"robotQq": row[0], "robotName": row[1]} if row else None

    @contextmanager
    def _qq_draft_operation(self):
        if not self.qq_draft_lock.acquire(blocking=False):
            raise InventoryError("正在准备 QQ 草稿，请稍后再操作", 409)
        try:
            yield
        finally:
            self.qq_draft_lock.release()

    @staticmethod
    def _robot_name(name):
        name = name.strip()
        if len(name.splitlines()) > 1 or any(ord(char) < 32 for char in name):
            raise InventoryError("备注或昵称应为单行文字")
        return name

    def save_qq_target(self, robot_qq, robot_name):
        robot_name = self._robot_name(robot_name)
        with self._qq_draft_operation(), closing(self._connect_db()) as db, db:
            db.execute("""
                INSERT INTO desktop_plugin_qq_profile (qq_account, robot_qq, robot_name) VALUES ('', ?, ?)
                ON CONFLICT (qq_account) WHERE qq_account = '' DO UPDATE SET
                    robot_qq = excluded.robot_qq, robot_name = excluded.robot_name
            """, (robot_qq, robot_name))
        return {"robotQq": robot_qq, "robotName": robot_name}

    def qq_profiles(self):
        with closing(self._connect_db()) as db:
            rows = db.execute("""
                SELECT id, qq_account, robot_qq, robot_name, backup
                FROM desktop_plugin_qq_profile ORDER BY backup, id
            """).fetchall()
        return [{"id": id_, "qqAccount": account, "robotQq": robot, "robotName": name, "backup": bool(backup)}
                for id_, account, robot, name, backup in rows]

    def save_qq_profile(self, profile_id, qq_account, robot_qq, robot_name, backup):
        if qq_account == robot_qq:
            raise InventoryError("发送账号和机器人好友必须是两个 QQ 号")
        robot_name = self._robot_name(robot_name)
        values = (qq_account, robot_qq, robot_name, backup)
        with self._qq_draft_operation(), closing(self._connect_db()) as db, db:
            try:
                if profile_id is None:
                    profile_id = db.execute("""
                        INSERT INTO desktop_plugin_qq_profile (qq_account, robot_qq, robot_name, backup)
                        VALUES (?, ?, ?, ?)
                    """, values).lastrowid
                elif not db.execute("""
                    UPDATE desktop_plugin_qq_profile SET qq_account=?, robot_qq=?, robot_name=?, backup=? WHERE id=?
                """, (*values, profile_id)).rowcount:
                    raise InventoryError("该 QQ 配置已移除，请刷新后重试", 404)
            except sqlite3.IntegrityError as exc:
                raise InventoryError("此发送账号和机器人组合已经保存", 409) from exc
        return {"id": profile_id, "qqAccount": qq_account, "robotQq": robot_qq,
                "robotName": robot_name, "backup": backup}

    def delete_qq_profile(self, profile_id):
        with self._qq_draft_operation(), closing(self._connect_db()) as db, db:
            db.execute("DELETE FROM desktop_plugin_qq_profile WHERE id=?", (profile_id,))

    def bind_qq_account(self, account):
        with self._qq_draft_operation():
            if not any(profile["qqAccount"] == account for profile in self.qq_profiles()):
                raise InventoryError("请先保存这个发送账号的 QQ 配置", 409)
            window = bind_qq_window()
            if any(other != account and value == window for other, value in self.qq_windows.items()):
                raise InventoryError("该窗口已绑定其他账号。请切到正确的 QQ 窗口，或先解除原绑定。", 409)
            self.qq_windows[account] = window
            return self.bound_qq_accounts()

    def unbind_qq_account(self, account):
        with self._qq_draft_operation():
            self.qq_windows.pop(account, None)
            return self.bound_qq_accounts()

    def bound_qq_accounts(self):
        return list(self.qq_windows)

    def _qq_command(self, plugin_id, version, parameter_type, value, step_index, selected_target, profile_id):
        target = self.qq_target() if profile_id is None else next(
            (profile for profile in self.qq_profiles() if profile["id"] == profile_id), None
        )
        if target is None or target != selected_target:
            raise InventoryError("这组 QQ 配置已变化，请刷新插件页后重试", 409)
        steps = self.preview(plugin_id, version, parameter_type, value)
        command = steps[step_index]["command"] if step_index < len(steps) else None
        if not command or len(command.splitlines()) != 1 or any(ord(char) < 32 for char in command):
            raise InventoryError("请先在预演中生成一条有效指令")
        return target, command

    def prepare_qq_draft(self, plugin_id, version, parameter_type, value, step_index, selected_target, profile_id=None):
        with self._qq_draft_operation():
            target, command = self._qq_command(plugin_id, version, parameter_type, value, step_index, selected_target, profile_id)
            return open_qq_draft(target, command)

    @staticmethod
    def _send_fingerprint(target, command):
        return hashlib.sha256(repr((target["qqAccount"], target["robotQq"], command)).encode()).hexdigest()

    def qq_send_state(self, attempt_id):
        with closing(self._connect_db()) as db:
            row = db.execute("SELECT state FROM desktop_plugin_qq_send_attempt WHERE id=?", (attempt_id,)).fetchone()
        return {"state": row[0] if row else "not_found"}

    def send_qq(self, plugin_id, version, parameter_type, value, step_index, selected_target, attempt_id):
        with self._qq_draft_operation(), closing(self._connect_db()) as db:
            target, command = self._qq_command(plugin_id, version, parameter_type, value, step_index,
                                               selected_target, selected_target["id"])
            payload_hash = self._send_fingerprint(target, command)
            previous = db.execute("SELECT payload_hash, state FROM desktop_plugin_qq_send_attempt WHERE id=?",
                                  (attempt_id,)).fetchone()
            if previous:
                if previous[0] == payload_hash and previous[1] in SUBMITTED_STATES:
                    return {"state": previous[1]}
                raise InventoryError("这条指令已有发送尝试。请先核对 QQ 聊天记录。", 409)
            if db.execute("""
                SELECT 1 FROM desktop_plugin_qq_send_attempt WHERE payload_hash=? AND state IN ('sending', 'uncertain')
            """, (payload_hash,)).fetchone():
                raise InventoryError("这条指令有待核查的发送记录。请核对 QQ 聊天后再继续。", 409)
            window = self.qq_windows.get(target["qqAccount"])
            if not window:
                raise InventoryError("请先为这个发送账号绑定 QQ 主窗口", 409)
            repeat = db.execute("SELECT 1 FROM desktop_plugin_qq_send_attempt WHERE payload_hash=? LIMIT 1",
                                (payload_hash,)).fetchone() is not None
            with db:
                db.execute("INSERT INTO desktop_plugin_qq_send_attempt VALUES (?, ?, 'sending')", (attempt_id, payload_hash))
            try:
                result = send_qq_command(target, command, window, value=None if repeat else value.strip())
            except InventoryError as exc:
                with db:
                    db.execute("UPDATE desktop_plugin_qq_send_attempt SET state=? WHERE id=?",
                               ("uncertain" if exc.status >= 500 else "rejected", attempt_id))
                raise
            with db:
                db.execute("UPDATE desktop_plugin_qq_send_attempt SET state=? WHERE id=?", (result["state"], attempt_id))
            return result

    def clear_qq_send(self, plugin_id, version, parameter_type, value, step_index, selected_target, attempt_id=None):
        with self._qq_draft_operation(), closing(self._connect_db()) as db, db:
            target, command = self._qq_command(plugin_id, version, parameter_type, value, step_index,
                                               selected_target, selected_target["id"])
            payload_hash = self._send_fingerprint(target, command)
            if attempt_id:
                row = db.execute("SELECT payload_hash, state FROM desktop_plugin_qq_send_attempt WHERE id=?",
                                 (attempt_id,)).fetchone()
                if row and (row[0] != payload_hash or row[1] in SUBMITTED_STATES):
                    raise InventoryError("该次发送已有提交记录或与当前配置不符，请查询发送状态。", 409)
            db.execute("""
                UPDATE desktop_plugin_qq_send_attempt SET state='rejected'
                WHERE payload_hash=? AND state IN ('sending', 'uncertain')
            """, (payload_hash,))

    def _path(self, relative):
        try:
            return contained_data_path(self.root, relative)
        except ValueError as exc:
            raise InventoryError("插件目录不允许链接、目录联接或越界路径") from exc

    def _local_publisher(self):
        try:
            path = contained_data_path(self.program_root, "plugin-publisher.pub")
            public_key = read_small(path, 128).decode("ascii")
            return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key)), None
        except FileNotFoundError:
            return None, None
        except (OSError, ValueError, InventoryError):
            return None, "无法读取程序旁的 plugin-publisher.pub。使用此公钥签名的插件需要修复公钥后重试。"

    def _verify(self, files, local_publisher):
        if files.keys() != PACKAGE_FILES.keys() or any(len(files[name]) > limit for name, limit in PACKAGE_FILES.items()):
            raise InventoryError("插件包应只包含 manifest.json 和 manifest.sig")
        try:
            signature = bytes.fromhex(files["manifest.sig"].decode("ascii"))
        except ValueError as exc:
            raise InventoryError("插件签名校验失败") from exc
        try:
            manifest = Manifest.model_validate_json(files["manifest.json"])
        except ValidationError as exc:
            raise InventoryError("插件清单无效或宿主版本不兼容") from exc
        for publisher in (BUNDLED_PUBLISHER if manifest.id == BUNDLED_ID else None, local_publisher):
            if publisher is not None:
                try:
                    publisher.verify(signature, files["manifest.json"])
                    return manifest
                except InvalidSignature:
                    pass
        raise InventoryError("插件签名校验失败，请使用可信的插件包，或核对发布者公钥。")

    def _bundled(self):
        try:
            files = unpack_zip(read_small(BUNDLED_PACKAGE, UPLOAD_LIMIT))
            return files, self._verify(files, None)
        except (InventoryError, OSError) as exc:
            raise InventoryError("程序自带的球球助力插件包缺失或校验失败，请重新解压或更新桌面版。", 503) from exc

    def install_bundled(self, plugin_id):
        if plugin_id != BUNDLED_ID:
            raise InventoryError("没有此程序自带的插件", 404)
        files, _ = self._bundled()
        return self.install(files)

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
            available, packages, issues = [], [], []
            catalog_issue = None
            try:
                _, manifest = self._bundled()
                available.append(manifest.summary())
            except InventoryError as exc:
                catalog_issue = str(exc)
            publisher, publisher_issue = self._local_publisher()
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
            return {
                "available": available, "installed": packages, "issues": issues,
                "publisherIssue": publisher_issue, "catalogIssue": catalog_issue,
            }

    def install(self, files, *, inspect=False):
        with self.lock:
            publisher, _ = self._local_publisher()
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
        with self.lock, closing(self._connect_db()) as db, db:
            if enabled:
                _, digest = self._read(plugin_id, version, self._local_publisher()[0])
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
        return self.preview_batch(plugin_id, version, parameter_type, [value])[0]["steps"]

    def preview_batch(self, plugin_id, version, parameter_type, values):
        with self.lock, closing(self._connect_db()) as db:
            manifest, digest = self._read(plugin_id, version, self._local_publisher()[0])
            active = db.execute(
                "SELECT version, manifest_hash FROM desktop_plugin_activation WHERE plugin_id=?", (plugin_id,)
            ).fetchone()
            if active != (version, digest):
                raise InventoryError("请先启用此插件版本", 409)
            return [{"value": value, "steps": preview_plan(
                manifest, parameter_type, value, direct_number=digest == BUNDLED_LEGACY_MANIFEST_HASH)}
                    for value in dict.fromkeys(item.strip() for item in values)]
