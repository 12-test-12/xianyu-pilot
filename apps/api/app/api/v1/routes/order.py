import asyncio
import datetime
import logging
import math
from typing import Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.database import get_db
from ....core.response import ResultObject
from ....models.entities import (
    XianyuAccount,
    XianyuGoods,
    XianyuTradeOrder,
    XianyuTradeOrderItem,
)
from ....schemas.order import (
    ConfirmFreeshippingReqDTO,
    ConfirmShipmentReqDTO,
    OrderListData,
    OrderQueryReqDTO,
    OrderVO,
    SoldOrderSyncReqDTO,
)
from ....services.xianyu_api_service import confirm_order_shipment, confirm_freeshipping
from ....services.xianyu_order_sync import (
    sync_order_by_external_id,
    sync_orders_for_account,
)
from ..deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/order")

# 批量刷新扩展 router（前端 order.js 调用 POST /api/order/batchRefresh，参考项目无实现）
batch_refresh_router = APIRouter(prefix="/order", tags=["order-batch"])


_ORDER_SORT_FIELD_MAP = {
    "createdAt": XianyuTradeOrder.create_time,
    "buyerName": XianyuTradeOrder.buyer_name,
    "orderStatus": XianyuTradeOrder.order_status,
}


def _resolve_order_sort(req: "OrderQueryReqDTO"):
    """根据请求中的 sort_field / sort_order 构造排序条件，默认 create_time DESC。"""
    field_name = (req.sort_field or "createdAt").strip()
    column = _ORDER_SORT_FIELD_MAP.get(field_name, XianyuTradeOrder.create_time)
    order = (req.sort_order or "desc").strip().lower()
    return column.asc() if order == "asc" else column.desc()


def _format_dt(value) -> Optional[str]:
    return str(value) if value else None


def trade_order_to_vo(
    order: XianyuTradeOrder,
    item: Optional[XianyuTradeOrderItem] = None,
    goods_extra: Optional[dict] = None,
) -> OrderVO:
    """订单实体 → VO。

    item / goods_extra 为可选的关联订单项与商品扩展信息；传入时会补齐
    商品标题、图片、外部商品 ID、数量、发货时间等前端展示字段。
    """
    goods_extra = goods_extra or {}
    external_goods_id = None
    goods_title = None
    goods_image = None
    goods_price = None
    quantity = None
    goods_count = None
    sku_id = None
    sku_name = None
    if item is not None:
        external_goods_id = goods_extra.get("externalGoodsId") or item.goods_id
        goods_title = item.goods_title or item.goods_name
        goods_image = item.goods_image or goods_extra.get("goodsImage")
        goods_price = str(item.goods_price) if item.goods_price is not None else None
        goods_count = item.goods_count or item.quantity or 1
        quantity = item.quantity or item.goods_count or 1
        sku_id = item.sku_id
        sku_name = item.sku_name

    return OrderVO(
        id=order.id,
        account_id=order.account_id,
        external_order_id=order.external_order_id,
        order_status=order.order_status,
        buyer_name=order.buyer_name,
        buyer_id=order.buyer_id,
        total_amount=order.total_amount,
        create_time=_format_dt(order.create_time),
        pay_time=_format_dt(order.pay_time),
        ship_time=_format_dt(order.ship_time),
        confirm_time=_format_dt(order.confirm_time),
        buyer_message=order.buyer_message,
        item_id=order.item_id or (str(external_goods_id) if external_goods_id else None),
        is_bargain=order.is_bargain,
        is_rated=order.is_rated,
        is_red_flower=order.is_red_flower,
        created_time=_format_dt(order.created_time),
        updated_time=_format_dt(order.updated_time),
        external_goods_id=(
            str(external_goods_id) if external_goods_id is not None else None
        ),
        goods_id=item.goods_id if item is not None else None,
        goods_image=goods_image,
        goods_title=goods_title,
        goods_price=goods_price,
        goods_count=goods_count,
        quantity=quantity,
        sku_id=sku_id,
        sku_name=sku_name,
        xianyu_account_id=order.account_id,
        xy_goods_id=order.item_id or (
            str(external_goods_id) if external_goods_id is not None else None
        ),
        order_id=order.external_order_id,
        total_price=order.total_amount,
    )


async def _load_order_items(
    db: AsyncSession, orders: list[XianyuTradeOrder]
) -> dict[int, tuple[XianyuTradeOrderItem, dict]]:
    """批量加载订单项与商品扩展信息，返回 {order_id: (item, goods_extra)}。

    order_item.goods_id 存的是平台 itemId（数值），本地商品表用
    external_goods_id 关联该值；XianyuGoods.id 是自增主键，二者不能互查。
    """
    order_ids = [int(order.id) for order in orders if order.id is not None]
    if not order_ids:
        return {}
    item_result = await db.execute(
        select(XianyuTradeOrderItem)
        .where(
            XianyuTradeOrderItem.deleted == 0,
            XianyuTradeOrderItem.order_id.in_(order_ids),
        )
        .order_by(XianyuTradeOrderItem.id.asc())
    )
    order_items = item_result.scalars().all()
    goods_keys = sorted({str(int(item.goods_id)) for item in order_items if item.goods_id})
    goods_extra: dict[str, dict] = {}
    if goods_keys:
        goods_result = await db.execute(
            select(XianyuGoods).where(
                XianyuGoods.external_goods_id.in_(goods_keys),
                XianyuGoods.deleted == 0,
            )
        )
        for goods in goods_result.scalars():
            key = str(goods.external_goods_id or "").strip()
            if key:
                goods_extra[key] = {
                    "externalGoodsId": goods.external_goods_id,
                    "goodsImage": goods.cover_pic or goods.image_url,
                }
    result: dict[int, tuple[XianyuTradeOrderItem, dict]] = {}
    for item in order_items:
        order_id = int(item.order_id)
        if order_id in result:
            continue  # 每个订单只取第一个订单项用于 VO 摘要字段
        extra = goods_extra.get(str(int(item.goods_id)), {}) if item.goods_id else {}
        result[order_id] = (item, extra)
    return result


async def _orders_to_vos(
    db: AsyncSession, orders: list[XianyuTradeOrder]
) -> list[OrderVO]:
    items_by_order = await _load_order_items(db, orders)
    vos = []
    for order in orders:
        item, extra = items_by_order.get(int(order.id), (None, {}))
        vos.append(trade_order_to_vo(order, item, extra))
    return vos


async def _resolve_sync_account_ids(
    db: AsyncSession, requested_account_id: Optional[int]
) -> list[int]:
    """确定本次刷新需要同步的账号：显式指定优先，否则取全部启用账号。"""
    if requested_account_id:
        return [int(requested_account_id)]
    result = await db.execute(
        select(XianyuAccount.id).where(
            XianyuAccount.deleted == 0,
            XianyuAccount.status == 1,
        )
    )
    return [int(account_id) for account_id in result.scalars().all()]


@router.post("/list", response_model=ResultObject[OrderListData])
async def list_orders(
    req: OrderQueryReqDTO,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        page_num = max(req.page_num or 1, 1)
        page_size = max(min(req.page_size or 20, 100), 1)
        query = select(XianyuTradeOrder)
        if req.xianyu_account_id is not None:
            query = query.where(XianyuTradeOrder.account_id == req.xianyu_account_id)
        if req.xy_goods_id:
            # xy_goods_id 是商品维度过滤：订单 item_id 或关联订单项 goods_id 匹配
            goods_key = str(req.xy_goods_id).strip()
            goods_key_int = None
            try:
                goods_key_int = int(goods_key)
            except (TypeError, ValueError):
                goods_key_int = None
            item_conditions = [XianyuTradeOrder.item_id == goods_key]
            if goods_key_int is not None:
                # goods_id 是数值列；仅在键可解析为数值时才按订单项匹配。
                # 否则（非数字键）不能退化成 goods_id IS NULL，那会把
                # 所有订单项 goods_id 为空的订单都拉进来。
                item_match = select(XianyuTradeOrderItem.order_id).where(
                    XianyuTradeOrderItem.deleted == 0,
                    XianyuTradeOrderItem.goods_id == goods_key_int,
                )
                item_conditions.append(XianyuTradeOrder.id.in_(item_match))
            query = query.where(or_(*item_conditions))
        if req.order_status is not None:
            query = query.where(XianyuTradeOrder.order_status == req.order_status)

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        offset = (page_num - 1) * page_size
        query = query.order_by(_resolve_order_sort(req)).offset(offset).limit(page_size)
        result = await db.execute(query)
        orders = result.scalars().all()

        records = await _orders_to_vos(db, orders)
        pages = math.ceil(total / page_size) if total > 0 else 0
        return ResultObject.success(
            OrderListData(
                records=records,
                total=total,
                page_num=page_num,
                page_size=page_size,
                pages=pages,
            )
        )
    except Exception as e:
        logger.error("查询订单列表失败", exc_info=True)
        return ResultObject.internal_error()


@router.post("/confirmShipment", response_model=ResultObject[str])
async def confirm_shipment(
    req: ConfirmShipmentReqDTO,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """确认发货（同步商业版能力：调用闲鱼 API 真实确认发货）。

    - 普通订单走 mtop.taobao.idle.logistic.consign.dummy（无物流虚拟发货）
    - 小刀订单（is_bargain=1）走 mtop.idle.groupon.activity.seller.freeshipping（免拼发货）
    - 已发货（ORDER_ALREADY_DELIVERY）视为幂等成功
    - 成功后更新本地 order_status=3, ship_time=now
    """
    try:
        if not req.order_id:
            return ResultObject.failed("订单ID不能为空")
        result = await db.execute(
            select(XianyuTradeOrder).where(
                XianyuTradeOrder.account_id == req.xianyu_account_id,
                XianyuTradeOrder.external_order_id == req.order_id,
                XianyuTradeOrder.deleted == 0,
            )
        )
        order = result.scalar_one_or_none()
        if not order:
            return ResultObject.failed("订单不存在")
        if order.order_status == 3:
            return ResultObject.success("订单已确认发货，无需重复操作")

        # 根据是否小刀订单选择发货方式
        is_bargain = bool(order.is_bargain)
        api_result = await asyncio.to_thread(
            confirm_order_shipment,
            account_id=req.xianyu_account_id,
            order_id=req.order_id,
            is_bargain=is_bargain,
            item_id=order.item_id,
            buyer_id=order.buyer_id,
        )

        if not api_result or not api_result.get("success"):
            error_msg = (api_result or {}).get("message") or (api_result or {}).get("error") or "闲鱼确认发货失败"
            logger.warning(
                "确认发货失败 accountId=%d orderId=%s isBargain=%s error=%s",
                req.xianyu_account_id, req.order_id, is_bargain, error_msg,
            )
            return ResultObject.failed(error_msg)

        # 闲鱼 API 成功后更新本地状态
        order.order_status = 3
        order.ship_time = datetime.datetime.now()
        await db.commit()

        ship_method = api_result.get("ship_method", "virtual" if not is_bargain else "freeshipping")
        idempotent = "（已发货幂等）" if api_result.get("idempotent") else ""
        logger.info(
            "确认发货成功 accountId=%d orderId=%s shipMethod=%s%s",
            req.xianyu_account_id, req.order_id, ship_method, idempotent,
        )
        return ResultObject.success(f"确认发货成功（{ship_method}）{idempotent}")
    except Exception as e:
        logger.error("确认发货失败", exc_info=True)
        return ResultObject.internal_error()


@router.post("/confirmFreeshipping", response_model=ResultObject[str])
async def confirm_freeshipping_endpoint(
    req: ConfirmFreeshippingReqDTO,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """免拼发货（小刀订单专用）。

    调用闲鱼 mtop.idle.groupon.activity.seller.freeshipping 接口。
    必须提供 item_id 和 buyer_id（闲鱼接口要求整数类型）。
    """
    try:
        if not req.order_id:
            return ResultObject.failed("订单ID不能为空")
        if req.item_id is None or req.buyer_id is None:
            return ResultObject.failed("免拼发货必须提供商品ID和买家ID")

        result = await db.execute(
            select(XianyuTradeOrder).where(
                XianyuTradeOrder.account_id == req.xianyu_account_id,
                XianyuTradeOrder.external_order_id == req.order_id,
                XianyuTradeOrder.deleted == 0,
            )
        )
        order = result.scalar_one_or_none()
        if not order:
            return ResultObject.failed("订单不存在")
        if order.order_status == 3:
            return ResultObject.success("订单已确认发货，无需重复操作")

        api_result = await asyncio.to_thread(
            confirm_freeshipping,
            account_id=req.xianyu_account_id,
            order_id=req.order_id,
            item_id=req.item_id,
            buyer_id=req.buyer_id,
        )

        if not api_result or not api_result.get("success"):
            error_msg = (api_result or {}).get("message") or (api_result or {}).get("error") or "免拼发货失败"
            logger.warning(
                "免拼发货失败 accountId=%d orderId=%s itemId=%s buyerId=%s error=%s",
                req.xianyu_account_id, req.order_id, req.item_id, req.buyer_id, error_msg,
            )
            return ResultObject.failed(error_msg)

        order.order_status = 3
        order.ship_time = datetime.datetime.now()
        order.is_bargain = 1
        await db.commit()

        idempotent = "（已发货幂等）" if api_result.get("idempotent") else ""
        logger.info(
            "免拼发货成功 accountId=%d orderId=%s%s",
            req.xianyu_account_id, req.order_id, idempotent,
        )
        return ResultObject.success(f"免拼发货成功{idempotent}")
    except Exception as e:
        logger.error("免拼发货失败", exc_info=True)
        return ResultObject.internal_error()


@router.post("/syncSoldOrders", response_model=ResultObject[dict])
async def sync_sold_orders(
    req: SoldOrderSyncReqDTO,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """同步闲鱼已售订单（同步商业版能力：调用真实订单同步流程）。

    通过 mtop.taobao.idle.trade.merchant.sold.get 分页拉取远程订单并 upsert 到本地。
    """
    try:
        if not req.xianyu_account_id:
            return ResultObject.failed("账号ID不能为空")

        result = await sync_orders_for_account(account_id=req.xianyu_account_id)

        if not result.get("success"):
            error_msg = result.get("error") or "订单同步失败"
            error_code = result.get("errorCode", "ORDER_SYNC_FAILED")
            logger.warning(
                "订单同步失败 accountId=%d errorCode=%s error=%s",
                req.xianyu_account_id, error_code, error_msg,
            )
            return ResultObject.failed(error_msg)

        logger.info(
            "订单同步成功 accountId=%d total=%d inserted=%d updated=%d failed=%d",
            req.xianyu_account_id,
            result.get("total", 0),
            result.get("inserted", 0),
            result.get("updated", 0),
            result.get("failed", 0),
        )
        return ResultObject.success({
            "message": "同步成功",
            "synced_count": result.get("total", 0),
            "inserted": result.get("inserted", 0),
            "updated": result.get("updated", 0),
            "failed": result.get("failed", 0),
        })
    except Exception as e:
        logger.error("同步鱼小铺卖家订单列表失败", exc_info=True)
        return ResultObject.internal_error()


# ==================== 批量刷新订单（先远程同步，再回读本地） ====================

@batch_refresh_router.post("/batchRefresh", response_model=ResultObject[dict])
async def batch_refresh_orders(
    data: Optional[dict] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """批量刷新订单：先触发远程同步，再返回本地最新订单数据。

    - 指定 xianyuAccountId / accountId 时只同步该账号，否则同步全部启用账号
    - 指定 orderIds 时对本地缺失的订单号做单笔补录（扫描远程已售订单）
    - 远程同步失败不抛异常，错误原因放在返回体 syncErrors 中
    - 返回结构兼容既有字段 {message, refreshed_count, records}，并附带
      refreshedCount / syncedCount / syncErrors / syncedAccounts
    """
    data = data or {}
    order_ids = [
        str(item).strip() for item in (data.get("orderIds") or []) if str(item).strip()
    ]
    raw_account_id = data.get("xianyuAccountId") or data.get("accountId")
    account_id: Optional[int] = None
    if raw_account_id not in (None, ""):
        try:
            account_id = int(raw_account_id)
        except (TypeError, ValueError):
            return ResultObject.validate_failed("账号ID格式无效")

    want_sync = data.get("sync")
    do_sync = True if want_sync is None else bool(want_sync)

    sync_errors: list[dict] = []
    synced_accounts: list[int] = []
    synced_count = 0
    inserted = 0
    updated = 0
    failed = 0

    if do_sync:
        try:
            account_ids = await _resolve_sync_account_ids(db, account_id)
        except Exception as e:
            logger.warning("解析待同步账号失败 errorType=%s", type(e).__name__)
            account_ids = [account_id] if account_id else []
        # 结束本会话已开启的读事务：远程同步由其它会话写入，本会话若停留在
        # 旧快照里，就会"同步成功却看不到新订单"。
        try:
            await db.rollback()
        except Exception as e:
            logger.warning("释放刷新前事务失败 errorType=%s", type(e).__name__)
        for sync_account_id in account_ids:
            try:
                result = await sync_orders_for_account(account_id=sync_account_id)
            except Exception as e:
                logger.error(
                    "批量刷新远程同步异常 accountId=%d errorType=%s",
                    sync_account_id, type(e).__name__, exc_info=True,
                )
                sync_errors.append({
                    "accountId": sync_account_id,
                    "error": "订单同步未完成，请检查账号状态后重试",
                    "errorCode": "ORDER_SYNC_FAILED",
                })
                continue
            if not result.get("success"):
                error_msg = result.get("error") or "订单同步失败"
                logger.warning(
                    "批量刷新远程同步失败 accountId=%d errorCode=%s error=%s",
                    sync_account_id, result.get("errorCode"), error_msg,
                )
                sync_errors.append({
                    "accountId": sync_account_id,
                    "error": error_msg,
                    "errorCode": result.get("errorCode", "ORDER_SYNC_FAILED"),
                })
                continue
            synced_accounts.append(sync_account_id)
            synced_count += int(result.get("total") or 0)
            inserted += int(result.get("inserted") or 0)
            updated += int(result.get("updated") or 0)
            failed += int(result.get("failed") or 0)

    # 指定 orderIds 时，对本地仍缺失的订单号做单笔补录
    missing_order_ids = order_ids
    if order_ids and do_sync:
        try:
            existing_result = await db.execute(
                select(XianyuTradeOrder.external_order_id).where(
                    XianyuTradeOrder.external_order_id.in_(order_ids),
                    XianyuTradeOrder.deleted == 0,
                )
            )
            existing = {
                str(value) for value in existing_result.scalars().all() if value
            }
            missing_order_ids = [oid for oid in order_ids if oid not in existing]
        except Exception as e:
            logger.warning("查询待补录订单失败 errorType=%s", type(e).__name__)

    if do_sync and missing_order_ids:
        backfill_account_ids = (
            [account_id] if account_id else await _resolve_sync_account_ids(db, None)
        )
        for target_order_id in missing_order_ids:
            for backfill_account_id in backfill_account_ids:
                try:
                    backfill = await sync_order_by_external_id(
                        backfill_account_id, target_order_id
                    )
                except Exception as e:
                    logger.error(
                        "订单单笔补录异常 accountId=%d orderId=%s errorType=%s",
                        backfill_account_id, target_order_id, type(e).__name__,
                        exc_info=True,
                    )
                    sync_errors.append({
                        "accountId": backfill_account_id,
                        "orderId": target_order_id,
                        "error": "订单补录未完成，请稍后重试",
                        "errorCode": "ORDER_BACKFILL_FAILED",
                    })
                    continue
                if not backfill.get("success"):
                    sync_errors.append({
                        "accountId": backfill_account_id,
                        "orderId": target_order_id,
                        "error": backfill.get("error") or "订单补录失败",
                        "errorCode": backfill.get("errorCode", "ORDER_BACKFILL_FAILED"),
                    })
                    continue
                if backfill.get("found"):
                    synced_count += 1
                    if backfill.get("action") == "inserted":
                        inserted += 1
                    else:
                        updated += 1
                    break

    # 结束本会话此前的读事务：远程同步在其它会话写入，若不先提交，
    # 下面的回读会停留在旧快照里，导致"同步了却看不到新订单"。
    if do_sync:
        try:
            await db.commit()
        except Exception as e:
            logger.warning("刷新前提交读事务失败 errorType=%s", type(e).__name__)
            await db.rollback()

    query = select(XianyuTradeOrder).where(XianyuTradeOrder.deleted == 0)
    if account_id:
        query = query.where(XianyuTradeOrder.account_id == account_id)
    if order_ids:
        query = query.where(XianyuTradeOrder.external_order_id.in_(order_ids))
    query = query.order_by(XianyuTradeOrder.id.desc()).limit(100)
    result = await db.execute(query)
    orders = result.scalars().all()
    records = await _orders_to_vos(db, orders)

    message = "刷新成功"
    if sync_errors:
        message = f"刷新完成，但有 {len(sync_errors)} 个同步错误"

    return ResultObject.success({
        "message": message,
        "refreshed_count": len(records),
        "refreshedCount": len(records),
        "records": [r.model_dump() if hasattr(r, "model_dump") else r for r in records],
        "syncErrors": sync_errors,
        "syncedAccounts": synced_accounts,
        "syncedCount": synced_count,
        "inserted": inserted,
        "updated": updated,
        "failed": failed,
    })

