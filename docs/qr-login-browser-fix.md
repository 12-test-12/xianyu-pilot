# 扫码登录浏览器修复记录（2026-11-04）

基于提交 `e44e3fc`，接续工作区已有的 Playwright 替换草稿完成修复。

## 定位

- 原桌面登录窗口只检测 `unb` 就回传 Cookie，不能证明登录票据完整。
- 登录窗口共享持久 profile，删除 Cookie 是异步操作，固定等待 400 毫秒无法保证旧状态已清空。
- 原账号页面自动生成的二维码仍走 requests 换票；新增内嵌窗口只是另一个入口，没有替换原链路。
- 替换草稿尚未更新带哈希的 requirements.txt，重新安装和打包不会获得 Playwright。

## 修复

参考 [ai-goofish-monitor 的 account_login_service](https://github.com/12-test-12/ai-goofish-monitor/blob/master/src/services/account_login_service.py) 的流程：独立线程内启动真实浏览器，每次使用新的上下文，截取官方二维码，在浏览器内执行确认和跳转。Chrome、Edge、自带 Chromium 依次尝试。

移除额外的桌面登录窗口与前端 Cookie 回传桥；桌面和服务端统一沿用扫码 API，凭据保存在后端。必须获得有效的闲鱼 `unb` 和 `cookie2`，回访首页后再次检查，仅导出闲鱼首页适用的 Cookie。取消会话后拒绝迟到的凭据写入；启动中的浏览器也占用会话容量；应用退出时取消登录会话。

生成二维码等待上限为 60 秒，前端请求超时为 65 秒。更新 Playwright 依赖锁及 PyInstaller 驱动收集配置；README 明确扫码需要 Chrome 或 Edge。

## 验证与边界

- 修改前的小范围基线：15 项通过。
- Chrome 直接访问官方页面：二维码成功生成。
- 实际 Python QrLoginWorker：生成 PNG 二维码，取消后线程退出，状态为 cancelled。
- 后端全套回归：433 项通过；新增并发等修改后补跑专项检查。
- 扫码及 CI 打包规则检查：72 项通过、1 项跳过、42 项 subtests 通过。
- 前端生产构建通过。修改文件 ESLint 无错误；账号页存在 8 条既有警告，因此严格零警告检查未通过。
- 本机直接运行 Python 时系统临时目录权限异常；使用工作区临时目录验证通过。便携版已有 prepare_portable_runtime 将临时目录迁到 data/tmp，本次保留该实现。

未执行手机扫码确认、真实账号落库或重新构建 EXE。需要在实际账号上验收新增账号、失效账号重新扫码、取消后重新生成，以及退出后无残留浏览器进程。
