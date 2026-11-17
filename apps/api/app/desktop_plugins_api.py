"""Authenticated loopback API for the desktop plugin manager."""
import base64
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.concurrency import run_in_threadpool

from app.api.v1.deps import get_current_user
from app.core.response import ResultObject
from app.desktop_inventory_api import local_write_boundary
from app.services.desktop_inventory import InventoryError
from app.services.desktop_plugins import ID_PATTERN, UPLOAD_LIMIT, VERSION_PATTERN, ParameterType, unpack_zip
from app.services.qq_bridge.onebot import QQ_ID_PATTERN

router = APIRouter(
    prefix="/api/desktop/plugins",
    dependencies=[Depends(get_current_user), Depends(local_write_boundary)],
)
PluginId = Annotated[str, Path(pattern=ID_PATTERN)]
PluginVersion = Annotated[str, Path(pattern=VERSION_PATTERN)]
QQAccount = Annotated[str, Path(min_length=5, max_length=20, pattern=QQ_ID_PATTERN)]


class EnableBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    enabled: bool


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameterType: ParameterType
    value: str = Field(min_length=1, max_length=500)


class BatchPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameterType: ParameterType
    values: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(min_length=1, max_length=50)


class QQConnectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(min_length=1, max_length=100)
    qqAccount: str = Field(pattern=QQ_ID_PATTERN)
    robotQq: str = Field(pattern=QQ_ID_PATTERN)
    accessToken: SecretStr = SecretStr("")


class QQTargetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robotQq: str = Field(min_length=5, max_length=20, pattern=QQ_ID_PATTERN)
    robotName: str = Field(default="", max_length=80)


class QQProfileBody(QQTargetBody):
    qqAccount: str = Field(min_length=5, max_length=20, pattern=QQ_ID_PATTERN)
    backup: bool = Field(default=False, strict=True)


class QQProfileSelection(QQProfileBody):
    id: int = Field(gt=0, strict=True)
    qqAccount: str = Field(pattern=r"^([1-9][0-9]{4,19})?$")


class QQDraftBody(PreviewBody):
    target: QQProfileSelection | QQTargetBody
    stepIndex: int = Field(strict=True, ge=0, le=2)


class QQSendSelection(QQDraftBody):
    target: QQProfileSelection


class QQSendBody(QQSendSelection):
    attemptId: str = Field(pattern=r"^qq-send-[a-f0-9-]{32,36}$")


def store(request: Request):
    return request.app.state.desktop_plugins


def perform(operation, *args, **kwargs):
    try:
        return ResultObject.success(operation(*args, **kwargs))
    except OSError as exc:
        raise InventoryError("无法访问本地插件目录，请检查权限或文件占用后重试", 503) from exc


async def package_payload(request: Request):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"application/zip", "application/json"}:
        raise InventoryError("请选择 ZIP 插件包或插件文件夹", 415)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > UPLOAD_LIMIT:
            raise InventoryError("插件包不能超过 64 KB", 413)
        data.extend(chunk)
    if content_type == "application/zip":
        return unpack_zip(data)
    try:
        files = json.loads(data)
        if not isinstance(files, dict):
            raise ValueError("expected filename map")
        return {name: base64.b64decode(value, validate=True) for name, value in files.items()}
    except (ValueError, TypeError, RecursionError) as exc:
        raise InventoryError("插件文件夹格式无效") from exc


@router.get("")
def plugins(request: Request):
    return perform(store(request).status)


@router.get("/qq/connection")
def qq_connection(request: Request):
    return perform(store(request).qq_connection)


@router.put("/qq/connection")
def connect_qq(request: Request, body: QQConnectionBody):
    return perform(store(request).connect_qq, body.endpoint, body.qqAccount, body.robotQq,
                   body.accessToken.get_secret_value())


@router.delete("/qq/connection")
def disconnect_qq(request: Request):
    return perform(store(request).disconnect_qq)


@router.get("/qq/target")
def qq_target(request: Request):
    return perform(store(request).qq_target)


@router.put("/qq/target")
def save_qq_target(request: Request, body: QQTargetBody):
    return perform(store(request).save_qq_target, body.robotQq, body.robotName)


@router.get("/qq/profiles")
def qq_profiles(request: Request):
    return perform(store(request).qq_profiles)


@router.post("/qq/profiles")
def add_qq_profile(request: Request, body: QQProfileBody):
    return perform(store(request).save_qq_profile, None, body.qqAccount, body.robotQq, body.robotName, body.backup)


@router.put("/qq/profiles/{profile_id}")
def update_qq_profile(request: Request, profile_id: Annotated[int, Path(gt=0)], body: QQProfileBody):
    return perform(store(request).save_qq_profile, profile_id, body.qqAccount, body.robotQq, body.robotName, body.backup)


@router.delete("/qq/profiles/{profile_id}")
def delete_qq_profile(request: Request, profile_id: Annotated[int, Path(gt=0)]):
    return perform(store(request).delete_qq_profile, profile_id)


@router.get("/qq/windows")
def bound_qq_accounts(request: Request):
    return perform(store(request).bound_qq_accounts)


@router.put("/qq/windows/{account}")
def bind_qq_account(request: Request, account: QQAccount):
    return perform(store(request).bind_qq_account, account)


@router.delete("/qq/windows/{account}")
def unbind_qq_account(request: Request, account: QQAccount):
    return perform(store(request).unbind_qq_account, account)


@router.post("/package/inspect")
async def inspect_package(request: Request):
    files = await package_payload(request)
    return await run_in_threadpool(perform, store(request).install, files, inspect=True)


@router.post("/package")
async def install_package(request: Request):
    files = await package_payload(request)
    return await run_in_threadpool(perform, store(request).install, files)


@router.post("/catalog/{plugin_id}/install")
def install_bundled(request: Request, plugin_id: PluginId):
    return perform(store(request).install_bundled, plugin_id)


@router.patch("/{plugin_id}/{version}")
def set_enabled(request: Request, plugin_id: PluginId, version: PluginVersion, body: EnableBody):
    return perform(store(request).set_enabled, plugin_id, version, body.enabled)


@router.delete("/{plugin_id}/{version}")
def uninstall(request: Request, plugin_id: PluginId, version: PluginVersion):
    return perform(store(request).uninstall, plugin_id, version)


@router.post("/{plugin_id}/{version}/preview")
def preview(request: Request, plugin_id: PluginId, version: PluginVersion, body: PreviewBody):
    return perform(store(request).preview, plugin_id, version, body.parameterType, body.value)


@router.post("/{plugin_id}/{version}/preview-batch")
def preview_batch(request: Request, plugin_id: PluginId, version: PluginVersion, body: BatchPreviewBody):
    return perform(store(request).preview_batch, plugin_id, version, body.parameterType, body.values)


@router.post("/{plugin_id}/{version}/qq-draft")
def prepare_qq_draft(request: Request, plugin_id: PluginId, version: PluginVersion, body: QQDraftBody):
    return perform(store(request).prepare_qq_draft, plugin_id, version, body.parameterType, body.value,
                   body.stepIndex, body.target.model_dump(), getattr(body.target, "id", None))


@router.post("/{plugin_id}/{version}/qq-send")
def send_qq(request: Request, plugin_id: PluginId, version: PluginVersion, body: QQSendBody):
    return perform(store(request).send_qq, plugin_id, version, body.parameterType, body.value,
                   body.stepIndex, body.target.model_dump(), body.attemptId)


@router.post("/{plugin_id}/{version}/qq-send/clear")
def clear_qq_send(request: Request, plugin_id: PluginId, version: PluginVersion, body: QQSendSelection):
    return perform(store(request).clear_qq_send, plugin_id, version, body.parameterType, body.value,
                   body.stepIndex, body.target.model_dump())
