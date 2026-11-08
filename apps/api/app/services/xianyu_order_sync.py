"""
闲鱼订单同步服务。

参考商业版 automation_runtime.sync_sold_orders_for_account 实现：
1. 调用 mtop.taobao.idle.trade.merchant.sold.get 分页拉取卖家已售订单
2. 解析 commonData / buyerInfoVO / priceVO / itemInfoVO 四个子对象
3. 按 (account_id, external_order_id) upsert 到 xianyu_trade_order / xianyu_trade_order_item
4. 可选拉取退款订单补充状态（mtop.taobao.idle.merchant.refund.list）
"""
import asyncio
import datetime
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import async_session
from ..models.entities import XianyuTradeOrder, XianyuTradeOrderItem
from .xianyu_api_service import fetch_sold_orders_page

logger = logging.getLogger(__name__)

# 闲鱼订单状态文本 → 内部状态码（与商业版 _map_remote_order_status 一致）
# 0待付款 1已付款 2待发货 3已发货 4已完成 5已关闭 6待核验/退款处理中
_ORDER_STATUS_MAP = {
    "待付款": 0,
    "WAIT_BUYER_PAY": 0,
    "已付款": 1,
    "待发货": 2,
    "WAIT_SELLER_SEND_GOODS": 2,
    "已发货": 3,
    "待收货": 3,
    "WAIT_BUYER_CONFIRM_GOODS": 3,
    "交易成功": 4,
    "TRADE_FINISHED": 4,
    "交易关闭": 5,
    "TRADE_CLOSED": 5,
    "退款中": 6,
    "退款成功": 5,
    "已退款": 5,
    "退款关闭": 5,
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        try:
            return int(float(value))
        except (ValueError, TypeError, OverflowError):
            return default


def _map_order_status(raw_status: Any, in_refund: bool = False) -> int:
    """将闲鱼返回的订单状态文本映射为内部状态码。"""
    if in_refund:
        return 6
    status_text = _text(raw_status)
    return _ORDER_STATUS_MAP.get(status_text, 6)


def _parse_order_time(value: Any) -> Optional[datetime.datetime]:
    """解析闲鱼订单时间字段，支持 'YYYY-MM-DD HH:MM:SS' 和 'YYYY-MM-DD'。"""
    text_val = _text(value)
    if not text_val:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text_val, fmt)
        except ValueError:
            continue
    return None


def _parse_order_amount(
    total_price: Any = None,
    unit_price: Any = None,
    quantity: int = 1,
    *,
    price_vo: Optional[dict[str, Any]] = None,
    common: Optional[dict[str, Any]] = None,
    item: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """解析订单金额，全面支持闲鱼 mtop 各种金额字段（含 cent 分单位转换）。"""
    p_vo = price_vo or {}
    c_data = common or {}
    i_data = item or {}

    def money(value, multiplier=1, divisor=1):
        try:
            amount = Decimal(_text(value))
            if amount.is_finite() and 0 <= amount < 10**15:
                return f"{amount * multiplier / divisor:.2f}"
        except InvalidOperation:
            pass
        return None

    for val, divisor in (
        (p_vo.get("realPayPrice"), 1),
        (p_vo.get("actualPaidFee"), 1),
        (p_vo.get("realPayCent"), 100),
        (p_vo.get("payPrice"), 1),
        (c_data.get("payPrice"), 1),
        (p_vo.get("amountCent"), 100),
        (c_data.get("amountCent"), 100),
        (i_data.get("amountCent"), 100),
        (p_vo.get("totalCent"), 100),
    ):
        amount = money(val, divisor=divisor)
        if amount is not None:
            return amount

    for val in (
        total_price,
        p_vo.get("totalPrice"),
        p_vo.get("orderPrice"),
        c_data.get("totalPrice"),
        c_data.get("orderPrice"),
        i_data.get("totalPrice"),
        i_data.get("orderPrice"),
    ):
        amount = money(val)
        if amount is not None:
            return amount

    if quantity < 1:
        return None
    for val, divisor in (
        (unit_price, 1),
        (p_vo.get("auctionPrice"), 1),
        (p_vo.get("unitPrice"), 1),
        (c_data.get("price"), 1),
        (c_data.get("priceCent"), 100),
        (p_vo.get("priceCent"), 100),
        (i_data.get("priceCent"), 100),
    ):
        amount = money(val, multiplier=quantity, divisor=divisor)
        if amount is not None:
            return amount

    return None


def _detect_bargain_from_buttons(item: dict[str, Any]) -> bool:
    """检测订单是否为小刀订单：btnList 中存在 tradeAction=SKIP_PIN。

    参考商业版 order_service._parse_sold_order_item 的小刀判断逻辑。
    递归搜索整个订单数据，不依赖固定的层级位置。
    """
    def search(obj: Any) -> bool:
        if isinstance(obj, dict):
            btn_list = obj.get("btnList")
            if isinstance(btn_list, list):
                for btn in btn_list:
                    if isinstance(btn, dict) and btn.get("tradeAction") == "SKIP_PIN":
                        return True
            for v in obj.values():
                if search(v):
                    return True
        elif isinstance(obj, list):
            for v in obj:
                if search(v):
                    return True
        return False
    return search(item)


def _parse_remote_order_item(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    """解析闲鱼 mtop 返回的单条订单数据，参考商业版 _parse_remote_sold_order_item。"""
    if not isinstance(item, dict):
        return None

    common = item.get("commonData") if isinstance(item.get("commonData"), dict) else {}
    buyer_info = item.get("buyerInfoVO") if isinstance(item.get("buyerInfoVO"), dict) else {}
    price_vo = item.get("priceVO") if isinstance(item.get("priceVO"), dict) else {}
    item_info = item.get("itemInfoVO") if isinstance(item.get("itemInfoVO"), dict) else {}
    item_buy_info = common.get("itemBuyInfo") if isinstance(common.get("itemBuyInfo"), dict) else {}

    external_order_id = _text(common.get("orderId"))
    if not external_order_id:
        return None

    quantity = _safe_int(price_vo.get("buyNum", common.get("quantity")))
    goods_id_raw = _text(
        common.get("itemId") or item_info.get("itemId") or item_buy_info.get("itemId")
    )
    # XianyuTradeOrderItem.goods_id 是 BigInteger 列，需要数值类型而非字符串
    goods_id = _safe_int(goods_id_raw, 0) if goods_id_raw else 0
    goods_title = _text(
        item.get("itemTitle")
        or common.get("itemTitle")
        or item_info.get("title")
        or item_buy_info.get("title")
    ) or (f"商品 {goods_id}" if goods_id else "订单商品")
    goods_image = _text(
        common.get("itemMainPic")
        or item_info.get("itemPic")
        or item_buy_info.get("itemPic")
        or item.get("itemMainPic")
    )
    goods_price = _text(
        price_vo.get("auctionPrice")
        or price_vo.get("unitPrice")
        or item_info.get("price")
        or common.get("price")
    )
    if not goods_price:
        for c in (common.get("priceCent"), price_vo.get("priceCent"), item_info.get("priceCent")):
            if c is not None:
                try:
                    goods_price = f"{float(c) / 100.0:.2f}"
                    break
                except (ValueError, TypeError):
                    pass
    total_amount = _parse_order_amount(
        price_vo.get("totalPrice"),
        goods_price,
        quantity,
        price_vo=price_vo,
        common=common,
        item={**item_info, **item},
    )

    refund_flag = common.get("inRefund")
    in_refund = bool(refund_flag) and _text(refund_flag).lower() not in ("false", "0")
    order_status = _map_order_status(common.get("orderStatus"), in_refund)

    return {
        "external_order_id": external_order_id,
        "order_status": order_status,
        "total_amount": total_amount,
        "buyer_name": _text(buyer_info.get("userNick") or buyer_info.get("name")),
        "buyer_id": _text(buyer_info.get("buyerId")),
        "create_time": _parse_order_time(common.get("createTime")),
        "pay_time": _parse_order_time(
            common.get("payTime") or common.get("paymentTime") or common.get("paySuccessTime")
        ),
        "ship_time": _parse_order_time(
            common.get("deliveryTime") or common.get("consignTime") or common.get("shipTime")
        ),
        "confirm_time": _parse_order_time(common.get("endTime") or common.get("confirmTime")),
        "buyer_message": _text(common.get("buyerMessage") or common.get("leaveMessage")),
        "item_id": goods_id_raw,  # String 列，保留原始字符串
        "is_bargain": _detect_bargain_from_buttons(item),
        # 订单项
        "items": [
            {
                "goods_id": goods_id,  # BigInteger 列，已转换为 int
                "goods_title": goods_title,
                "goods_image": goods_image,
                "goods_price": goods_price,
                "goods_count": max(quantity, 1),
                "quantity": max(quantity, 1),
            }
        ],
    }


async def _replace_order_items(db: AsyncSession, order_id: int, items: list[Any]) -> None:
    """替换订单项：先软删旧的再插入新的。

    订单项写入失败不应连带丢弃订单主记录（平台已发货但商品信息缺失时尤其常见），
    因此用 SAVEPOINT 隔离，失败只回滚订单项并记日志。
    """
    try:
        async with db.begin_nested():
            await db.execute(
                text(
                    "UPDATE xianyu_trade_order_item SET deleted = 1, updated_time = CURRENT_TIMESTAMP "
                    "WHERE order_id = :oid AND deleted = 0"
                ),
                {"oid": order_id},
            )
            for item_data in items:
                if not isinstance(item_data, dict):
                    continue
                db.add(XianyuTradeOrderItem(
                    order_id=order_id,
                    goods_id=item_data.get("goods_id"),
                    goods_title=item_data.get("goods_title"),
                    goods_name=item_data.get("goods_title"),
                    goods_image=item_data.get("goods_image"),
                    goods_price=item_data.get("goods_price"),
                    goods_count=item_data.get("goods_count", 1),
                    quantity=item_data.get("quantity", 1),
                    deleted=0,
                ))
            await db.flush()
    except Exception as exc:
        logger.warning(
            "订单项写入失败，保留订单主记录 orderId=%s errorType=%s",
            order_id,
            type(exc).__name__,
        )


async def _upsert_order(db: AsyncSession, account_id: int, parsed: dict[str, Any]) -> tuple[str, str]:
    """按 (account_id, external_order_id) upsert 订单，返回 ("inserted"|"updated", external_order_id)。"""
    external_order_id = parsed["external_order_id"]

    result = await db.execute(
        select(XianyuTradeOrder).where(
            XianyuTradeOrder.account_id == account_id,
            XianyuTradeOrder.external_order_id == external_order_id,
            XianyuTradeOrder.deleted == 0,
        )
    )
    order = result.scalar_one_or_none()

    if order is None:
        order = XianyuTradeOrder(
            account_id=account_id,
            external_order_id=external_order_id,
            order_status=parsed["order_status"],
            total_amount=parsed["total_amount"],
            buyer_name=parsed["buyer_name"],
            buyer_id=parsed["buyer_id"],
            create_time=parsed["create_time"],
            pay_time=parsed["pay_time"],
            ship_time=parsed["ship_time"],
            confirm_time=parsed["confirm_time"],
            buyer_message=parsed["buyer_message"],
            item_id=parsed["item_id"],
            is_bargain=1 if parsed.get("is_bargain") else 0,
            is_rated=0,
            is_red_flower=0,
            deleted=0,
        )
        db.add(order)
        await db.flush()
        action = "inserted"
    else:
        if parsed.get("order_status") is not None:
            order.order_status = parsed["order_status"]
        if parsed.get("total_amount") is not None:
            order.total_amount = parsed["total_amount"]
        if parsed.get("buyer_name"):
            order.buyer_name = parsed["buyer_name"]
        if parsed.get("buyer_id"):
            order.buyer_id = parsed["buyer_id"]
        # 时间字段用 COALESCE 语义：远程有值才覆盖，避免清空已有数据
        if parsed.get("create_time"):
            order.create_time = parsed["create_time"]
        if parsed.get("pay_time"):
            order.pay_time = parsed["pay_time"]
        if parsed.get("ship_time"):
            order.ship_time = parsed["ship_time"]
        if parsed.get("confirm_time"):
            order.confirm_time = parsed["confirm_time"]
        if parsed.get("buyer_message"):
            order.buyer_message = parsed["buyer_message"]
        if parsed.get("item_id"):
            order.item_id = parsed["item_id"]
        # 小刀标记：只置 True 不回退（参考商业版 order_service 逻辑）
        if parsed.get("is_bargain") and not order.is_bargain:
            order.is_bargain = 1
        order.updated_time = datetime.datetime.now()
        action = "updated"

    # 替换订单项：先软删除旧的，再插入新的（失败不影响订单主记录）
    await _replace_order_items(db, order.id, parsed.get("items", []))

    return action, external_order_id


# 单账号订单全量同步进行中标记：并发入口（批量刷新/进页自动刷新/定时任务）
# 同时触发时只跑一份，其余直接跳过，避免重复打平台分页接口。
_order_sync_inflight: set = set()


async def sync_orders_for_account(
    account_id: int,
    max_pages: int = 20,
    page_size: int = 30,
) -> dict[str, Any]:
    """同步指定账号的闲鱼已售订单（单账号同一时刻只允许一个在执行）。

    已有同步在执行时返回 success=True + skipped=True 的零统计结果，
    调用方无需把它当失败处理。
    """
    if account_id in _order_sync_inflight:
        logger.info("订单同步跳过（该账号已有同步在执行）: accountId=%d", account_id)
        return {
            "success": True,
            "total": 0,
            "inserted": 0,
            "updated": 0,
            "failed": 0,
            "skipped": True,
            "message": "该账号订单同步正在进行中，本次跳过",
        }
    _order_sync_inflight.add(account_id)
    try:
        return await _sync_orders_for_account_impl(
            account_id, max_pages=max_pages, page_size=page_size
        )
    finally:
        _order_sync_inflight.discard(account_id)


async def _sync_orders_for_account_impl(
    account_id: int,
    max_pages: int = 20,
    page_size: int = 30,
) -> dict[str, Any]:
    """同步指定账号的闲鱼已售订单。

    流程：
    1. 分页调用 mtop.taobao.idle.trade.merchant.sold.get 拉取订单
    2. 逐条解析并 upsert 到本地数据库
    3. 返回同步统计

    Returns:
        {"success": True, "total": N, "inserted": N, "updated": N, "failed": N}
        或 {"success": False, "error": "..."}
    """
    logger.info("开始同步订单: accountId=%d", account_id)

    total_fetched = 0
    inserted = 0
    updated = 0
    failed = 0
    sold_item_ids_to_relist: list = []  # 新售订单对应的商品 ID，用于触发售整自动上架
    page_number = 1
    issue = {}

    try:
        while page_number <= max_pages:
            # 闲鱼 API 是同步 HTTP 调用，用 to_thread 避免阻塞事件循环
            page_result = await asyncio.to_thread(
                fetch_sold_orders_page,
                account_id=account_id,
                page_number=page_number,
                page_size=page_size,
            )

            if not page_result or not page_result.get("success"):
                error_msg = (page_result or {}).get("error", "订单平台接口暂不可用")
                error_code = (page_result or {}).get("errorCode", "ORDER_SYNC_UNAVAILABLE")
                logger.warning(
                    "订单分页拉取失败 accountId=%d page=%d errorCode=%s",
                    account_id,
                    page_number,
                    error_code,
                )
                issue = {"error": f"第 {page_number} 页：{error_msg}", "errorCode": error_code}
                break

            data = page_result.get("data", {})
            items = data.get("items", [])
            has_next = data.get("nextPage", False)
            total_count = data.get("totalCount", 0)

            page_inserted = page_updated = 0
            page_sold_items = []
            async with async_session() as db:
                for item in items:
                    try:
                        parsed = _parse_remote_order_item(item)
                        if not parsed:
                            failed += 1
                            continue
                        # 单笔订单用 SAVEPOINT 隔离：某笔订单失败只回滚它自己，
                        # 不影响同页其它订单落库（订单项失败已在 _replace_order_items 内兜底）
                        async with db.begin_nested():
                            action, _ = await _upsert_order(db, account_id, parsed)
                        if action == "inserted":
                            page_inserted += 1
                            # 新售订单插入成功，记录商品 ID 用于触发售整自动上架钩子
                            sold_item_id = str(parsed.get("item_id") or "").strip()
                            if sold_item_id:
                                page_sold_items.append(sold_item_id)
                        else:
                            page_updated += 1
                    except Exception as exc:
                        failed += 1
                        logger.warning(
                            "订单入库失败 accountId=%d externalOrderId=%s errorType=%s",
                            account_id,
                            str((item or {}).get("commonData", {}).get("orderId", ""))[:200]
                            if isinstance(item, dict) else "",
                            type(exc).__name__,
                        )
                await db.commit()
            inserted += page_inserted
            updated += page_updated
            total_fetched += page_inserted + page_updated
            sold_item_ids_to_relist.extend(page_sold_items)

            logger.info(
                "订单同步分页完成: accountId=%d page=%d 本页=%d 累计=%d 总数=%s",
                account_id, page_number, len(items), total_fetched, total_count,
            )

            if not has_next:
                break
            if page_number == max_pages:
                issue = {"error": f"已读取 {max_pages} 页，平台仍有后续订单", "errorCode": "ORDER_SYNC_PAGE_LIMIT"}
                break

            page_number += 1
            # 风控间隔
            await asyncio.sleep(0.5)

        logger.info(
            "订单同步完成: accountId=%d total=%d inserted=%d updated=%d failed=%d",
            account_id, total_fetched, inserted, updated, failed,
        )

        # 售整自动上架钩子：新售订单触发后立即异步重发
        # 失败不影响订单同步主流程；relist_scheduler 也会每 3 分钟兜底扫描
        if sold_item_ids_to_relist:
            try:
                from .relist_service import relist_sold_item
                for sold_item_id in sold_item_ids_to_relist:
                    asyncio.create_task(
                        relist_sold_item(account_id, sold_item_id),
                        name=f"relist_hook_{account_id}_{sold_item_id}",
                    )
            except Exception as exc:
                logger.warning(
                    "触发售整自动上架失败 accountId=%d errorType=%s",
                    account_id, type(exc).__name__,
                )
        if failed and not issue:
            issue = {"error": f"{failed} 笔订单无法读取或入库，请重试同步", "errorCode": "ORDER_SYNC_ROW_FAILED"}
        return {
            "success": not issue,
            "partial": bool(issue and total_fetched),
            **issue,
            "total": total_fetched,
            "inserted": inserted,
            "updated": updated,
            "failed": failed,
        }
    except Exception as exc:
        logger.error(
            "订单同步异常 accountId=%d errorType=%s",
            account_id,
            type(exc).__name__,
        )
        return {
            "success": False,
            "partial": bool(total_fetched),
            "total": total_fetched,
            "inserted": inserted,
            "updated": updated,
            "failed": failed,
            "error": f"第 {page_number} 页同步未完成，请重试",
            "errorCode": "ORDER_SYNC_FAILED",
        }


async def upsert_remote_order(
    account_id: int,
    item: dict[str, Any],
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """把单条远程订单原始数据（mtop sold.get 的 items[] 元素）落库。

    供 WebSocket 实时付款事件、单笔补录、批量刷新复用。幂等：按
    (account_id, external_order_id) upsert；订单项写入失败不会丢弃订单主记录。

    Returns:
        {"success": True, "action": "inserted"|"updated", "externalOrderId": "..."}
        或 {"success": False, "error": "...", "errorCode": "..."}
    """
    if not account_id:
        return {"success": False, "error": "账号ID不能为空", "errorCode": "INVALID_ACCOUNT"}
    try:
        parsed = _parse_remote_order_item(item)
        if not parsed:
            return {
                "success": False,
                "error": "订单数据无法解析（缺少 orderId）",
                "errorCode": "ORDER_PARSE_FAILED",
            }
        async with async_session() as db:
            action, external_order_id = await _upsert_order(db, account_id, parsed)
            if commit:
                await db.commit()
        logger.info(
            "单笔订单落库完成 accountId=%d externalOrderId=%s action=%s",
            account_id, external_order_id, action,
        )
        return {
            "success": True,
            "action": action,
            "externalOrderId": external_order_id,
            "orderStatus": parsed.get("order_status"),
        }
    except Exception as exc:
        logger.error(
            "单笔订单落库失败 accountId=%d errorType=%s",
            account_id, type(exc).__name__, exc_info=True,
        )
        return {
            "success": False,
            "error": "订单写入失败，请稍后重试",
            "errorCode": "ORDER_UPSERT_FAILED",
        }


async def sync_order_by_external_id(
    account_id: int,
    external_order_id: str,
    max_pages: int = 10,
    page_size: int = 30,
) -> dict[str, Any]:
    """按外部订单号补录单笔订单：分页扫描卖家已售订单直到命中该订单号。

    平台没有按 orderId 查询单笔订单的 mtop 接口（sold.get 的 orderIds 参数
    当前实现固定为空串），因此这里用分页扫描 + 命中即停的方式补录。

    Returns:
        {"success": True, "found": True, "action": "...", "externalOrderId": "..."}
        / {"success": True, "found": False, "externalOrderId": "..."}
        / {"success": False, "error": "...", "errorCode": "..."}
    """
    target = _text(external_order_id)
    if not account_id:
        return {"success": False, "error": "账号ID不能为空", "errorCode": "INVALID_ACCOUNT"}
    if not target:
        return {
            "success": False,
            "error": "订单号不能为空",
            "errorCode": "INVALID_EXTERNAL_ORDER_ID",
        }

    page_number = 1
    try:
        while page_number <= max_pages:
            page_result = await asyncio.to_thread(
                fetch_sold_orders_page,
                account_id=account_id,
                page_number=page_number,
                page_size=page_size,
            )
            if not page_result or not page_result.get("success"):
                return {
                    "success": False,
                    "error": (page_result or {}).get("error", "订单平台接口暂不可用"),
                    "errorCode": (page_result or {}).get(
                        "errorCode", "ORDER_SYNC_UNAVAILABLE"
                    ),
                }

            data = page_result.get("data", {})
            items = data.get("items", [])
            for item in items:
                parsed = _parse_remote_order_item(item)
                if not parsed:
                    continue
                if parsed["external_order_id"] != target:
                    continue
                result = await upsert_remote_order(account_id, item)
                if result.get("success"):
                    result["found"] = True
                return result

            if not data.get("nextPage", False):
                break
            page_number += 1
            await asyncio.sleep(0.5)

        logger.info(
            "单笔订单补录未命中 accountId=%d externalOrderId=%s pages=%d",
            account_id, target, page_number,
        )
        return {"success": True, "found": False, "externalOrderId": target}
    except Exception as exc:
        logger.error(
            "单笔订单补录异常 accountId=%d errorType=%s",
            account_id, type(exc).__name__, exc_info=True,
        )
        return {
            "success": False,
            "error": "订单补录未完成，请检查账号状态后重试",
            "errorCode": "ORDER_SYNC_FAILED",
        }
