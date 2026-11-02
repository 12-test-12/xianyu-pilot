"""聊天消息内容可见性回归测试。

背景：闲鱼 WS 的 contentType 是数字枚举（1 文本、2 图片、3 语音、8 商品卡片、
26 订单通知 等）。历史实现把未识别的类型统一压成 contentType=1 且正文为空，
前端只能落到 "[非文本消息]" 占位，用户看不到任何内容。

本测试只覆盖 ws_storage 的纯映射 / 派生函数（不建库、不联网），确保：
1. 每个已知 contentType 都能派生非空 displayText 或结构化字段；
2. 未知类型给出可读中文占位而不是空串；
3. 系统通知类消息正文能从 extraInfo / reminderContent 等 JSON 兜底提取。
"""

import json

import pytest

from app.services import ws_storage


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """纯映射函数不需要网络，这里禁掉以防意外外呼。"""

    def _blocked(*args, **kwargs):
        raise AssertionError("test_message_content_visibility 不应发起网络请求")

    monkeypatch.setattr("socket.create_connection", _blocked, raising=False)
    monkeypatch.setattr("socket.getaddrinfo", _blocked, raising=False)


# ---------------------------------------------------------------------------
# 映射表本身
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "content_type,expected_kind",
    [
        (1, "text"),
        (2, "image"),
        (3, "audio"),
        (4, "video"),
        (5, "emoji"),
        (6, "file"),
        (7, "location"),
        (8, "goods_card"),
        (9, "red_packet"),
        (10, "transfer"),
        (11, "business_notice"),
        (26, "order_notice"),
    ],
)
def test_content_type_map_covers_documented_types(content_type, expected_kind):
    assert ws_storage.MESSAGE_CONTENT_TYPE_MAP[content_type] == expected_kind
    assert ws_storage._content_type_kind(content_type) == expected_kind
    assert ws_storage.MESSAGE_CONTENT_TYPE_LABELS[expected_kind]
    assert ws_storage.MESSAGE_CONTENT_TYPE_PLACEHOLDERS[expected_kind]


@pytest.mark.parametrize("value,expected", [
    (1, 1), ("1", 1), (2, 2), ("image", 2), ("audio", 3), (26, 26),
    (None, 1), ("", 1), ("abc", 0), (101, 101), (32, 32), (True, 1),
])
def test_coerce_content_type(value, expected):
    assert ws_storage._coerce_content_type(value) == expected


def test_unknown_kind_is_not_collapsed_to_text():
    """未知类型必须保持自身数值，不能被压成 1（文本）。"""
    for unknown in (0, 32, 101, 999, "abc"):
        assert ws_storage._content_type_kind(unknown) == "unknown"
    assert ws_storage._content_type_kind(32) != "text"


# ---------------------------------------------------------------------------
# 各类型经 _build_message_display_fields 派生后的可见性
# ---------------------------------------------------------------------------

def _display_text(message):
    return ws_storage._build_message_display_fields(message)["displayText"]


def test_text_message_keeps_body():
    fields = ws_storage._build_message_display_fields({"contentType": 1, "msgContent": "你好，在吗？"})
    assert fields["displayText"] == "你好，在吗？"
    assert fields["contentType"] == 1


def test_text_message_without_body_is_not_blank():
    assert _display_text({"contentType": 1, "msgContent": ""}) == "[文本]"


def test_image_message_has_urls_and_text():
    message = {
        "contentType": 2,
        "msgContent": "https://img.alicdn.com/imgextra/i1/a.jpg",
    }
    fields = ws_storage._build_message_display_fields(message)
    assert fields["imageUrls"]
    assert fields["displayText"].startswith("[图片]")


def test_audio_message_has_media_and_duration_text():
    message = {
        "contentType": 3,
        "completeMsg": json.dumps({"audio": {"url": "https://img.alicdn.com/a.amr", "duration": 8}}),
    }
    fields = ws_storage._build_message_display_fields(message)
    assert fields["media"]["type"] == "audio"
    assert fields["media"]["duration"] == 8
    assert "时长 8s" in fields["displayText"]


def test_audio_message_without_url_still_readable():
    fields = ws_storage._build_message_display_fields({"contentType": 3, "msgContent": ""})
    assert fields["media"]["type"] == "audio"
    assert fields["displayText"].startswith("[语音]")


def test_goods_card_message_has_card_title():
    message = {
        "contentType": 8,
        "completeMsg": json.dumps({
            "rawPayload": {"sessionInfo": {"extensions": {
                "itemTitle": "九成新机械键盘",
                "itemMainPic": "https://img.alicdn.com/imgextra/i2/b.jpg",
                "itemPrice": "128.00",
                "itemId": "778899",
            }}}
        }),
    }
    fields = ws_storage._build_message_display_fields(message)
    assert fields["card"]["title"] == "九成新机械键盘"
    assert fields["card"]["price"] == "128.00"
    assert "[商品卡片]" in fields["displayText"]
    assert "九成新机械键盘" in fields["displayText"]


def test_order_notice_extracts_reminder_content():
    message = {
        "contentType": 26,
        "reminderContent": "买家已付款 ¥0.01，请尽快发货",
        "completeMsg": json.dumps({"extraInfo": {"reminderContent": "买家已付款 ¥0.01"}}),
    }
    fields = ws_storage._build_message_display_fields(message)
    assert fields["displayText"]
    assert "买家已付款" in fields["displayText"]


def test_order_notice_without_body_gets_label():
    fields = ws_storage._build_message_display_fields({"contentType": 26})
    assert fields["displayText"].startswith("[订单通知]")


def test_order_notice_body_from_extra_info_json_string():
    """正文藏在 completeMsg 字符串里的 extraInfo 时也要能提取出来。"""
    message = {
        "contentType": 26,
        "msgContent": "",
        "completeMsg": json.dumps({"extraInfo": json.dumps({"content": "订单已发货"})}),
    }
    assert "订单已发货" in _display_text(message)


@pytest.mark.parametrize("content_type,placeholder_prefix", [
    (4, "[视频]"),
    (5, "[表情]"),
    (6, "[文件]"),
    (7, "[位置]"),
    (9, "[红包]"),
    (10, "[转账]"),
    (11, "[业务通知]"),
])
def test_other_types_get_chinese_placeholder(content_type, placeholder_prefix):
    text = _display_text({"contentType": content_type, "msgContent": ""})
    assert text
    assert text.startswith(placeholder_prefix)


@pytest.mark.parametrize("content_type", [32, 101, 999])
def test_unknown_type_is_readable_not_empty(content_type):
    text = _display_text({"contentType": content_type, "msgContent": ""})
    assert text
    assert text != ""
    assert "[非文本消息]" not in text
    assert "暂不支持的消息类型" in text
    assert str(content_type) in text


def test_unknown_type_with_body_keeps_body():
    text = _display_text({"contentType": 999, "msgContent": "系统提示：订单已关闭"})
    assert "系统提示：订单已关闭" in text


def test_invalid_content_type_falls_back_to_readable_placeholder():
    text = _display_text({"contentType": "abc", "msgContent": ""})
    assert text == ws_storage.MESSAGE_CONTENT_TYPE_PLACEHOLDERS["unknown"]


def test_display_fields_are_idempotent_and_do_not_mutate_input():
    message = {"contentType": 8, "msgContent": "商品卡片标题"}
    snapshot = dict(message)
    first = ws_storage._build_message_display_fields(message)
    second = ws_storage._build_message_display_fields(first)
    assert message == snapshot
    assert first["displayText"] == second["displayText"]


def test_decorate_context_messages_covers_every_row():
    rows = [
        {"id": 1, "contentType": 1, "msgContent": "hi"},
        {"id": 2, "contentType": 3, "msgContent": ""},
        {"id": 3, "contentType": 8, "msgContent": ""},
        {"id": 4, "contentType": 26, "msgContent": ""},
        {"id": 5, "contentType": 101, "msgContent": ""},
    ]
    decorated = ws_storage._decorate_context_messages(rows)
    assert len(decorated) == len(rows)
    for item in decorated:
        assert str(item.get("displayText") or "").strip()
        assert item.get("contentTypeLabel")
    # 原入参不被修改
    assert all("displayText" not in row for row in rows)


# ---------------------------------------------------------------------------
# WS 解包路径：_extract_live_message_content 不再返回空正文
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("content_type", [4, 5, 6, 7, 9, 10, 11, 26, 32, 101])
def test_extract_live_message_content_never_returns_blank(content_type):
    parsed_type, text, image_urls = ws_storage._extract_live_message_content({"contentType": content_type})
    assert parsed_type == content_type
    assert text.strip()
    assert image_urls == []


def test_extract_live_message_content_unknown_is_chinese():
    _, text, _ = ws_storage._extract_live_message_content({"contentType": 999})
    assert "暂不支持的消息类型" in text


def test_extract_live_message_content_text_type_unchanged():
    assert ws_storage._extract_live_message_content(
        {"contentType": 1, "text": {"text": "在的"}}
    ) == (1, "在的", [])


def test_extract_live_message_content_image_type_unchanged():
    content_type, text, urls = ws_storage._extract_live_message_content(
        {"contentType": 2, "image": {"pics": [{"url": "//img.alicdn.com/i.jpg"}]}}
    )
    assert content_type == 2
    assert urls and urls[0].startswith("https://")
    assert text == urls[0]
