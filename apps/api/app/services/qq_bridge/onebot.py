"""Loopback OneBot 11 HTTP transport shared by the desktop applications."""
import http.client
import json
import re
from urllib.parse import urlsplit


QQ_ID_PATTERN = r"^[1-9][0-9]{0,19}$"


class ConnectorError(ValueError):
    pass


def validate_endpoint(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ConnectorError("QQ 接入地址或端口无效") from exc
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.path not in {"", "/"}
            or not port or not 1024 <= port <= 65535 or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise ConnectorError("QQ 接入地址必须是 http://127.0.0.1:端口")
    return port


class OneBotClient:
    ALLOWED = {"get_login_info", "get_friend_list", "get_status", "send_private_msg"}

    def __init__(self, endpoint, token):
        self.port = validate_endpoint(endpoint)
        if not re.fullmatch(r"[!-~]{1,512}", token):
            raise ConnectorError("请填写有效的 OneBot Access Token")
        self.token = token

    def call(self, action, params):
        if action not in self.ALLOWED:
            raise ConnectorError("未开放此 QQ 操作")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            connection.request("POST", "/" + action, body=json.dumps(params).encode(), headers={
                "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if response.status in (401, 403):
                raise ConnectorError("OneBot 拒绝访问，请核对 Access Token")
            if response.status != 200 or len(raw) > 1024 * 1024:
                raise ConnectorError("OneBot 接口响应异常，请核对 HTTP 服务地址和端口")
            result = json.loads(raw)
            if not isinstance(result, dict) or "data" not in result:
                raise ConnectorError("QQ 接入响应格式无效")
            if result.get("status") != "ok" or result.get("retcode") != 0:
                raise ConnectorError("QQ 接入未确认操作成功，请检查 QQ 登录状态")
            return result["data"]
        except (OSError, ValueError, http.client.HTTPException, RecursionError) as exc:
            if isinstance(exc, ConnectorError):
                raise
            raise ConnectorError("本机 OneBot 连接失败，请检查 HTTP 服务和端口") from exc
        finally:
            connection.close()

    def identity(self, expected):
        result = self.call("get_login_info", {})
        if not isinstance(result, dict) or str(result.get("user_id")) != expected:
            raise ConnectorError("QQ 当前登录账号与登记账号不一致")

    def friends(self, expected):
        self.identity(expected)
        result = self.call("get_friend_list", {})
        if not isinstance(result, list):
            raise ConnectorError("QQ 好友目录响应格式无效")
        return [{"conversation_id": f"{expected}:direct:{item['user_id']}",
                 "name": str(item.get("remark") or item.get("nickname") or item["user_id"])[:80]}
                for item in result if isinstance(item, dict) and re.fullmatch(QQ_ID_PATTERN, str(item.get("user_id", "")))]
