import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from app.api.v1.routes import fish_shop
from app.services import fish_shop_publish, xianyu_goods_sync
from app.services.publish_category import PublishCategoryError

CATEGORY = dict(catId="91000001", catName="测试叶子分类", channelCatId="92000001", tbCatId="93000001")
OTHER = {**CATEGORY, "catId": "91000999", "channelCatId": "92000999"}


def test_fish_shop_edit_and_readback_use_web_contract(monkeypatch):
    calls = []
    monkeypatch.setattr(fish_shop_publish, "_refresh_m_h5_tk", lambda cookie: cookie)
    monkeypatch.setattr(fish_shop_publish, "extract_token_from_cookie", lambda _: "fixture")

    def post(url, *, headers, data, timeout):
        endpoint = urlsplit(url)
        query = parse_qs(endpoint.query)
        assert headers["Origin"] == "https://www.goofish.com"
        assert query["type"] == ["originaljson"]
        assert query["sign"] == [fish_shop_publish.build_sign("fixture", query["t"][0], data["data"])]
        calls.append((endpoint.path, json.loads(data["data"])))
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                               json=lambda: {"ret": ["SUCCESS::调用成功"], "data": {"itemId": "101"}})

    monkeypatch.setattr(requests, "post", post)
    item = {"itemId": "101", "itemTextDTO": {"title": "新标题"}, "itemSkuList": [{"quantity": "0"}]}
    fish_shop_publish.call_fish_shop_api("fixture", fish_shop_publish.FISH_SHOP_EDIT_API, "1.0", item, is_edit=True)
    fish_shop_publish.call_fish_shop_edit_detail("fixture", "101")
    assert calls == [
        ("/h5/mtop.idle.pc.idleitem.edit/1.0/", item),
        ("/h5/mtop.idle.pc.idleitem.editDetail/1.0/", {"itemId": "101"}),
    ]


def test_explicit_fish_shop_category_refusal_carries_the_rejected_category(monkeypatch):
    monkeypatch.setattr(fish_shop_publish, "extract_token_from_cookie", lambda _: "fixture")
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"ret": ["FAIL_BIZ_CATEGORY_DISPOSED::类目废弃"], "data": {}})
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)
    with pytest.raises(PublishCategoryError) as error:
        fish_shop_publish.call_fish_shop_api("fixture", fish_shop_publish.FISH_SHOP_PUBLISH_API, "1.0", {"itemCatDTO": CATEGORY})
    assert error.value.rejected_category == CATEGORY


@pytest.mark.asyncio
async def test_fish_shop_route_refreshes_choices_after_refusal_without_republishing(monkeypatch):
    calls, rollbacks = [], []

    async def auth(*args):
        return SimpleNamespace(encrypted_cookie="fixture"), True

    async def rollback():
        rollbacks.append(True)

    def rejected(*args, **kwargs):
        calls.append("publish")
        raise PublishCategoryError("类目已废弃", rejected_category=CATEGORY)

    def refresh(self, request, rejected):
        assert rejected == CATEGORY
        calls.append("refresh")
        return {"categoryRefreshRequired": True, "categoryCandidates": [OTHER]}

    monkeypatch.setattr(fish_shop, "_get_account_auth_and_check_fish_shop", auth)
    monkeypatch.setattr(fish_shop, "decrypt_cookie_if_needed", lambda _: "fixture")
    monkeypatch.setattr(fish_shop, "extract_token_from_cookie", lambda _: "fixture")
    monkeypatch.setattr(xianyu_goods_sync, "extract_token_from_cookie", lambda _: "fixture")
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "resolve_category_for_publish", lambda *args: CATEGORY)
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "upload_images_to_xianyu", lambda *args: ["https://example.com/image.jpg"])
    monkeypatch.setattr(xianyu_goods_sync.XianyuItemPublisher, "refresh_rejected_category", refresh)
    monkeypatch.setattr(fish_shop, "call_fish_shop_api", rejected)
    request = {
        "xianyuAccountId": 1, "title": "测试", "description": "描述", "imageUrls": ["https://example.com/image.jpg"],
        "itemProperties": [{"propertyName": "颜色", "propertyValues": [{"propertyValue": "红色"}]}],
        "itemSkuList": [{"price": "1", "quantity": 1, "propertyList": [{"propertyText": "颜色", "valueText": "红色"}]}],
        "shippingMode": "none", "location": dict(prov="北京市", city="北京市", area="东城区", divisionId="110101", gps="116.4,39.9", poiName="东城区"),
    }
    response = await fish_shop.publish_fish_shop_item(request, SimpleNamespace(rollback=rollback), None)
    body = response.model_dump()
    assert body["data"]["status"] == "failed"
    assert body["data"]["retrySafe"] is True
    assert body["data"]["categoryCandidates"][0]["catId"] == OTHER["catId"]
    assert calls == ["publish", "refresh"]
    assert rollbacks == [True]
