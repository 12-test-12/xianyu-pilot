import pytest

from app.services.publish_category import (
    PublishCategoryError, normalize_publish_category,
    parse_publish_category_recommendation, resolve_publish_category,
)
from app.services.auto_category import select_best_category
from app.services.fish_shop_publish import build_internal_item_object
from app.services.xianyu_goods_sync import XianyuItemPublisher

CATEGORY = dict(catId="91000001", catName="测试叶子分类", channelCatId="92000001", tbCatId="93000001")
OTHER = {**CATEGORY, "catId": "91000002", "channelCatId": "92000002", "catName": "另一分类"}


@pytest.mark.parametrize("prediction", [CATEGORY, [CATEGORY]])
def test_object_and_list_predictions_preserve_all_ids(prediction):
    result = parse_publish_category_recommendation({"ret": ["SUCCESS::ok"], "data": {"categoryPredictResult": prediction}})
    assert result["recommended"] is True
    assert normalize_publish_category(result) == CATEGORY
    chosen = select_best_category({"ret": ["SUCCESS::ok"], "data": {"categoryPredictResult": prediction}})
    assert normalize_publish_category(chosen["category"]) == CATEGORY


def test_category_card_supplies_details_for_matching_prediction_not_shared_tb_id():
    result = {"ret": ["SUCCESS::ok"], "data": {
        "categoryPredictResult": {"catId": CATEGORY["catId"], "tbCatId": CATEGORY["tbCatId"]},
        "cardList": [{"cardData": {"propertyName": "分类", "valuesList": [OTHER, CATEGORY]}}],
    }}
    assert normalize_publish_category(parse_publish_category_recommendation(result)) == CATEGORY
    assert select_best_category(result)["category"]["catId"] == CATEGORY["catId"]


@pytest.mark.parametrize("data", [{}, {"categoryPredictResult": {}}, {"categoryPredictResult": {"catName": "缺少ID"}}, {"categoryPredictResult": {**CATEGORY, "isLeaf": False}}])
def test_empty_or_parent_prediction_is_not_a_success(data):
    result = parse_publish_category_recommendation({"ret": ["SUCCESS::ok"], "data": data})
    assert result["recommended"] is False
    with pytest.raises(PublishCategoryError):
        resolve_publish_category(None, result)


def test_explicit_candidate_is_preserved_and_local_ids_are_never_used_as_platform_ids():
    result = {**CATEGORY, "recommended": True, "candidates": [CATEGORY]}
    assert normalize_publish_category(resolve_publish_category(OTHER, result)) == OTHER
    assert normalize_publish_category(resolve_publish_category({"catName": CATEGORY["catName"], "source": "local", "catId": "50025461"}, result)) == CATEGORY
    with pytest.raises(PublishCategoryError):
        resolve_publish_category({"id": 5893, "catName": "失效的本地名称"}, result)


@pytest.mark.parametrize("category", [{}, {"id": 5893, "catName": "本地节点"}, {**CATEGORY, "isLeaf": False}])
def test_payload_builders_cannot_invent_a_default_category(category):
    publisher = object.__new__(XianyuItemPublisher)
    with pytest.raises(PublishCategoryError):
        publisher._build_publish_data({"title": "测试", "price": "1"}, category, [])
    with pytest.raises(PublishCategoryError):
        build_internal_item_object({"title": "测试"}, [], category)


def test_absent_optional_ids_stay_empty_in_both_payloads():
    category = {"catId": "91000001", "catName": "测试叶子分类"}
    publisher = object.__new__(XianyuItemPublisher)
    ordinary = publisher._build_publish_data({"title": "测试", "price": "1"}, category, [])
    fish = build_internal_item_object({"title": "测试"}, [], category)
    assert ordinary["itemCatDTO"] == fish["itemCatDTO"] == {**category, "channelCatId": "", "tbCatId": ""}
