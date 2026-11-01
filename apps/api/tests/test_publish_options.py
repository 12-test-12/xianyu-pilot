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
from app.services.category_cache import CategoryCache, category_scope

REAL_PUBLISH = xianyu_goods_sync.XianyuItemPublisher.publish
REAL_CATEGORY_RECOMMEND = xianyu_goods_sync.XianyuItemPublisher.category_recommend
CATEGORY = dict(catId="91000001", catName="测试叶子分类", channelCatId="92000001", tbCatId="93000001")


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
        calls.append(self._build_publish_data(payload, payload.get("category") or CATEGORY, ["https://example.com/image.jpg"]))
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


def mock_platform_receipts(monkeypatch, receipts, calls):
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "publish", REAL_PUBLISH)
    monkeypatch.setattr(xianyu_goods_sync, "_refresh_m_h5_tk", lambda cookie: cookie)
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "category_recommend", lambda *args: {**CATEGORY, "recommended": True})
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "upload_images_to_xianyu", lambda *args: ["https://example.com/image.jpg"])

    def receipt(*args):
        calls.append("remote")
        return receipts.pop(0)

    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "_call_api", receipt)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["FAIL_BIZ_STRONG_VALID_VERIFY_INFO", "FAIL_BIZ_ITEM_TITLE_VIOLATION", "FAIL_BIZ_USER_NOT_REALNAME"])
async def test_explicit_refusal_can_retry_original_key_after_remediation(publish_context, monkeypatch, code):
    request, session, calls, local_calls = publish_context
    mock_platform_receipts(monkeypatch, [
        {"ret": [f"{code}::未签署相关认证协议"], "data": {}},
        {"ret": ["SUCCESS::调用成功"], "data": {"itemId": "after-remediation"}},
    ], calls)
    body = response_body(await items.publish_item(request, session, None))
    assert body["data"]["status"] == "failed"
    assert body["data"]["retrySafe"] is True
    assert not local_calls
    if code == "FAIL_BIZ_STRONG_VALID_VERIFY_INFO":
        assert "同一账号" in body["msg"] and "协议签署" in body["msg"]
    for _ in range(2):
        body = response_body(await items.publish_item(request, session, None))
        assert body["data"]["status"] == "confirmed"
    assert calls == ["remote", "remote"]
    assert len(local_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("saved_state", ["failed", "unknown"])
async def test_previously_locked_auth_refusal_recovers_with_original_key(publish_context, monkeypatch, saved_state):
    request, session, calls, _ = publish_context
    mock_platform_receipts(monkeypatch, [
        {"ret": ["FAIL_BIZ_STRONG_VALID_VERIFY_INFO::未签署相关认证协议"], "data": {}},
        {"ret": ["SUCCESS::调用成功"], "data": {"itemId": "recovered"}},
    ], calls)
    body = response_body(await items.publish_item(request, session, None))
    attempt = await session.get(ExternalOperationAttempt, body["data"]["attemptId"])
    attempt.retry_safe = 0  # Persisted by the previous release.
    attempt.state = saved_state
    await session.commit()
    body = response_body(await items.publish_item(request, session, None))
    assert body["data"]["status"] == ("confirmed" if saved_state == "failed" else "unknown")
    assert calls == (["remote", "remote"] if saved_state == "failed" else ["remote"])


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", [{}, {"ret": ["SUCCESS::调用成功"], "data": {}}, {"ret": ["FAIL_SYS_UNKNOWN::unknown"], "data": {}}])
async def test_missing_or_ambiguous_receipt_never_republishes(publish_context, monkeypatch, receipt):
    request, session, calls, local_calls = publish_context
    mock_platform_receipts(monkeypatch, [receipt], calls)
    for _ in range(2):
        body = response_body(await items.publish_item(request, session, None))
        assert body["data"]["status"] == "unknown"
        assert body["data"]["retrySafe"] is False
    assert calls == ["remote"]
    assert not local_calls


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
    payload = build_internal_item_object(dict(title="资料", description="线上交付", price="1", shippingMode="none", location=REGION), [], CATEGORY)
    assert payload["itemPostFeeDTO"]["supportFreight"] is False
    assert not payload["itemPostFeeDTO"].get("onlyTakeSelf")
    assert payload["itemAddrDTO"]["poiId"] == ""


@pytest.mark.asyncio
async def test_category_metadata_reaches_publish_without_default_ids(publish_context):
    request, session, calls, _ = publish_context
    request.update(category=CATEGORY["catName"], categoryInfo={**CATEGORY, "source": "xianyu", "isLeaf": True})
    body = response_body(await items.publish_item(request, session, None))
    assert body["data"]["status"] == "confirmed"
    assert calls[0]["itemCatDTO"] == CATEGORY


@pytest.mark.asyncio
async def test_object_recommendation_replaces_old_default_before_publish(publish_context, monkeypatch):
    request, session, calls, _ = publish_context
    mock_platform_receipts(monkeypatch, [], calls)
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "category_recommend", REAL_CATEGORY_RECOMMEND)
    request["category"] = CATEGORY["catName"]

    def call(self, api, version, payload):
        if api == self.CATEGORY_RECOMMEND_API:
            return {"ret": ["SUCCESS::ok"], "data": {"categoryPredictResult": CATEGORY}}
        calls.append(payload)
        return {"ret": ["SUCCESS::ok"], "data": {"itemId": "valid-category"}}

    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "_call_api", call)
    body = response_body(await items.publish_item(request, session, None))
    assert body["data"]["status"] == "confirmed"
    assert calls[0]["itemCatDTO"] == CATEGORY


@pytest.mark.asyncio
async def test_no_valid_category_stops_before_remote_publish_and_allows_editing(publish_context, monkeypatch):
    request, session, calls, local_calls = publish_context
    mock_platform_receipts(monkeypatch, [], calls)
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "category_recommend", lambda *args: {"recommended": False})
    request["category"] = "旧的分类名称"
    body = response_body(await items.publish_item(request, session, None))
    assert body["data"]["status"] == "failed"
    assert body["data"]["retrySafe"] is True
    assert "重新识别分类" in body["msg"]
    assert calls == local_calls == []


@pytest.mark.asyncio
async def test_disposed_category_invalidates_cache_and_refreshes_choices_without_republishing(publish_context, monkeypatch, tmp_path):
    request, session, calls, local_calls = publish_context
    mock_platform_receipts(monkeypatch, [], calls)
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "category_recommend", REAL_CATEGORY_RECOMMEND)
    cache = CategoryCache(tmp_path / "categories.sqlite3")
    monkeypatch.setattr(xianyu_goods_sync, "desktop_category_cache", lambda: cache)
    cache.put(category_scope(1), "cover", {"success": True, "selectedCategory": CATEGORY, "candidates": [CATEGORY]})
    latest = {**CATEGORY, "catId": "91000999", "channelCatId": "92000999"}
    category_queries = []

    def call(self, api, version, payload):
        if api == self.CATEGORY_RECOMMEND_API:
            current = CATEGORY if not calls else latest
            category_queries.append(current)
            return {"ret": ["SUCCESS::ok"], "data": {"categoryPredictResult": current}}
        calls.append(payload)
        if len(calls) == 1:
            return {"ret": ["FAIL_BIZ_CATEGORY_DISPOSED::类目已废弃"], "data": {}}
        return {"ret": ["SUCCESS::ok"], "data": {"itemId": "after-category-refresh"}}

    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "_call_api", call)
    request.update(category=CATEGORY["catName"], categoryInfo={**CATEGORY, "source": "xianyu"})
    body = response_body(await items.publish_item(request, session, None))
    assert body["data"]["status"] == "failed"
    assert body["data"]["retrySafe"] is True
    assert body["data"]["categoryRefreshRequired"] is True
    assert body["data"]["categoryCandidates"][0]["catId"] == latest["catId"]
    assert len(calls) == 1 and not local_calls
    assert len(category_queries) == 2
    assert cache.get(category_scope(1), "cover") is None
    # Explicitly selecting a new candidate creates a new user intent.
    request.update(categoryInfo={**latest, "source": "xianyu"}, idempotencyKey="new-category-intent")
    for _ in range(2):
        body = response_body(await items.publish_item(request, session, None))
        assert body["data"]["status"] == "confirmed"
    assert calls[-1]["itemCatDTO"] == latest
    assert len(category_queries) == 3  # A platform write revalidates live IDs and labels.
    assert len(calls) == 2 and len(local_calls) == 1


@pytest.mark.asyncio
async def test_removed_selection_returns_live_choices_without_publishing(publish_context, monkeypatch):
    request, session, calls, local_calls = publish_context
    mock_platform_receipts(monkeypatch, [], calls)
    request.update(category="已删除的分类", categoryInfo={"catId": "91000888", "catName": "已删除的分类", "source": "xianyu"})
    body = response_body(await items.publish_item(request, session, None))
    assert body["data"]["status"] == "failed"
    assert body["data"]["categoryCandidates"][0]["catId"] == CATEGORY["catId"]
    assert not calls and not local_calls


@pytest.mark.asyncio
async def test_timeout_does_not_refresh_categories_or_retry_publish(publish_context, monkeypatch):
    request, session, calls, _ = publish_context
    mock_platform_receipts(monkeypatch, [], calls)

    def timeout(*args):
        calls.append("publish-started")
        raise TimeoutError("fixture")

    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "_call_api", timeout)
    for _ in range(2):
        body = response_body(await items.publish_item(request, session, None))
        assert body["data"]["status"] == "unknown"
        assert "categoryRefreshRequired" not in body["data"]
    assert calls == ["publish-started"]
