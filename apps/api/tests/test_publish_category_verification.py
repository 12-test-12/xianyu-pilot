"""发布核对必须与识别阶段同构，并在两次请求间合并候选。"""
import pytest

from app.services.publish_category import (
    PublishCategoryError, merge_category_recommendations,
    parse_publish_category_recommendation, prefer_richer_error,
    resolve_publish_category,
)
from app.services.xianyu_goods_sync import XianyuItemPublisher

CATEGORY = dict(catId="91000001", catName="测试叶子分类", channelCatId="92000001", tbCatId="93000001")
DECOY = {**CATEGORY, "catId": "91000077", "channelCatId": "92000077", "catName": "干扰分类"}
COVER = "https://cdn.example.com/cover.jpg"


def recommendation(*categories):
    return {"ret": ["SUCCESS::ok"], "data": {
        "categoryPredictResult": categories[0],
        "cardList": [{"propertyName": "分类", "valuesList": [dict(c, isClicked="1") for c in categories]}],
    }}


def item(**overrides):
    return {"title": "线上资料", "description": "通过链接交付",
            "imageUrls": ["/uploads/a.jpg"],
            "categoryInfo": {**CATEGORY, "source": "xianyu"}, **overrides}


class Publisher(XianyuItemPublisher):
    """Records which request shape reached the platform."""

    cover_candidates = (DECOY,)
    meta_candidates = (CATEGORY,)

    def __init__(self, cover=COVER, cover_size=(1080, 1440)):
        self.token = "fixture"
        self._cover_cdn_url = cover
        self._cover_size = cover_size
        self._last_upload_size = None
        self.shapes = []

    def _call_api(self, api, version, data):
        if api != self.CATEGORY_RECOMMEND_API:
            raise AssertionError(f"unexpected api {api}")
        self.shapes.append("imageInfos" if "imageInfos" in data else "itemInfo")
        return recommendation(*self.cover_candidates if "imageInfos" in data else self.meta_candidates)


def test_verification_reuses_the_identification_request_shape():
    publisher = Publisher()
    publisher.cover_candidates = (CATEGORY,)
    resolved = publisher.resolve_category_for_publish(item())
    assert publisher.shapes == ["imageInfos"]
    assert resolved["catId"] == CATEGORY["catId"]


def test_verification_without_an_uploaded_cover_uses_metadata_shape():
    publisher = Publisher(cover="", cover_size=None)
    publisher.resolve_category_for_publish(item())
    assert publisher.shapes == ["itemInfo"]


def test_second_shape_rescues_a_category_the_first_shape_missed():
    publisher = Publisher()
    publisher.cover_candidates = (DECOY,)
    publisher.meta_candidates = (CATEGORY,)
    resolved = publisher.resolve_category_for_publish(item())
    assert publisher.shapes == ["imageInfos", "itemInfo"]
    assert resolved["catId"] == CATEGORY["catId"]


def test_both_shapes_missing_still_refuses_with_merged_candidates():
    publisher = Publisher()
    publisher.cover_candidates = (DECOY,)
    publisher.meta_candidates = (DECOY,)
    with pytest.raises(PublishCategoryError) as error:
        publisher.resolve_category_for_publish(item(categoryInfo={"catId": "91000999", "catName": "已失效分类", "source": "xianyu"}))
    payload = error.value.to_data()
    assert payload["categoryRefreshRequired"] is True
    assert payload["categoryCandidates"], payload


def test_merge_widens_candidates_without_retargeting_the_selection():
    primary = parse_publish_category_recommendation(recommendation(DECOY))
    secondary = parse_publish_category_recommendation(recommendation(CATEGORY))
    merged = merge_category_recommendations(primary, secondary)
    assert merged["catId"] == DECOY["catId"]
    assert merged["candidates"][0]["catId"] == DECOY["catId"]
    assert {cat["catId"] for cat in merged["candidates"]} == {DECOY["catId"], CATEGORY["catId"]}
    assert resolve_publish_category({**CATEGORY, "source": "xianyu"}, merged)["catId"] == CATEGORY["catId"]


def test_richer_refusal_wins_so_the_ui_gets_actionable_choices():
    def refusal(candidates):
        error = PublishCategoryError("分类未在候选中", candidates=candidates)
        return error

    poor, rich = refusal([DECOY]), refusal([DECOY, CATEGORY])
    assert prefer_richer_error(poor, rich) is rich
    assert prefer_richer_error(rich, poor) is rich
    assert prefer_richer_error(rich, None) is rich
    assert prefer_richer_error(None, rich) is rich
    assert prefer_richer_error(Exception("plain"), rich) is rich


def test_category_recommend_accepts_flexible_signatures_and_safely_falls_back():
    publisher = Publisher()
    # Call without keywords (metadata shape)
    res = publisher.category_recommend("title", "desc", ["http://example.com/a.jpg"])
    assert res["recommended"] is True
    # Call with positional cover (identification shape)
    res = publisher.category_recommend("title", "desc", ["http://example.com/a.jpg"], COVER, (1080, 1080))
    assert res["recommended"] is True


def test_batch_upload_pins_the_cover_and_keeps_its_real_size():
    publisher = Publisher()
    sizes = iter([(1080, 1440), (800, 600), (640, 480)])

    def upload(url):
        publisher._last_upload_size = next(sizes)
        return f"https://cdn.example.com/{url.rsplit('/', 1)[-1]}"

    publisher.upload_image_to_xianyu = upload
    urls = publisher.upload_images_to_xianyu(["/uploads/a.jpg", "/uploads/b.jpg", "/uploads/c.jpg"])
    assert urls[0] == COVER.replace("cover", "a")
    assert publisher._cover_cdn_url == urls[0]
    assert publisher._cover_size == (1080, 1440)
    assert publisher._last_upload_size == (640, 480)
