"""Authenticated loopback API for the desktop plugin manager."""
import base64
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.api.v1.deps import get_current_user
from app.core.response import ResultObject
from app.desktop_inventory_api import local_write_boundary
from app.services.desktop_inventory import InventoryError
from app.services.desktop_plugins import ID_PATTERN, UPLOAD_LIMIT, VERSION_PATTERN, ParameterType, unpack_zip

router = APIRouter(
    prefix="/api/desktop/plugins",
    dependencies=[Depends(get_current_user), Depends(local_write_boundary)],
)
PluginId = Annotated[str, Path(pattern=ID_PATTERN)]
PluginVersion = Annotated[str, Path(pattern=VERSION_PATTERN)]


class EnableBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    enabled: bool


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameterType: ParameterType
    value: str = Field(min_length=1, max_length=500)


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
