import pytest

from app.services.publish_category import (
    PublishCategoryError, normalize_publish_category,
    parse_publish_category_recommendation, resolve_publish_category,
    same_category,
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
    with pytest.raises(PublishCategoryError):
        resolve_publish_category(OTHER, result)
    assert normalize_publish_category(resolve_publish_category(OTHER, {**result, "candidates": [CATEGORY, OTHER]})) == OTHER
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


def test_ids_can_change_repeatedly_without_changing_the_selected_category():
    preferred = {**CATEGORY, "categoryPath": ["服务", CATEGORY["catName"]], "source": "xianyu"}
    for revision in range(10):
        live = {**CATEGORY, "catId": str(91000100 + revision), "channelCatId": str(92000100 + revision), "categoryPath": preferred["categoryPath"]}
        resolved = resolve_publish_category(preferred, {**live, "recommended": True})
        assert normalize_publish_category(resolved) == normalize_publish_category(live)
        assert preferred["catId"] == CATEGORY["catId"]


@pytest.mark.parametrize("change", ["missing", "renamed", "ambiguous", "path_changed"])
def test_removed_or_ambiguous_categories_are_never_silently_retargeted(change):
    preferred = {**CATEGORY, "source": "xianyu", "categoryPath": ["服务", CATEGORY["catName"]]}
    live = {**CATEGORY, "catId": "91000999", "categoryPath": preferred["categoryPath"]}
    result = {"recommended": False, "candidates": [live]}
    if change == "missing":
        result = {"recommended": False, "candidates": []}
    elif change == "renamed":
        live.update(catName="已更名", categoryPath=["服务", "已更名"])
    elif change == "ambiguous":
        result["candidates"].append({**live, "catId": "91000888"})
    else:
        live["categoryPath"] = ["另一父分类", CATEGORY["catName"]]
    with pytest.raises(PublishCategoryError) as error:
        resolve_publish_category(preferred, result)
    assert error.value.to_data()["categoryRefreshRequired"] is True


def test_identical_platform_ids_survive_a_moved_display_path():
    # catId/channelCatId are the platform's own identity; a renamed parent path
    # must not turn the same category into an unconfirmable selection.
    preferred = {**CATEGORY, "source": "xianyu", "categoryPath": ["服务", "旧父分类", CATEGORY["catName"]]}
    live = {**CATEGORY, "categoryPath": ["服务", "新父分类", CATEGORY["catName"]]}
    resolved = resolve_publish_category(preferred, {"recommended": False, "candidates": [live]})
    assert normalize_publish_category(resolved) == CATEGORY


def test_local_tree_selection_is_refused_for_missing_platform_ids():
    local = {"id": 5893, "catName": "本地分类", "source": "local", "categoryPath": ["本地分类"]}
    with pytest.raises(PublishCategoryError) as error:
        resolve_publish_category(local, {"recommended": False, "candidates": [OTHER]})
    assert "平台类目 ID" in str(error.value) and "重新识别分类" in str(error.value)
    candidates = error.value.to_data()["categoryCandidates"]
    assert [candidate["catId"] for candidate in candidates] == [OTHER["catId"]]


def test_unavailable_recommendation_is_reported_apart_from_a_stale_selection():
    with pytest.raises(PublishCategoryError) as error:
        resolve_publish_category(CATEGORY, {"recommended": False, "candidates": []})
    assert "未能获取平台最新的分类候选" in str(error.value)
    assert error.value.to_data()["categoryRefreshFailed"] is True


def test_same_category_is_symmetric_and_respects_shared_keys():
    a = {"catId": "91000001", "channelCatId": "92000001"}
    b = {"catId": "91000001"}
    assert same_category(a, b) is True
    assert same_category(b, a) is True

    c = {"catId": "91000001", "channelCatId": "92000002"}
    assert same_category(a, c) is False
    assert same_category(c, a) is False

    d = {"catId": "91000002", "channelCatId": "92000001"}
    assert same_category(a, d) is False
    assert same_category(d, a) is False

    assert same_category({}, a) is False
    assert same_category(None, a) is False


def test_fish_shop_publish_snapshot_preserves_resolved_category():
    from app.api.v1.routes.fish_shop import _build_publish_snapshot
    internal_obj = {"itemCatDTO": CATEGORY}
    req = {"title": "测试商品", "price": "10", "categoryInfo": {"catName": "原始分类"}}
    snapshot = _build_publish_snapshot(req, internal_obj, [{"priceInCent": 1000}])
    assert snapshot["category"] == CATEGORY
    assert snapshot["categoryInfo"] == CATEGORY
