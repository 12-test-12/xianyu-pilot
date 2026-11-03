"""账号凭据落库的统一实现：添加/恢复账号与软删除的唯一入口。

/account/add、/account/manualAdd、compat POST /xianyu/accounts 以及两处
删除接口此前各自复制这套逻辑；修复只改一处就会在其它入口重新引入缺陷，
因此收敛到本模块。
"""

import re

from sqlalchemy import select, update

from ..core.cookie_crypto import encrypt_cookie_for_storage
from ..models.entities import XianyuAccount, XianyuAccountAuth, XianyuAccountRuntime


class AccountUpsertError(ValueError):
    """携带面向用户的中文错误信息的落库失败。"""


def extract_unb_from_cookie(cookie: str):
    """从 Cookie 字符串中提取 unb（闲鱼用户 ID）。"""
    if not cookie:
        return None
    for part in cookie.split("; "):
        if part.startswith("unb="):
            return part[4:]
    return None


def extract_m_h5_tk_from_cookie(cookie: str) -> str:
    """从 Cookie 字符串中提取 _m_h5_tk 值。"""
    if not cookie:
        return ""
    match = re.search(r"_m_h5_tk=([^;]+)", cookie)
    return match.group(1) if match else ""


async def upsert_account_with_cookie(
    db,
    *,
    cookie: str,
    unb: str,
    remark=None,
) -> XianyuAccount:
    """按 unb 创建或恢复账号记录，并把 Cookie 写入最新的 auth/runtime 行。

    - unb 对应的账号已存在且未软删除 → 抛 AccountUpsertError("账号已存在")
    - unb 只有软删除记录 → 恢复（deleted=0, status=1），remark 非 None 时更新备注
    - auth/runtime 存在多行时只激活最新一条，冗余行统一置软删除，
      避免后续 scalar_one_or_none 查询抛 MultipleResultsFound
    - 不负责 commit，由调用方统一提交（保证账号与凭据原子落库）
    """
    result = await db.execute(
        select(XianyuAccount)
        .where(XianyuAccount.external_uid == unb)
        .order_by(XianyuAccount.deleted.asc())
        .limit(1)
    )
    account = result.scalar_one_or_none()
    if account:
        if account.deleted == 0:
            raise AccountUpsertError("账号已存在")
        # 恢复软删除账号
        account.deleted = 0
        account.status = 1
        if remark is not None:
            account.remark = remark
    else:
        account = XianyuAccount(
            external_uid=unb,
            remark=remark,
            status=1,
        )
        db.add(account)
        await db.flush()

    m_h5_tk = extract_m_h5_tk_from_cookie(cookie)
    encrypted_cookie = encrypt_cookie_for_storage(cookie)
    encrypted_token = encrypt_cookie_for_storage(m_h5_tk) if m_h5_tk else None

    auth_result = await db.execute(
        select(XianyuAccountAuth)
        .where(XianyuAccountAuth.account_id == account.id)
        .order_by(XianyuAccountAuth.id.desc())
    )
    auth_rows = auth_result.scalars().all()
    if auth_rows:
        existing_auth = auth_rows[0]
        existing_auth.deleted = 0
        existing_auth.encrypted_cookie = encrypted_cookie
        if encrypted_token:
            existing_auth.encrypted_token = encrypted_token
        existing_auth.cookie_status = 0
        existing_auth.last_login_status_code = "COOKIE_UPDATED"
        existing_auth.last_login_status_message = "Cookie 已更新，等待统一登录校验"
        for extra in auth_rows[1:]:
            extra.deleted = 1
    else:
        db.add(
            XianyuAccountAuth(
                account_id=account.id,
                encrypted_cookie=encrypted_cookie,
                encrypted_token=encrypted_token,
                cookie_status=0,
                last_login_status_code="COOKIE_UPDATED",
                last_login_status_message="Cookie 已更新，等待统一登录校验",
            )
        )

    runtime_result = await db.execute(
        select(XianyuAccountRuntime)
        .where(XianyuAccountRuntime.account_id == account.id)
        .order_by(XianyuAccountRuntime.id.desc())
    )
    runtime_rows = runtime_result.scalars().all()
    if runtime_rows:
        existing_runtime = runtime_rows[0]
        existing_runtime.deleted = 0
        existing_runtime.cookie_status = 0
        existing_runtime.last_login_status_code = "COOKIE_UPDATED"
        existing_runtime.last_login_status_message = "Cookie 已更新，等待统一登录校验"
        for extra in runtime_rows[1:]:
            extra.deleted = 1
    else:
        db.add(
            XianyuAccountRuntime(
                account_id=account.id,
                cookie_status=0,
                last_login_status_code="COOKIE_UPDATED",
                last_login_status_message="Cookie 已更新，等待统一登录校验",
            )
        )
    return account


async def soft_delete_account(db, account_id: int) -> bool:
    """软删除账号及其 auth/runtime 状态，并停止对应 WS 客户端。

    返回 False 表示账号不存在或已删除；不负责 commit，由调用方统一提交。
    """
    result = await db.execute(
        select(XianyuAccount).where(
            XianyuAccount.id == account_id,
            XianyuAccount.deleted == 0,
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        return False

    # 停止可能正在运行的 WS 客户端
    try:
        from .ws_client import ws_manager
        await ws_manager.stop_client(account_id)
    except Exception:
        pass

    account.deleted = 1
    account.status = 0
    await db.execute(
        update(XianyuAccountAuth)
        .where(XianyuAccountAuth.account_id == account_id)
        .values(deleted=1)
    )
    await db.execute(
        update(XianyuAccountRuntime)
        .where(XianyuAccountRuntime.account_id == account_id)
        .values(deleted=1, online_status=0, ws_status=0)
    )
    return True
