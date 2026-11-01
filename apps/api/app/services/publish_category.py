"""Preserve marketplace category IDs; local tree IDs are display identifiers."""
from __future__ import annotations


class PublishCategoryError(RuntimeError):
    pass


def normalize_publish_category(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    if value.get("isLeaf") in (False, "false", "0", 0) or value.get("children"):
        return {}
    result = {key: str(value.get(key) or "").strip()
              for key in ("catId", "catName", "channelCatId", "tbCatId")}
    result["catName"] = str(value.get("catName") or value.get("name") or "").strip()
    if not result["catId"].isascii() or not result["catId"].isdigit() or int(result["catId"]) <= 0 or not result["catName"]:
        return {}
    # Never fill absent IDs from an unrelated category.
    return result


def category_request(req: dict) -> dict:
    details = req.get("categoryInfo")
    if isinstance(details, dict):
        return dict(details)
    category = req.get("category")
    return dict(category) if isinstance(category, dict) else {"catName": str(category or "").strip()}


def same_category(preferred: dict, candidate: dict) -> bool:
    # tbCatId can be shared by multiple idle-marketplace categories.
    keys = [key for key in ("catId", "channelCatId") if preferred.get(key)]
    return bool(keys) and all(str(preferred[key]) == str(candidate.get(key) or "") for key in keys)


def parse_publish_category_recommendation(result: object) -> dict:
    empty = {"recommended": False, "candidates": [], "cardList": []}
    if not isinstance(result, dict):
        return empty
    ret = result.get("ret")
    if not isinstance(ret, list) or not any(str(item).partition("::")[0] == "SUCCESS" for item in ret):
        return empty
    data = result.get("data")
    if not isinstance(data, dict):
        return empty
    cards = data.get("cardList") or []
    if isinstance(cards, dict):
        cards = [cards]
    if not isinstance(cards, list):
        cards = []
    cards = [card.get("cardData") or card for card in cards if isinstance(card, dict)]
    cards = [card for card in cards if isinstance(card, dict)]
    candidates, clicked = [], None
    for card in cards:
        if card.get("propertyName") != "分类":
            continue
        values = card.get("valuesList") or []
        for value in values if isinstance(values, list) else []:
            category = normalize_publish_category(value)
            if category:
                candidates.append(category)
                if str(value.get("isClicked")) == "1":
                    clicked = category
    predictions = data.get("categoryPredictResult") or []
    if isinstance(predictions, dict):
        predictions = [predictions]
    selected = None
    for prediction in predictions if isinstance(predictions, list) else []:
        if not isinstance(prediction, dict):
            continue
        if prediction.get("isLeaf") in (False, "false", "0", 0) or prediction.get("children"):
            continue
        matched = next((cat for cat in candidates if same_category(prediction, cat)), None)
        selected = matched or normalize_publish_category(prediction)
        if selected:
            break
    selected = selected or clicked
    if selected and selected not in candidates:
        candidates.insert(0, selected)
    return {**(selected or {}), "recommended": bool(selected), "candidates": candidates, "cardList": cards}


def resolve_publish_category(preferred: object, recommendation: dict) -> dict:
    preferred = preferred if isinstance(preferred, dict) else {"catName": str(preferred or "")}
    candidates = recommendation.get("candidates") or []
    if recommendation.get("recommended"):
        candidates = [recommendation, *candidates]
    candidates = [category for item in candidates if (category := normalize_publish_category(item))]
    selected = normalize_publish_category(preferred) if preferred.get("source") != "local" else {}
    if selected:
        # Respect an explicitly selected platform candidate, including its IDs.
        category = next((cat for cat in candidates if same_category(selected, cat)), selected)
    elif preferred.get("catName"):
        matches = [cat for cat in candidates if cat["catName"] == str(preferred["catName"]).strip()]
        unique = {(cat["catId"], cat["channelCatId"]): cat for cat in matches}
        category = next(iter(unique.values())) if len(unique) == 1 else None
    else:
        category = normalize_publish_category(recommendation) if recommendation.get("recommended") else None
    if not category:
        raise PublishCategoryError("未取得所选分类的有效叶子类目，请点击“重新识别分类”，从闲鱼返回的候选分类中选择后再发布。商品内容已保留。")
    same_as_recommended = same_category(category, recommendation)
    return {**category, "cardList": recommendation.get("cardList", []) if same_as_recommended else []}
