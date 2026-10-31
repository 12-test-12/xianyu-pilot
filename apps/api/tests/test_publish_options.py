"""Publish through the real route and durable coordinator without platform I/O."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.routes import items
from app.models.entities import ExternalOperationAttempt
from app.services import xianyu_goods_sync
from app.services.fish_shop_publish import build_internal_item_object
from app.services.publish_options import publish_location_error


REGION = dict(prov="北京市", city="北京市", area="东城区", divisionId="110101",
              gps="116.418757,39.917544", poiName="东城区", poiId="")


@pytest_asyncio.fixture
async def publish_context(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'publish.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(ExternalOperationAttempt.__table__.create)
    calls, local_calls = [], []

    async def auth(*args):
        return SimpleNamespace(encrypted_cookie="fixture")

    def publish(self, payload):
        calls.append(self._build_publish_data(payload, {}, ["https://example.com/image.jpg"]))
        return {"success": True, "itemId": "fixture-item", "itemUrl": "https://example.com/item"}

    async def persist(*args, **kwargs):
        local_calls.append(kwargs)
        return {"localId": None}

    monkeypatch.setattr(items, "_get_account_auth", auth)
    monkeypatch.setattr(items, "decrypt_cookie_if_needed", lambda _: "fixture")
    monkeypatch.setattr(xianyu_goods_sync, "extract_token_from_cookie", lambda _: "fixture-token")
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "publish", publish)
    monkeypatch.setattr(xianyu_goods_sync, "persist_published_goods", persist)
    request = dict(xianyuAccountId=1, title="线上资料", description="通过链接交付",
                   imageUrls=["https://example.com/image.jpg"], price="9.90", stock=1,
                   shippingMode="none", freeShipping=False, supportSelfPick=False,
                   location=dict(REGION), idempotencyKey="publish-test-original-key")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield request, session, calls, local_calls
    finally:
        await engine.dispose()


def response_body(response):
    return json.loads(response.body) if hasattr(response, "body") else response.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["none", "free"])
async def test_publish_shipping_reaches_payload_and_same_key_never_republishes(publish_context, mode):
    request, session, calls, local_calls = publish_context
    request.update(shippingMode=mode, freeShipping=mode == "free")
    for _ in range(2):
        body = response_body(await items.publish_item(request, session, None))
        assert body["code"] == 200, body
        assert body["data"]["status"] == "confirmed"
    assert len(calls) == len(local_calls) == 1
    assert calls[0]["itemPostFeeDTO"]["supportFreight"] is (mode == "free")
    assert calls[0]["itemAddrDTO"]["divisionId"] == 110101
    assert calls[0]["itemAddrDTO"]["poiId"] == ""
    request["shippingMode"] = "free" if mode == "none" else "none"
    request["freeShipping"] = mode == "none"
    conflict = response_body(await items.publish_item(request, session, None))
    assert conflict["data"]["errorCode"] == "idempotency_conflict"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [dict(shippingMode="fixed"), dict(supportSelfPick=True), dict(location={}), dict(location={**REGION, "gps": "181,30"})])
async def test_invalid_options_never_reach_platform(publish_context, change):
    request, session, calls, _ = publish_context
    request.update(change)
    body = response_body(await items.publish_item(request, session, None))
    assert body["code"] != 200
    assert calls == []


@pytest.mark.asyncio
async def test_unknown_online_publish_is_never_replayed(publish_context, monkeypatch):
    request, session, calls, _ = publish_context

    def ambiguous(*args):
        calls.append("started")
        raise TimeoutError("fixture timeout")

    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "publish", ambiguous)
    for _ in range(2):
        body = response_body(await items.publish_item(request, session, None))
        assert body["data"]["status"] == "unknown"
        assert body["data"]["retrySafe"] is False
    assert calls == ["started"]


@pytest.mark.asyncio
async def test_local_repair_bypasses_new_location_validation(publish_context, monkeypatch):
    request, session, calls, local_calls = publish_context
    request["location"] = {"poiName": "旧地址"}

    async def unavailable(*args, **kwargs):
        raise OSError("fixture local failure")

    with monkeypatch.context() as previous_version:
        previous_version.setattr(items, "publish_location_error", lambda _: None)
        previous_version.setattr(xianyu_goods_sync, "persist_published_goods", unavailable)
        body = response_body(await items.publish_item(request, session, None))
        assert body["data"]["status"] == "remote_confirmed"
    body = response_body(await items.publish_item(request, session, None))
    assert body["data"]["status"] == "confirmed"
    assert len(calls) == len(local_calls) == 1


@pytest.mark.parametrize("change", [{}, {"divisionId": "台北市"}, {"gps": "NaN,30"}, {"gps": "116,91"}, {"gps": ",30"}])
def test_region_validation(change):
    region = {} if not change else {**REGION, **change}
    assert publish_location_error(region)
    assert publish_location_error(REGION) is None


def test_fish_shop_online_payload_has_no_freight_or_self_pick():
    payload = build_internal_item_object(dict(title="资料", description="线上交付", price="1", shippingMode="none", location=REGION), [], {})
    assert payload["itemPostFeeDTO"]["supportFreight"] is False
    assert not payload["itemPostFeeDTO"].get("onlyTakeSelf")
    assert payload["itemAddrDTO"]["poiId"] == ""
