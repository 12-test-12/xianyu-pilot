"""Preserve marketplace category IDs; local tree IDs are display identifiers."""
from __future__ import annotations


class PublishCategoryError(RuntimeError):
    def __init__(self, message, *, candidates=(), rejected_category=None):
        super().__init__(message)
        self.candidates = [option for item in candidates if (option := category_option(item))]
        self.rejected_category = normalize_publish_category(rejected_category)

    def to_data(self):
        return {"categoryRefreshRequired": True, "categoryCandidates": self.candidates,
                "categoryRefreshFailed": not bool(self.candidates), "rejectedCategory": self.rejected_category or None}


CATEGORY_REFRESH_CODES = {"FAIL_BIZ_CATEGORY_DISPOSED", "FAIL_BIZ_ITEM_CATEGORY_INVALID", "FAIL_BIZ_ITEM_CATEGORY_NOT_MATCH"}

# The three ways a publish can be refused before any platform write. Each one
# needs a different user action, so the message names the actual cause instead
# of repeating a single generic sentence.
LOCAL_ONLY_MESSAGE = (
    "当前所选分类不包含平台类目 ID（来自本地分类目录或旧草稿），无法直接发布。"
    "请点击“重新识别分类”，从平台返回的最新候选中选择。商品内容已保留。"
)
NO_CANDIDATE_MESSAGE = (
    "未能获取平台最新的分类候选（可能是账号登录状态或网络异常）。"
    "请确认账号已登录后点击“重新识别分类”。商品内容已保留。"
)
MISMATCH_MESSAGE = (
    "当前分类未能在平台最新候选中确认，请从最新候选中重新选择，或点击“重新识别分类”。商品内容已保留。"
)


def category_failure_message(preferred: dict, candidates: list) -> str:
    """Explain why this category cannot be published, not just that it cannot."""
    if not candidates:
        return NO_CANDIDATE_MESSAGE
    if not normalize_publish_category(preferred):
        return LOCAL_ONLY_MESSAGE
    return MISMATCH_MESSAGE


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


def category_option(value: object) -> dict:
    category = normalize_publish_category(value)
    if not category:
        return {}
    path = value.get("categoryPath")
    if not isinstance(path, list):
        path = [value.get(key) for key in ("channelCat1Name", "channelCat2Name", "channelCat3Name")]
    path = [str(name).strip()[:200] for name in path[:8] if name]
    if not path or path[-1] != category["catName"]:
        path.append(category["catName"])
    return {**category, "categoryPath": path}


def current_category_candidates(recommendation: dict) -> list[dict]:
    values = recommendation.get("candidates") or []
    if recommendation.get("recommended"):
        values = [recommendation, *values]
    unique = {}
    for value in values:
        option = category_option(value)
        if option:
            unique[(option["catId"], option["channelCatId"])] = option
    return list(unique.values())


def same_category(preferred: dict, candidate: dict) -> bool:
    # tbCatId can be shared by multiple idle-marketplace categories.
    if not isinstance(preferred, dict) or not isinstance(candidate, dict):
        return False
    keys = [key for key in ("catId", "channelCatId") if preferred.get(key) and candidate.get(key)]
    return bool(keys) and all(str(preferred[key]) == str(candidate[key]) for key in keys)


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
            category = category_option(value)
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
        selected = matched or category_option(prediction)
        if selected:
            break
    selected = selected or clicked
    if selected and selected not in candidates:
        candidates.insert(0, selected)
    return {**(selected or {}), "recommended": bool(selected), "candidates": candidates, "cardList": cards}


def resolve_publish_category(preferred: object, recommendation: dict) -> dict:
    preferred = preferred if isinstance(preferred, dict) else {"catName": str(preferred or "")}
    candidates = current_category_candidates(recommendation)
    name = str(preferred.get("catName") or "").strip()
    category = None
    if name:
        # IDs from a saved draft or template are hints, not permanent authority.
        matches = [cat for cat in candidates if cat["catName"] == name]
        # A marketplace catId/channelCatId pair is the platform's own identity:
        # identical IDs are the same category even when the display path moved,
        # so path equality is only a tiebreaker for candidates whose IDs changed.
        identical = [cat for cat in matches if same_category(preferred, cat)]
        if len(identical) == 1:
            category = identical[0]
        else:
            old_path = preferred.get("categoryPath")
            path_scoped = matches
            if preferred.get("source") != "local" and isinstance(old_path, list) and len(old_path) > 1:
                path_scoped = [cat for cat in matches if cat["categoryPath"] == old_path]
            if len(path_scoped) == 1:
                category = path_scoped[0]
    else:
        category = category_option(recommendation) if recommendation.get("recommended") else None
    if not category:
        raise PublishCategoryError(category_failure_message(preferred, candidates), candidates=candidates)
    same_as_recommended = same_category(category, recommendation)
    return {**category, "cardList": recommendation.get("cardList", []) if same_as_recommended else []}
