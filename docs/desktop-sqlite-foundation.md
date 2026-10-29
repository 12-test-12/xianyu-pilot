# 个人桌面端改造：存储基础

改造基于原项目的 Python 后端、SQLAlchemy 模型和 Vue 页面，继续沿用账号、商品、订单、卡密和发货流程。广告、付费投放、反馈工单和商业版桥接已删除；AI、QQ/MCP 仍按需保留。本分支不使用 Docker。

## 当前可验证的内容

- `app.main` 根据显式运行模式选择启动流程。桌面流程不加载原服务端启动器，不连接 MySQL/Redis，不启动平台连接、定时任务或自动发货。
- SQLite 文件为 `%LOCALAPPDATA%\XianyuPilot\app.sqlite3`（Windows）。其他系统使用用户本地数据目录；支持 `--data-dir` 指定本机目录。与历史工作流演示的数据库分开。
- 首次启动初始化原模型对应的账号、授权、运行状态、商品、订单、订单明细、发货规则、卡密组、卡密和发货记录表。主键在 SQLite 使用 `INTEGER`，保留原 MySQL 类型。
- 迁移按版本和 SHA256 记录，事务执行。拒绝覆盖其他应用的数据库、篡改过的迁移和更新版本的数据库；同一数据目录只允许一个实例。
- 数据库连接启用外键检查和 5 秒锁等待。尚未引入并行写入或后台发送任务。

**这是存储基础，不是完整桌面产品。** 桌面入口的 `/` 返回状态 JSON，尚未挂载原 Vue 页面和业务接口。未适配的 `/api/*` 请求返回 HTTP 503，避免将未执行的操作显示为成功。完整业务仍处于原本机服务端流程，暂时保留其 MySQL/Redis 代码，待对应模块完成 SQLite 适配后删除。

## 启动验证

使用 Python 3.11，在项目根目录准备环境：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r apps/api/requirements.txt
.\start-desktop.bat
```

Linux/macOS 的安装解释器使用 `.venv/bin/python`，启动使用 `sh ./start-desktop.sh`。

启动参数示例：

```powershell
.\start-desktop.bat --data-dir D:\XianyuPilotData --port 15181
```

默认访问 `http://127.0.0.1:15177/health/ready` 查看数据库和迁移状态，`/api/desktop/status` 查看适配阶段。服务只绑定回环地址，拒绝外站 Origin。终端按 Ctrl+C 退出。不会自动打开浏览器或发送消息。

桌面流程不读取服务端 `.env`、服务端密钥文件或 MySQL/Redis 环境配置。此阶段只开放存储状态；AI、平台和其他配置将在相关原业务适配时接入。

## 下一步实施顺序

1. 优先适配原卡密仓库和发货规则的读写接口：去除 MySQL 专用 SQL，验证导入、去重、事务和库存状态。
2. 接入原订单与发货记录，落地同一 SQLite 事务中的库存占用和订单幂等控制；断电或重启后能判断待处理、成功和结果未知。
3. 将原账号、消息和平台连接改为本地流程，替换 Redis 在单用户模式下的会话、锁和调度用途，再删除剩余服务端依赖。
4. 挂载原 Vue 页面并做本机完整链路回归，最后再制作桌面窗口、安装包和更新机制。

升级前停止程序并备份整个数据目录。新增迁移文件，不修改已发布迁移。当前不会导入旧演示数据或自动迁移 MySQL 数据。
