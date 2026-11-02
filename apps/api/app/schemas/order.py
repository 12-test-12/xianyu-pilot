from typing import Optional, List, Any, Literal
from pydantic import ConfigDict, Field, field_validator, model_validator
from ..core.camel import CamelModel


class OrderQueryReqDTO(CamelModel):
    xianyu_account_id: Optional[int] = None
    xy_goods_id: Optional[str] = None
    order_status: Optional[int] = None
    page_num: Optional[int] = 1
    page_size: Optional[int] = 20
    # 排序字段：createdAt / buyerName / orderStatus（其它值回退为默认 createdAt）
    sort_field: Optional[str] = None
    # 排序方向：asc / desc（默认 desc）
    sort_order: Optional[str] = None


class ConfirmShipmentReqDTO(CamelModel):
    xianyu_account_id: int
    order_id: str


class ConfirmFreeshippingReqDTO(CamelModel):
    """免拼发货请求 DTO（小刀订单专用）。

    必须提供 item_id 和 buyer_id，闲鱼免拼接口要求这两个字段为整数类型。
    """
    xianyu_account_id: int
    order_id: str
    item_id: Any = None
    buyer_id: Any = None


class SoldOrderSyncReqDTO(CamelModel):
    xianyu_account_id: int


class ManualDeliveryReqDTO(CamelModel):
    model_config = ConfigDict(extra="forbid")

    delivery_mode: Literal["text", "card"] = "text"
    # 自定义发货时必填；货源库发货（source_id 非空）时可为空，由后端读取货源内容
    delivery_content: str = Field(default="", max_length=10_000)
    quantity_requested: int = Field(default=1, ge=1, le=100)
    idempotency_key: Optional[str] = Field(
        default=None,
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    # 货源库发货：传入货源 ID 时从 delivery_text_source 读取内容
    source_id: Optional[int] = Field(default=None, ge=1)
    # 触发时机：付款后 / 确认收货后 / 评价后（手动发货仅作记录，默认付款后）
    delivery_timing: Optional[Literal["after_payment", "after_receipt", "after_review"]] = "after_payment"

    @field_validator("delivery_content")
    @classmethod
    def normalize_delivery_content(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def _validate_content_or_source(self) -> "ManualDeliveryReqDTO":
        # 自定义发货必须有内容；货源库发货内容由后端解析
        if not self.source_id and not self.delivery_content:
            raise ValueError("发货内容不能为空（或提供 sourceId 从货源库读取）")
        return self


class OrderVO(CamelModel):
    """适配新 XianyuTradeOrder 实体的 DTO"""
    id: Optional[int] = None
    # 新实体字段
    account_id: Optional[int] = None          # 原 xianyu_account_id
    external_order_id: Optional[str] = None   # 原 order_id
    order_status: Optional[int] = None
    buyer_name: Optional[str] = None
    buyer_id: Optional[str] = None
    total_amount: Optional[str] = None        # 原 total_price
    create_time: Optional[str] = None
    pay_time: Optional[str] = None
    ship_time: Optional[str] = None
    confirm_time: Optional[str] = None
    buyer_message: Optional[str] = None
    item_id: Optional[str] = None
    is_bargain: Optional[int] = None
    is_rated: Optional[int] = None
    is_red_flower: Optional[int] = None
    created_time: Optional[str] = None
    updated_time: Optional[str] = None
    # 商品维度字段（来自关联 xianyu_trade_order_item / xianyu_goods）
    external_goods_id: Optional[str] = None
    goods_id: Optional[int] = None
    goods_image: Optional[str] = None
    quantity: Optional[int] = None
    goods_count_total: Optional[int] = None
    sku_id: Optional[str] = None
    sku_name: Optional[str] = None
    # 向后兼容字段
    xianyu_account_id: Optional[int] = None
    xy_goods_id: Optional[str] = None
    order_id: Optional[str] = None
    goods_title: Optional[str] = None
    goods_price: Optional[str] = None
    goods_count: Optional[int] = None
    total_price: Optional[str] = None


class OrderListData(CamelModel):
    records: List[OrderVO] = []
    total: int = 0
    page_num: int = 1
    page_size: int = 20
    pages: int = 0


class OrderBatchRefreshReqDTO(CamelModel):
    """POST /order/batchRefresh 请求体。

    兼容前端历史字段：orderIds / xianyuAccountId / accountId；
    可选 sync 控制是否触发远程同步（默认 True）。
    """
    order_ids: List[str] = []
    xianyu_account_id: Optional[int] = None
    account_id: Optional[int] = None
    sync: bool = True

    @model_validator(mode="after")
    def _normalize_ids(self) -> "OrderBatchRefreshReqDTO":
        self.order_ids = [
            str(item).strip() for item in (self.order_ids or []) if str(item).strip()
        ]
        return self
