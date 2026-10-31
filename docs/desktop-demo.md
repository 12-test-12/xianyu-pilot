# 历史本地演示已移除

2026-10-31：删除自建演示前端、`start-desktop-demo.bat`、对应 PowerShell 启动器及 `build:desktop` 构建入口。

使用原项目 Vue 后台：准备依赖并构建 `apps/web` 后运行 `start-desktop.bat`，或使用正式 Windows 便携包。参见 [完整控制台与 Windows Release](desktop-console-release.md)。

`apps/desktop` 剩余 Python 模块只用于历史离线回归，不属于正式桌面运行入口，不进入发布包。用户已有 `data/` 不做删除或改写。
