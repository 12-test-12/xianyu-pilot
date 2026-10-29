# 闲鱼助手 · 个人桌面端改造

基于原项目已有的 Vue 后台和 Python 业务增量修改，保留账号、商品、消息、订单、自动发货、卡密及日志。AI 自动回复、QQ/MCP 按需使用。

产品方向为单用户本机运行、SQLite 存储，不使用 Docker。广告、付费投放、商业桥接和对应页面、配置已经移除。

## 当前进度

- 原有自动发货和卡密操作继续沿用原业务设计。
- CI 在 Linux/Windows 本机检查和构建，发布可校验的源码部署 ZIP。
- 新的 SQLite 入口已经支持数据目录、单实例、事务迁移和原核心模型表；尚未开放原业务接口和 Vue 页面，不会执行真实发货。
- 原服务端流程暂时仍依赖 MySQL/Redis，供未迁移的原业务开发使用。待相关业务适配完成后删除这些依赖。

SQLite 存储基础的安装、启动和后续顺序见 [桌面改造说明](docs/desktop-sqlite-foundation.md)。Windows 准备好 Python 依赖后运行 `start-desktop.bat`，默认状态入口为 `http://127.0.0.1:15177/health/ready`。

本地数据固定保存在程序根目录的 `data/` 下，数据库为 `data/app.sqlite3`，上传文件为 `data/uploads/`。移动程序时保留该文件夹即可；不使用 AppData 或自定义数据目录。

## 开发与发布

- [原本机开发流程](docs/local-dev-runbook.md)：`start-local.bat` / `start-local.sh`，适用于迁移中的原服务端。
- [本机源码部署包](docs/native-deployment.md)：包含原源码和本次验证的 Web/Crawler 构建，尚非 EXE 安装包。
- [流水线规则](docs/ci-pipeline.md)：检查、构建、安全审计和受限的版本发布。
- [自动发货增量改造](docs/auto-delivery-incremental.md)：原业务修改记录。

历史独立工作流演示保留在 `apps/desktop`，不作为此次桌面改造的业务实现，也不进入原系统发布包。相关历史文档保留供追溯。

项目包含上游开源代码；许可证和署名见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。
