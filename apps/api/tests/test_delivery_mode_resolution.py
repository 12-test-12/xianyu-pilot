"""发货规则诊断回归测试：区分“没有规则 / 规则不匹配 / 模式已停用”，并保证文本规则能真正发货。

覆盖 5 个场景（外加 1 个全局回退的加固场景）：
1. 完全没有发货规则 -> delivery_rule_missing
2. 有规则但没有匹配该商品的规则 -> delivery_rule_not_matched
3. 匹配到历史遗留 api/custom 模式 -> delivery_mode_unsupported（文案带规则 ID 与原始模式）
4. 匹配到文本规则 -> 正常发货（消息真正发送、发货记录成功）
5. 商品无专属规则但存在账号级/全局文本规则 -> 回退使用全局规则并成功发货
6. 商品命中一条非法模式的规则，但同时存在全局文本规则 -> 跳过坏规则回退到全局文本规则

断言重点：
* 失败记录不再出现“API/custom 发货模式已停用”这种误导性文案；
* 错误码准确、retry_safe=False（配置问题不应自动重试）；
* 文本规则场景能进入正常发货流程（gateway 收到内容、delivery_record 成功）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import create_configured_engine
from app.models.entities import (
    CardGroup,
    CardItem,
    DeliveryRecord,
    DeliveryRule,
    RealtimeDeliveryAttempt,
    XianyuGoods,
    XianyuTradeOrder,
    XianyuTradeOrderItem,
)
from app.services import realtime_delivery as realtime
from app.services import ws_delivery_handler as delivery

ACCOUNT_ID = 1
ITEM_ID = "8888"
ORDER_ID = "order-1"
BUYER_ID = "buyer-1"
SESSION_ID = "session-1"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """发货链路不允许真实网络：任何出站连接直接失败。"""

    import socket

    def blocked(*args, **kwargs):
        raise AssertionError("real network forbidden")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest_asyncio.fixture
async def db(tmp_path):
    """独立的 SQLite 库：ORM 表 + 两张 raw SQL 表（delivery_goods_config / delivery_text_source）。"""

    engine = create_configured_engine(f"sqlite+aiosqlite:///{tmp_path / 'delivery.sqlite3'}")
    async with engine.begin() as conn:
        for model in (
            XianyuGoods,
            XianyuTradeOrder,
            XianyuTradeOrderItem,
            DeliveryRule,
            CardGroup,
            CardItem,
            DeliveryRecord,
            RealtimeDeliveryAttempt,
        ):
            await conn.run_sync(model.__table__.create)
        await conn.execute(
            text(
                """
                CREATE TABLE delivery_goods_config (
                    id INTEGER PRIMARY KEY,
                    goods_id INTEGER NOT NULL,
                    config_json TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    deleted INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE delivery_text_source (
                    id INTEGER PRIMARY KEY,
                    title TEXT NULL,
                    content TEXT NULL,
                    remark TEXT NULL,
                    segments TEXT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    created_time DATETIME NULL,
                    updated_time DATETIME NULL
                )
                """
            )
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


class _RecordingGateway:
    """记录真正发送出去的内容，用于验证“文本规则场景确实发货”。"""

    def __init__(self):
        self.sent: list[str] = []

    async def send_message(self, lease, content, segments=None):
        self.sent.append(content)
        return realtime.ExternalDeliveryResult.confirmed()

    async def confirm_shipment(self, lease):
        return realtime.ExternalDeliveryResult.confirmed()


@pytest.fixture
def gateway(monkeypatch):
    fake = _RecordingGateway()
    monkeypatch.setattr(delivery, "XianyuRealtimeDeliveryGateway", lambda: fake)

    async def _noop(*args, **kwargs):
        return None

    # 审计/通知不是本测试的关注点，且会写入额外表，这里直接屏蔽。
    monkeypatch.setattr(delivery, "_record_delivery_audit", _noop)
    monkeypatch.setattr(delivery, "_notify_realtime_delivery_attention", _noop)
    return fake


def payment_message() -> dict:
    """构造一条“买家已付款”的付款事件消息。"""

    return {
        "sId": SESSION_ID,
        "senderUserId": BUYER_ID,
        "senderUserName": "买家",
        "xyGoodsId": ITEM_ID,
        "pnmId": "event-1",
        "reminderUrl": f"orderId={ORDER_ID}&itemId={ITEM_ID}&buyerUserId={BUYER_ID}",
        "reminderContent": "我已付款",
    }


async def seed_goods(db, goods_id: int = 1, external_id: str = ITEM_ID) -> int:
    """插入一条商品记录，返回主键（让规则 goods_id 可以精确匹配）。"""

    await db.execute(
        text(
            """
            INSERT INTO xianyu_goods (
                id, account_id, external_goods_id, goods_id, title,
                price, sold_price, status, deleted,
                auto_relist_enabled, has_snapshot
            ) VALUES (
                :id, :account_id, :external_id, :external_id, '测试商品',
                '1.00', '1.00', 1, 0,
                0, 0
            )
            """
        ),
        {"id": goods_id, "account_id": ACCOUNT_ID, "external_id": external_id},
    )
    await db.commit()
    return goods_id


async def seed_rule(db, *, rule_id: int, goods_id=None, mode: str = "text", content: str = "感谢购买") -> int:
    """插入一条 delivery_rule（旧版规则表）。"""

    await db.execute(
        text(
            """
            INSERT INTO delivery_rule (
                id, account_id, rule_name, goods_id, delivery_mode,
                delivery_content, trigger_on_pay, max_delivery_per_day, status, deleted
            ) VALUES (
                :id, :account_id, :rule_name, :goods_id, :mode,
                :content, 1, 0, 1, 0
            )
            """
        ),
        {
            "id": rule_id,
            "account_id": ACCOUNT_ID,
            "rule_name": f"规则 {rule_id}",
            "goods_id": goods_id,
            "mode": mode,
            "content": content,
        },
    )
    await db.commit()
    return rule_id


async def seed_goods_config(db, goods_id: int, mode: str, content: str = "") -> None:
    """插入 delivery_goods_config（新版按商品配置），config_json 为 payDelivery。"""

    import json

    config = {
        "payDelivery": {
            "enabled": True,
            "mode": mode,
            "content": content,
        }
    }
    await db.execute(
        text(
            """
            INSERT INTO delivery_goods_config (id, goods_id, config_json, version, deleted)
            VALUES (:id, :goods_id, :config_json, 1, 0)
            """
        ),
        {"id": goods_id, "goods_id": goods_id, "config_json": json.dumps(config, ensure_ascii=False)},
    )
    await db.commit()


async def latest_record(db):
    """读取最近一条发货记录（按 id 倒序）。"""

    row = (
        await db.execute(
            select(
                DeliveryRecord.id,
                DeliveryRecord.status,
                DeliveryRecord.delivery_mode,
                DeliveryRecord.error_message,
                DeliveryRecord.delivery_status,
            ).order_by(DeliveryRecord.id.desc())
        )
    ).first()
    return row


@pytest.mark.asyncio
async def test_no_rule_configured_reports_delivery_rule_missing(db, gateway):
    """场景 1：完全没有发货规则时，必须报“没有规则”，而不是“发货模式停用”。"""

    await seed_goods(db)

    outcome = await delivery._process_delivery(db, ACCOUNT_ID, payment_message())

    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.error_code == "delivery_rule_missing"
    assert "尚未配置任何自动发货规则" in outcome.message
    assert "已停用" not in outcome.message
    assert outcome.retry_safe is False
    assert gateway.sent == []

    record = await latest_record(db)
    assert record is not None
    assert record.status == 3
    assert record.delivery_status == "failed"
    assert "尚未配置任何自动发货规则" in (record.error_message or "")
    assert "发货模式已停用" not in (record.error_message or "")


@pytest.mark.asyncio
async def test_rule_for_other_goods_reports_delivery_rule_not_matched(db, gateway):
    """场景 2：有规则但没匹配该商品时，报“未找到匹配该商品的发货规则”。"""

    goods_id = await seed_goods(db)
    # 规则绑定的是另一个商品（goods_id=9999），不会匹配到当前商品。
    await seed_rule(db, rule_id=1, goods_id=9999)

    outcome = await delivery._process_delivery(db, ACCOUNT_ID, payment_message())

    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.error_code == "delivery_rule_not_matched"
    assert f"未找到匹配商品 {ITEM_ID} 的发货规则" in outcome.message
    assert "「自动发货」页" in outcome.message
    assert "已停用" not in outcome.message
    assert outcome.retry_safe is False
    assert gateway.sent == []

    record = await latest_record(db)
    assert record.status == 3
    assert f"未找到匹配商品 {ITEM_ID} 的发货规则" in (record.error_message or "")
    assert goods_id  # 保证商品确实存在，排除“商品缺失”这一分支

    # 规则表里确实有 1 条启用规则，但就是不匹配 —— 这是“未匹配”而非“没配置”。
    total = (await db.execute(text("SELECT COUNT(*) FROM delivery_rule WHERE deleted = 0"))).scalar()
    assert int(total) == 1


@pytest.mark.asyncio
async def test_legacy_api_mode_reports_delivery_mode_unsupported(db, gateway):
    """场景 3：命中规则但模式是历史遗留的 api -> delivery_mode_unsupported，文案带规则 ID 与原始值。"""

    goods_id = await seed_goods(db)
    await seed_rule(db, rule_id=7, goods_id=goods_id, mode="api")

    outcome = await delivery._process_delivery(db, ACCOUNT_ID, payment_message())

    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.error_code == "delivery_mode_unsupported"
    assert "发货规则 #7" in outcome.message
    assert "API" in outcome.message
    assert "api" in outcome.message
    assert "请到「自动发货」页改为文本或卡密发货" in outcome.message
    assert outcome.retry_safe is False
    assert gateway.sent == []

    record = await latest_record(db)
    assert record.status == 3
    assert "发货规则 #7" in (record.error_message or "")
    # 这里才是真正“模式已停用”的场景，允许出现该措辞。
    assert "发货模式为 API" in (record.error_message or "")


@pytest.mark.asyncio
async def test_custom_mode_in_goods_config_reports_delivery_mode_unsupported(db, gateway):
    """场景 3 补充：新版按商品配置里残留 custom 模式，同样按“模式已停用”诊断。"""

    goods_id = await seed_goods(db)
    await seed_goods_config(db, goods_id, mode="custom")

    outcome = await delivery._process_delivery(db, ACCOUNT_ID, payment_message())

    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.error_code == "delivery_mode_unsupported"
    assert "该商品的发货配置" in outcome.message
    assert "自定义" in outcome.message
    assert outcome.retry_safe is False
    assert gateway.sent == []


@pytest.mark.asyncio
async def test_text_rule_delivers_successfully(db, gateway):
    """场景 4：匹配到文本规则时必须真正发货，不再被模式校验拦住。"""

    goods_id = await seed_goods(db)
    await seed_rule(db, rule_id=3, goods_id=goods_id, mode="text", content="感谢购买，卡密已发。")

    outcome = await delivery._process_delivery(db, ACCOUNT_ID, payment_message())

    assert outcome is not None
    assert outcome.status == "success"
    assert outcome.error_code is None
    assert gateway.sent == ["感谢购买，卡密已发。"]

    record = await latest_record(db)
    assert record is not None
    assert record.status == 2
    assert record.delivery_status == "success"
    assert record.delivery_mode == "text"
    assert not record.error_message


@pytest.mark.asyncio
async def test_global_text_rule_is_used_as_fallback(db, gateway):
    """场景 5：商品没有专属规则，但存在账号级/全局（goods_id 为空）文本规则，应回退使用。"""

    await seed_goods(db)
    # 全局规则：goods_id 为 NULL（账号级/全局），模式为文本。
    await seed_rule(db, rule_id=5, goods_id=None, mode="text", content="全局文本发货内容")

    outcome = await delivery._process_delivery(db, ACCOUNT_ID, payment_message())

    assert outcome is not None
    assert outcome.status == "success"
    assert outcome.error_code is None
    assert gateway.sent == ["全局文本发货内容"]

    record = await latest_record(db)
    assert record.status == 2
    assert record.delivery_mode == "text"


@pytest.mark.asyncio
async def test_global_text_rule_survives_legacy_goods_rule(db, gateway):
    """场景 6（加固）：命中非法模式的商品规则时，应继续找下一条可用规则，回退到全局文本规则。"""

    goods_id = await seed_goods(db)
    # 商品专属规则是历史遗留的 custom 模式（排序最优先），全局文本规则排第二。
    await seed_rule(db, rule_id=9, goods_id=goods_id, mode="custom")
    await seed_rule(db, rule_id=10, goods_id=None, mode="text", content="全局文本发货内容")

    outcome = await delivery._process_delivery(db, ACCOUNT_ID, payment_message())

    assert outcome is not None
    assert outcome.status == "success"
    assert outcome.error_code is None
    assert gateway.sent == ["全局文本发货内容"]

    record = await latest_record(db)
    assert record.status == 2
    assert record.delivery_mode == "text"


@pytest.mark.asyncio
async def test_disabled_rules_report_missing_not_matched(db, gateway):
    """补充断言：规则全部停用时归入 delivery_rule_missing，而不是“未匹配商品”。"""

    await seed_goods(db)
    await db.execute(
        text(
            """
            INSERT INTO delivery_rule (
                id, account_id, rule_name, goods_id, delivery_mode,
                delivery_content, trigger_on_pay, max_delivery_per_day, status, deleted
            ) VALUES (11, :account_id, '已停用规则', NULL, 'text', '内容', 1, 0, 0, 0)
            """
        ),
        {"account_id": ACCOUNT_ID},
    )
    await db.commit()

    outcome = await delivery._process_delivery(db, ACCOUNT_ID, payment_message())

    assert outcome is not None
    assert outcome.status == "failed"
    assert outcome.error_code == "delivery_rule_missing"
    assert "均处于停用状态" in outcome.message
    assert gateway.sent == []
