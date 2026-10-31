# Gemini 应用图标接入

日期：2026-10-31。

采用用户选定、已在提交 `a530d83` 中保存的「黑曜石极光」蓝色小鱼设计，不重新绘制或改动图案。

- PNG 母版：`apps/web/public/xya/brand/app-icon.png`。
- Windows 图标：`apps/web/public/favicon.ico`，包含 16、24、32、48、64、128、256 像素尺寸。
- `app-icon.svg` 是嵌入 PNG 的 SVG 容器，不是真正的矢量重绘。
- 侧栏去除旧的蓝色 X 字标，改为同一图标配「闲鱼助手 / Xianyu Pilot」文字；启动画面、登录页与移动端标题栏继续共用 PNG。
- 原生窗口、任务栏与托盘共用 ICO；托盘额外保留运行状态点。
- `packaging/windows/xianyu_portable.spec` 的目录包和单文件 EXE 均从已构建的 `web/favicon.ico` 嵌入图标。

重新生成图标运行 `python scripts/generate-app-icon.py`；随后在 `apps/web` 构建前端，再进行 Windows 打包。

本地最终构建目录为 `dist/gemini-icon-final/`，交付目录为 `dist/gemini-icon-release/`。目录包中的 `XianyuPilot.exe` 必须与同目录 `_internal/` 一起保留；单文件为 `XianyuPilot-Standalone.exe`。交付时提供完整目录 ZIP 与独立 `XianyuPilot.exe`。原安装目录与用户 `data/` 不做自动覆盖或删除。

本地打包时隔离 PATH，避免第三方工具（例如 Poppler）目录中的同名 ICU DLL 被误收集并干扰 Qt。图标按七种尺寸逐像素核对 EXE 资源；启动验证在独立测试副本中执行，不包含真实账号或用户数据。
