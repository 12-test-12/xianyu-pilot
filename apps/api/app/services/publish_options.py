"""Local publish checks shared by ordinary and fish-shop requests.

A district from the bundled dictionary is a publishing region, not a delivery
address. Its POI ID is optional; never manufacture one from a district code.
The platform may impose additional category/account-specific requirements.
"""
import math
import re


def publish_location_error(location: object) -> str | None:
    if not isinstance(location, dict):
        return "请选择完整的发布地区（省、市、区）"
    fields = ("poiName", "prov", "city", "area", "divisionId", "gps")
    values = {key: str(location.get(key) or "").strip() for key in fields}
    if any(not value or value.lower() == "null" for value in values.values()):
        return "请选择完整的发布地区（省、市、区）"
    if not re.fullmatch(r"[1-9][0-9]{5}", values["divisionId"]):
        return "发布地区的行政区编码无效，请重新选择"
    parts = values["gps"].split(",")
    try:
        if len(parts) != 2 or any(not part.strip() for part in parts):
            raise ValueError
        lng, lat = (float(part) for part in parts)
        if not (math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90):
            raise ValueError
    except (TypeError, ValueError):
        return "发布地区的坐标无效，请重新选择"
    return None


def ordinary_shipping_error(mode: str, free_shipping: object, self_pick: object) -> str | None:
    if mode not in {"free", "none"}:
        return "当前普通发布支持包邮或线上交付（无需邮寄），请选择对应方式"
    if mode == "free" and str(free_shipping).strip().lower() in {"0", "false", "no", "off", "none"}:
        return "包邮模式与运费设置不一致，请重新选择"
    if mode == "none" and str(self_pick).strip().lower() not in {"", "0", "false", "no", "off", "none"}:
        return "线上交付无需自提，请关闭支持自提"
    return None
