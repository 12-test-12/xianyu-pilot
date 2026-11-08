"""Use the desktop seller-console order feed with the durable delivery monitor."""
import asyncio
import json
import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from sqlalchemy import text

from app.core.background_tasks import spawn_background_task
from app.core.database import async_session
from app.services.desktop_delivery_contracts import StepResult
from app.services.desktop_inventory import InventoryError
from app.services.manual_delivery import ManualDeliveryError
from app.services.message_automation_outbox import RetryableOutboxError
from app.services.notify_dispatcher import notify_new_order
from app.services.official_delivery_contracts import OfficialOrder, WAITING
from app.services.official_delivery_gateway import OfficialDeliverySender
from app.services.official_delivery_monitor import OfficialDeliveryMonitor, notice_from_ws
from app.services.seller_orders_api import PlatformOrderError
from app.services.ws_client import ws_manager
from app.services.xianyu_api_service import (
    _decrypt_value, _get_account_auth, _parse_cookie_str, confirm_order_shipment, fetch_sold_orders_page,
)
from app.services.xianyu_order_sync import _detect_bargain_from_buttons

logger = logging.getLogger(__name__)
_STATUS = {"待发货": WAITING, "已发货": "WAIT_BUYER_CONFIRM_GOODS", "交易成功": "TRADE_FINISHED",
           "待付款": "WAIT_BUYER_PAY", "交易关闭": "TRADE_CLOSED"}


def parse_sold_order(account_id, seller_id, row):
    try:
        common = row["commonData"]
        price = row.get("priceVO") or {}
        buyer = row.get("buyerInfoVO") or {}
        item = row.get("itemInfoVO") or {}
        purchase = common.get("itemBuyInfo") or {}
        raw_cents = price.get("realPayCent", common.get("amountCent"))
        if raw_cents is None:
            paid = price.get("realPayPrice", price.get("totalPrice"))
            cents = Decimal(str(paid)) * 100
        else:
            cents = Decimal(str(raw_cents))
        if not cents.is_finite() or not 0 <= cents <= 10**12 or cents != cents.to_integral_value():
            raise ValueError
        quantity = common.get("quantity", price.get("buyNum"))
        if isinstance(quantity, str) and quantity.isascii() and quantity.isdigit():
            quantity = int(quantity)
        sku = common.get("skuId", purchase.get("skuId", item.get("skuId")))
        if sku is not None and (isinstance(sku, bool) or not isinstance(sku, (int, str))):
            raise ValueError
        status = common["orderStatus"]
        refunding = common.get("inRefund", row.get("inRefund"))
        # The merchant console returns literal strings, unlike the seller API.
        if refunding in ("true", "false"):
            refunding = refunding == "true"
        order = OfficialOrder(
            account_id=account_id, seller_id=str(common.get("sellerId", seller_id)),
            order_id=str(common["orderId"] or ""),
            buyer_id=str(common.get("buyerId") or buyer.get("buyerId") or "").removesuffix("@goofish"),
            item_id=str(common.get("itemId") or item.get("itemId") or purchase.get("itemId") or ""),
            sku_id=str(sku) if sku is not None else "",
            quantity=quantity, amount_cent=int(cents), status=_STATUS.get(status, status), refunding=refunding,
        )
        if order.seller_id != seller_id:
            raise ValueError
        return order
    except (KeyError, AttributeError, TypeError, ValueError, InvalidOperation) as exc:
        raise PlatformOrderError("sold_order_facts_incomplete") from exc


class DesktopSoldOrderSource:
    def __init__(self, store):
        self.store = store

    def parse(self, account_id, seller_id, row):
        order = parse_sold_order(account_id, seller_id, row)
        if order.sku_id:
            return order
        with self.store.connection() as conn:
            skus = conn.execute("""
                SELECT s.sku_id,s.property_list_json FROM xianyu_goods_sku s
                JOIN xianyu_goods g ON g.id=s.goods_id
                WHERE g.account_id=? AND g.deleted=0 AND (g.external_goods_id=? OR g.goods_id=? OR CAST(g.id AS TEXT)=?)
            """, (account_id, order.item_id, order.item_id, order.item_id)).fetchall()
        lines = (row.get("itemVO") or {}).get("itemInfoLines") or []
        if not skus:
            if lines:
                raise PlatformOrderError("sold_order_sku_missing")
            return order
        # Never infer a purchased SKU from price or from the only enabled rule.
        matches = []
        for sku in skus:
            try:
                props = json.loads(sku["property_list_json"] or "[]")
                expected = [(p["propertyText"], p["valueText"]) for p in props]
                actual = [(line["key"], line["value"]) for line in lines]
                if not expected or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k,v in expected + actual):
                    continue
                named_match = sorted(actual) == sorted(expected)
                single_match = len(expected) == 1 and actual == [("规格", expected[0][1])]
                if named_match or single_match:
                    matches.append(sku["sku_id"])
            except (ValueError, TypeError, KeyError):
                continue
        if len(matches) != 1:
            raise PlatformOrderError("sold_order_sku_missing")
        return order.model_copy(update={"sku_id": matches[0]})

    async def page(self, account_id, page):
        client = ws_manager.get_client(account_id)
        if not client or not client.unb:
            raise PlatformOrderError("seller_session_unavailable")
        seller_id = str(client.unb)
        result = await asyncio.to_thread(fetch_sold_orders_page, account_id, page,
                                         expected_seller_id=seller_id)
        if not result or not result.get("success"):
            raise PlatformOrderError("sold_orders_unavailable")
        return seller_id, result["data"]

    async def lookup(self, account_id, order_id):
        for page in range(1, 11):
            seller_id, data = await self.page(account_id, page)
            matches = [row for row in data["items"] if isinstance(row, dict)
                       and isinstance(row.get("commonData"), dict)
                       and str(row["commonData"].get("orderId") or "") == order_id]
            if len(matches) == 1:
                return await asyncio.to_thread(self.parse, account_id, seller_id, matches[0]), matches[0]
            if matches or not data["nextPage"]:
                break
        raise PlatformOrderError("sold_order_not_verified")

    async def get_order(self, account_id, order_id):
        order, _ = await self.lookup(account_id, order_id)
        return order

    async def list_waiting(self, account_id, page=1):
        seller_id, data = await self.page(account_id, page)
        orders = []
        incomplete = False
        for row in data["items"]:
            common = row.get("commonData") if isinstance(row, dict) else None
            if not isinstance(common, dict) or common.get("orderStatus") not in (WAITING, "待发货"):
                continue
            try:
                order = await asyncio.to_thread(self.parse, account_id, seller_id, row)
                if not order.refunding:
                    orders.append(order)
            except PlatformOrderError as exc:
                incomplete = str(exc)
        if incomplete:
            await asyncio.to_thread(self.store.monitor_state, account_id, "attention", incomplete)
        # shortcut: probe the newest two pages every 20 seconds, expand when the platform supports a verified waiting-only filter
        return orders, data["nextPage"] and page < 2


async def resolve_conversation(account_id, buyer_id, item_id):
    async with async_session() as db:
        result = await db.execute(text("""
            SELECT DISTINCT s_id FROM xianyu_conversation
            WHERE account_id=:account AND goods_id=:item AND s_id IS NOT NULL
              AND (peer_external_uid IN (:buyer, :suffixed) OR external_buyer_id IN (:buyer, :suffixed))
            UNION
            SELECT s_id FROM xianyu_chat_message
            WHERE account_id=:account AND xy_goods_id=:item AND deleted=0 AND s_id IS NOT NULL
              AND (peer_external_uid IN (:buyer, :suffixed) OR sender_user_id IN (:buyer, :suffixed)
                   OR receiver_user_id IN (:buyer, :suffixed))
        """), {"account": account_id, "item": item_id, "buyer": buyer_id, "suffixed": f"{buyer_id}@goofish"})
        sessions = {str(sid).removesuffix("@goofish") for sid in result.scalars() if sid}
    return sessions.pop() if len(sessions) == 1 else ""


class DesktopSoldOrderSender(OfficialDeliverySender):
    async def confirm_shipment(self, work, order):
        checked, row = await self.source.lookup(order.account_id, order.order_id)
        if checked != order:
            return StepResult("not_sent", "local:confirmation_order_changed", True)
        result = await asyncio.to_thread(
            confirm_order_shipment, order.account_id, order.order_id,
            _detect_bargain_from_buttons(row), order.item_id, order.buyer_id,
            expected_seller_id=order.seller_id,
        )
        if result and result.get("success"):
            return StepResult("confirmed", "official:consign-ack:" + work.operation_id)
        return StepResult("unknown")


class DesktopOrderDelivery(OfficialDeliveryMonitor):
    def __init__(self, path, gate):
        super().__init__(path, None, None)
        self.gate = gate
        self.wake_probe = asyncio.Event()
        self.source = DesktopSoldOrderSource(self.store)
        self.sender = DesktopSoldOrderSender(self.source, ws_manager._clients, resolve_conversation, self.upload_image)

    async def probe_connected_accounts(self, *, configured_only=False):
        async def probe(account_id):
            try:
                await self.drain(account_id)
            except Exception as exc:
                logger.warning("Desktop delivery inbox delayed accountId=%s errorType=%s", account_id, type(exc).__name__)
            try:
                await self.poll_once(account_id)
            except Exception as exc:
                logger.warning("Desktop delivery probe failed accountId=%s errorType=%s", account_id, type(exc).__name__)
                await asyncio.to_thread(self.store.monitor_state, account_id, "paused", "sold_order_verification_failed")
                return False
            return True

        if self.gate.blocked or self._stopping:
            return []
        accounts = [aid for aid in tuple(ws_manager._clients) if self.sender.is_ready(aid)]
        if configured_only and accounts:
            with self.store.connection() as conn:
                configured = {row[0] for row in conn.execute("""
                    SELECT account_id FROM delivery_rule WHERE deleted=0 AND status=1
                    UNION SELECT account_id FROM delivery_record
                          WHERE receipt_mode='platform' AND workflow_state!='completed'
                    UNION SELECT account_id FROM delivery_inbox WHERE state='pending'
                """)}
            accounts = [aid for aid in accounts if aid in configured]
        return await asyncio.gather(*(probe(aid) for aid in accounts))

    @staticmethod
    async def upload_image(account_id, image_bytes):
        from app.services.auto_category import upload_image_to_xianyu

        auth = await asyncio.to_thread(_get_account_auth, account_id)
        client = ws_manager.get_client(account_id)
        cookie = _decrypt_value((auth or {}).get("encrypted_cookie") or "")
        if not client or (auth or {}).get("external_uid") != str(client.unb) or _parse_cookie_str(cookie).get("unb") != str(client.unb):
            raise PlatformOrderError("seller_session_mismatch")
        return await asyncio.to_thread(upload_image_to_xianyu, cookie, image_bytes)

    async def consider(self, account_id, order_id, notice=None):
        if self.gate.blocked or self._stopping or account_id in self._resume_required:
            return None
        order = await self.source.get_order(account_id, order_id)
        if order.status != WAITING or order.refunding:
            return None
        if notice and ((notice.item_id and notice.item_id != order.item_id)
                       or (notice.buyer_id and notice.buyer_id != order.buyer_id)):
            return None
        with self.store.connection() as conn:
            if not conn.execute("""
                SELECT 1 FROM delivery_rule r JOIN xianyu_goods g ON g.id=r.goods_id
                WHERE g.account_id=? AND g.deleted=0 AND (g.external_goods_id=? OR g.goods_id=?)
                  AND r.deleted=0 AND r.status=1
            """, (account_id, order.item_id, order.item_id)).fetchone():
                return None
            prior = conn.execute("""
                SELECT 1 FROM realtime_delivery_attempt
                WHERE account_id=? AND
                  (external_order_id=? OR (COALESCE(external_order_id,'')='' AND item_id=? AND peer_id IN (?,?)))
                  AND (state IN ('message_sending','message_sent','platform_confirming','success','unknown')
                       OR message_started_at IS NOT NULL)
            """, (account_id, order_id, order.item_id, order.buyer_id, f"{order.buyer_id}@goofish")).fetchone()
            if prior:
                return None
            if conn.execute("""
                SELECT 1 FROM xianyu_trade_order o
                JOIN manual_delivery_attempt a ON a.order_id=o.id
                WHERE o.account_id=? AND o.external_order_id=? AND a.message_started_at IS NOT NULL
            """, (account_id, order_id)).fetchone():
                return None
            if not order.sku_id and conn.execute("""
                SELECT 1 FROM xianyu_goods g JOIN xianyu_goods_sku s ON s.goods_id=g.id
                WHERE g.account_id=? AND g.deleted=0 AND (g.external_goods_id=? OR g.goods_id=?)
            """, (account_id, order.item_id, order.item_id)).fetchone():
                raise PlatformOrderError("sold_order_sku_missing")
            statement = conn.execute("SELECT enabled FROM delivery_statement WHERE deleted=0 ORDER BY id DESC LIMIT 1").fetchone()
            consent = conn.execute("""
                SELECT status FROM delivery_statement_session
                WHERE account_id=? AND order_id=? AND xy_goods_id=? AND buyer_id IN (?,?) AND deleted=0 ORDER BY id DESC LIMIT 1
            """, (account_id, order_id, order.item_id, order.buyer_id, f"{order.buyer_id}@goofish")).fetchone()
        if (statement and statement[0] or consent) and (not consent or consent[0] != "confirmed"):
            if not consent and notice and notice.kind == "order_hint":
                from app.services.ws_statement_handler import send_statement_and_create_session

                await asyncio.to_thread(self.rules.resolve, account_id, order.item_id, order.sku_id)
                sid = await resolve_conversation(account_id, order.buyer_id, order.item_id)
                if not sid:
                    raise PlatformOrderError("conversation_unverified")
                if not self.observe_continuity(account_id) or self._stopping or self.gate.blocked:
                    raise PlatformOrderError("delivery_paused")
                async with async_session() as db:
                    sent = await send_statement_and_create_session(
                        db, account_id=account_id, msg={}, order_id=order_id, xy_goods_id=order.item_id,
                        s_id=sid, pnm_id=notice.message_id, buyer_user_id=order.buyer_id, buyer_user_name="",
                    )
                    await db.commit()
                if not sent:
                    raise PlatformOrderError("statement_not_confirmed")
            return None
        await asyncio.to_thread(self.rules.resolve, account_id, order.item_id, order.sku_id)
        if not await resolve_conversation(account_id, order.buyer_id, order.item_id):
            raise PlatformOrderError("conversation_unverified")
        delivery_id = await self._consider_verified(account_id, order_id, order, notice)
        if delivery_id and notice and notice.kind == "order_hint":
            try:
                spawn_background_task(notify_new_order(account_id, {
                    "xyGoodsId": order.item_id,
                    "reminderContent": "买家已付款",
                    "reminderUrl": "?" + urlencode({"orderId": order_id}),
                }), name="desktop-new-order-notification")
            except RuntimeError:
                logger.debug("Desktop notification runtime is shutting down")
        return delivery_id

    async def execute_manual(self, order_id, command, coordinator):
        with self.store.connection() as conn:
            owner = conn.execute("SELECT account_id FROM xianyu_trade_order WHERE id=? AND deleted=0", (order_id,)).fetchone()
        if not owner:
            return await coordinator.execute(order_id, command)
        async with self.lock(owner[0]):
            with self.store.connection() as conn:
                automatic = conn.execute("""
                    SELECT 1 FROM delivery_record
                    WHERE order_id=? AND desktop_managed=1 AND receipt_mode='platform'
                """, (order_id,)).fetchone()
            if automatic:
                raise ManualDeliveryError(409, "automatic_delivery_exists", "该订单已有自动发货记录，请先核对发货状态")
            return await coordinator.execute(order_id, command)

    async def retry_record(self, record_id):
        with self.store.connection() as conn:
            record = conn.execute("""
                SELECT account_id FROM delivery_record
                WHERE id=? AND desktop_managed=1 AND receipt_mode='platform'
            """, (record_id,)).fetchone()
        if not record:
            return None
        account_id = record[0]
        async with self.lock(account_id):
            try:
                if self.gate.blocked or self._stopping:
                    raise InventoryError("自动发货已暂停，请恢复后再核验", 409)
                await asyncio.to_thread(self.store.recover_interrupted, account_id)
                detail = self.store.detail(record_id)
                if detail["workflowState"] == "needs_review":
                    detail = await self._reconcile_record(record_id)
                elif detail["workflowState"] == "stock_blocked":
                    await self.consider(account_id, detail["orderNumber"])
                    detail = self.store.detail(record_id)
                else:
                    await self.execute(record_id)
                    detail = self.store.detail(record_id)
            except PlatformOrderError as exc:
                raise InventoryError("暂无法核验平台订单，请稍后重试", 503) from exc
        state = detail["workflowState"]
        if state == "completed":
            return {"status": "success", "message": "平台发货已确认"}
        if state == "needs_review":
            return {"status": "unknown", "message": "请先在闲鱼核对该订单和聊天记录"}
        if detail["confirmationState"] == "manual_pending":
            return {"status": "message_sent", "message": "请在闲鱼确认发货"}
        return {"status": state if state == "failed" else "pending", "message": "核验未完成，请检查订单和发货条件"}

    async def handle_message(self, account_id, message, *, payment_event):
        if str(message.get("direction") or "IN").upper() != "IN":
            return
        client = ws_manager.get_client(account_id)
        if not client or not client.unb:
            if payment_event:
                raise RetryableOutboxError("seller_session_unavailable")
            return
        notice = notice_from_ws(message, str(client.unb))
        if notice and notice.kind == "buyer_text" and not payment_event:
            if not await asyncio.to_thread(self.rules.has_keyword, account_id, notice.item_id, notice.text):
                return
        elif not payment_event or not notice:
            if payment_event:
                self.wake_probe.set()
                raise RetryableOutboxError("payment_order_reference_unavailable")
            return
        await asyncio.to_thread(self.store.enqueue, account_id, notice)
        self.wake_probe.set()
