# Gemini 应用图标接入

日期：2026-10-31。

采用用户选定、已在提交 `a530d83` 中保存的「黑曜石极光」蓝色小鱼设计，不重新绘制或改动图案。

- PNG 母版：`apps/web/public/xya/brand/app-icon.png`。
- Windows 图标：`apps/web/public/favicon.ico`，包含 16、24、32、48、64、128、256 像素尺寸。
- `app-icon.svg` 是嵌入 PNG 的 SVG 容器，不是真正的矢量重绘。
- 侧栏去除旧的蓝色 X 字标，改为同一图标配「闲鱼助手 / Xianyu Pilot」文字；启动画面、登录页与移动端标题栏继续共用 PNG。
- 原生窗口、任务栏与托盘共用 ICO；托盘额外保留运行状态点。
- `packaging/windows/xianyu_portable.spec` 的目录包和单文件 EXE 均直接从仓库中的 `apps/web/public/favicon.ico` 嵌入 Windows PE 图标资源。Windows 资源管理器读取的是 EXE 本身，下载后不需要启动软件或另外设置快捷方式图标。

重新生成图标运行 `python scripts/generate-app-icon.py`；随后在 `apps/web` 构建前端，再进行 Windows 打包。

## GitHub 下载包的图标保证

1. Windows 构建下载同次 Actions 的 Web 产物，先核对 `dist/favicon.ico` 与源码图标完全相同；前端使用旧图标就停止打包。
2. 构建脚本使用 PyInstaller `--clean`，为两个 EXE 嵌入同一源码图标。构建完成后读取 `RT_GROUP_ICON` / `RT_ICON` 资源，逐个比较 16、24、32、48、64、128、256px 的尺寸、元数据和完整图像字节。默认图标及其他图标组、语言版本都必须匹配，不能仅存在一个匹配的备用图标。
3. 生成 Release 附件后，重新检查 `release/windows/XianyuPilot.exe` 和 `XianyuPilot-Windows-x64.zip` 内的主 EXE，以及 ZIP 内的窗口图标。校验成功才上传 Actions 产物。
4. Linux 发布作业下载同次运行的附件，校验提交归属、全包校验和，再独立检查两个 EXE 的图标资源，通过后才创建 GitHub Release。缺图标、默认 Python 图标、旧图标或不完整尺寸均阻断发布，即使文件校验和正确也不能通过。

发布的 Windows 附件是独立 `XianyuPilot.exe` 和完整目录 `XianyuPilot-Windows-x64.zip`。目录包中的 EXE 必须与 `_internal/` 一起保留。更改源码并完成本地提交后，需要推送并等待 GitHub 全部作业通过，才能产生带这些检查的新 Release；已有 Release 附件不会自动改变。

## 校验与证据

校验器为 `scripts/ci/windows_icon.py`，使用固定版本 `pefile`，可在 Windows/Linux 读取 PE 资源，无需运行 EXE。构建依赖位于 `packaging/windows/requirements-build.txt`，发布校验依赖位于 `packaging/windows/requirements-icon-check.txt`。

```sh
python -m pip install -r packaging/windows/requirements-icon-check.txt
python -m unittest discover -s tests/ci -v
python scripts/ci/windows_icon.py --release-directory release/windows --report reports/windows-icon-release.json
```

Actions 的 `windows-portable-validation` 保存打包前、构建后、附件打包后的图标报告；`windows-release-icon-verification` 保存发布作业对下载附件的复核报告。报告包含源码 ICO 的 SHA256、受检 EXE 的 SHA256、图标组数量和七种尺寸。

本地回归覆盖有效 PE 资源、语言版本、错误默认图标、错误图像、缺少尺寸、旧前端资源、ZIP 内旧 EXE，以及“校验和有效但 EXE 图标错误”时禁止发布。现有真实目录 EXE、单文件 EXE 与完整交付 ZIP 也通过同一校验器；这不代替新提交在远端的完整流水线执行。

本地打包时应隔离 PATH，避免第三方工具（例如 Poppler）目录中的同名 ICU DLL 被误收集并干扰 Qt。
