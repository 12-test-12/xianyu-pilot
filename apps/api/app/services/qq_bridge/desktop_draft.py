"""Prepare drafts in the signed-in Windows QQ client."""
from base64 import b64encode
import json
import os
from pathlib import Path
import subprocess

from app.services.desktop_inventory import InventoryError


SCRIPT = Path(__file__).resolve().parents[2] / "resources" / "qq_draft.ps1"
MESSAGES = {
    "qq_closed": "请先打开并登录电脑 QQ，再试一次。",
    "qq_unavailable": "没能切换到 QQ 主窗口。请打开电脑 QQ 主窗口后重试。",
    "contact_not_found": "QQ 中没找到可确认的机器人好友，请核对 QQ 号和 QQ 中显示的备注或昵称。",
    "chat_not_verified": "没能核对聊天对象或输入框。可复制指令后在 QQ 私聊粘贴。",
    "draft_exists": "这个 QQ 聊天已有草稿。请先处理原草稿，再试一次。",
}


def open_qq_draft(target, command):
    if os.name != "nt":
        raise InventoryError("直接填入草稿目前支持 Windows 电脑 QQ。可复制指令后手动粘贴。", 409)
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        script = b64encode(SCRIPT.read_text(encoding="ascii").encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Sta", "-EncodedCommand", script],
            input=json.dumps({**target, "command": command}, ensure_ascii=True).encode("ascii"),
            capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InventoryError("无法确认 QQ 草稿是否已填入。请先查看 QQ 输入框。", 503) from exc
    state = result.stdout.decode("ascii", errors="replace").strip()
    if result.returncode == 0 and state == "draft_ready":
        return {"state": state}
    if state in MESSAGES:
        raise InventoryError(MESSAGES[state], 409)
    raise InventoryError("无法确认 QQ 草稿是否已填入。请先查看 QQ 输入框。", 503)
