# 原项目完整控制台与 Windows Release

更新日期：2026-10-31。

## 客户端入口

桌面窗口固定打开本机根路由 `/`，后端从已构建的 `apps/web/dist/index.html` 提供原 Vue 3 应用。继续使用 `App.vue`、原导航、原页面及原 CSS。历史演示前端和临时 `/desktop/safety` 工作台已删除，旧工作台地址返回 404。

闲鱼账号、商品、订单、消息、自动发货、卡密仓库、自动回复、AI 设置、日志与定时任务等模块继续使用原业务路由。桌面启动不加载服务端 MySQL 迁移器，也不要求另行安装 MySQL 或 Redis。

- 新增追加迁移 `006_full_console.sql`，补齐原业务表、原唯一索引和原 SQL 兼容字段；不修改已经应用的 001–005 迁移。
- SQLite 会话适配原业务 SQL 的 upsert、日期、聚合和写锁语义；读写仍落在同一个 `data/app.sqlite3`，不返回模拟业务数据。
- 原 Vue 入口仅在桌面宿主注入启动凭证时交换本机管理会话。普通服务端页面保留原登录流程。跨站来源被拒绝，会话不写入 Release 包。
- 完整提供 `/assets`、`/xya` 和 `/uploads`，保持原 `/api` 合约及 SSE 单次票据机制；Uvicorn 保留 WebSocket 协议支持。
- 订单和发货记录使用原完整查询，保留筛选、买家、商品明细及执行状态；旧桌面诊断读接口位于 `/api/desktop/orders` 和 `/api/desktop/auto-delivery/records`，不覆盖主控制台接口。
- 原消息/AI 工作器、凭据刷新、评价与上架服务随桌面生命周期启动和停止。托盘暂停闸门也用于原自动发货网关。
- 原生文件选择可用于导入，下载写入程序旁 `data/tmp/downloads`；API、脚本和导航仅连接自己的本机服务，原商品、头像和消息图片允许被动加载 HTTPS 图片。
- 桌面加密使用每个安装独立的 `data/profiles/credentials.key`，不复用服务端默认开发密钥。备份和移动时必须保留完整 `data/`。

首次启动没有账号。通过原后台添加并授权闲鱼账号后，再配置商品、库存、模型与自动化规则。真实平台登录、发送、外部 AI 服务和异常履约仍需使用授权账号实际联调，离线回归不能替代。

## 两种 Windows 下载

1. `XianyuPilot.exe`：独立单文件 EXE，可直接运行；运行组件由 PyInstaller 临时展开，业务数据仍固定在 EXE 旁的 `data/`。
2. `XianyuPilot-Windows-x64.zip`：完整目录式包，解压整个 `XianyuPilot/` 后运行其中的 EXE。此包内的 EXE 必须与 `_internal/` 一起保留。

日常使用优先选择完整目录 ZIP：避免单文件 EXE 每次启动时临时展开 Python、Qt 和 Chromium。此次启动并行初始化、缓存与刷新优化见 [桌面性能与界面清理](desktop-performance.md)。

两种形式均内置 Python、Qt/Chromium 和原前端，不要求用户安装 Python、Node.js 或系统浏览器。升级、备份和移动前从托盘彻底退出，并保留原 `data/`。

## Release 触发

发布流程参考 [ai-goofish-monitor 的 publish-desktop 作业](https://github.com/12-test-12/ai-goofish-monitor/blob/master/.github/workflows/docker-image.yml)。

| 触发 | 构建与审计 | Release |
| --- | --- | --- |
| 推送 main | 全部执行 | 成功后发布 `desktop-运行编号-尝试编号` |
| 推送 v* 版本标签 | 全部执行 | 合法版本格式通过后发布对应版本 |
| 手动运行 | 全部执行 | 默认勾选发布；允许选择包含修复的开发分支 |
| 开发分支普通推送或 PR | 全部执行 | 不自动发布 |

发布作业具有 `contents: write`，使用 `gh release create ... --latest`，不带 `--draft`、`--prerelease` 或 `--latest=false`。版本标签发布前重新核对提交；重跑不覆盖既有 Release 或附件。

每个 Release 包含独立 EXE、完整目录 ZIP、源码 ZIP、覆盖三个下载文件的 `SHA256SUMS.txt` 和 `windows-build-info.json`。发布前校验源码提交、EXE 哈希、ZIP 内每个文件和必需运行组件，缺少独立 EXE 时不会只发布源码。

手动发布：GitHub → Actions → CI and Native Release → Run workflow → 选择包含修复的分支 → 保持发布选项开启。构建、审计和两种 EXE 检查全部成功后，Releases 页面才会生成最新正式下载。

## 验证

- `test_desktop_console.py` 使用真实 SQLite 验证原 API 的数据读取、配置保存、日期统计、会话聚合、本机授权与 SSE 票据。
- 原前端构建与 Node 测试继续运行；本地浏览器逐项验证原主要页面。
- GitHub Qt 检查必须看到原 `.app-shell` 和完整导航，并实际请求账号、商品、订单、库存、货源、设置等接口，再建立 SSE 连接。只出现安全工作台无法通过。
- 目录包和独立 EXE 分别从移除开发 PATH 的环境启动，检查外部 cwd、中文路径搬移、数据库标识和原 Web 控制台渲染。

2026-10-31 本地已安装固定版本 Qt/PyInstaller，并构建含新图标和退出修复的目录版、独立 EXE 与便携 ZIP。两种冻结版本已通过外部 cwd、移除开发 PATH、中文路径搬移、数据库身份保留和内嵌原控制台加载/退出检查；原生 Qt 回归通过。真实账号与订单、真实托盘交互、干净 VM、跨盘、物理断电和完整 I/O 隔离仍需实测。公开下载以 GitHub Releases 实际附件为准，本地构建与本地提交不表示远端已发布。
