# CI/CD 流水线分析与改造说明

日期：2026-10-28（北京时间）。参考项目：[12-test-12/ai-goofish-monitor 的流水线](https://github.com/12-test-12/ai-goofish-monitor/blob/master/.github/workflows/docker-image.yml)。本次通过 GitHub 连接读取参考文件，核对的文件 blob 为 `dfba3bd433cc85888fe15fa2920ba3738d2f1484`。

本文说明当前仓库实际完成的流水线修改。它不表示 GitHub 远端任务已经执行，也不表示桌面版已经实现。本次不触发外部镜像发布或 Release。

## 1. 原流水线有什么问题

原 `.github/workflows/docker-publish.yml` 只有三个组件的镜像构建/发布矩阵：

```text
推送 main / 手动触发
  → api、web、crawler 各自构建
  → 直接推送 GHCR latest 和短 SHA
  → 可选从 latest 同步到 ACR
```

| 原有问题 | 影响 | 本次处理 |
| --- | --- | --- |
| 没有 PR 校验入口 | 合并前无法发现构建、测试和审计失败 | 增加 `pull_request` 检查 |
| 构建之前没有测试/审计门禁 | 问题代码仍可能发布 | 所有必需检查经统一 Quality gate 汇总 |
| workflow 默认具有 `packages: write` | 不需要发布的任务也请求写权限 | 默认只读，只有发布/标签推进任务申请包写权限 |
| GHCR 命名空间写死上游组织 | Fork 可能无权推送 | 默认使用当前仓库所有者，可显式配置命名空间 |
| `secrets` 直接出现在 step `if` 中 | 不符合 GitHub 的条件表达式使用限制 | 在独立步骤校验设置并输出非敏感 enabled 标志 |
| ACR 源是可变 `latest` | 并发时可能同步另一轮构建 | 记录 build-push 输出的精确 digest，并据此同步 |
| 每个组件立即覆盖 latest | 某个组件失败时，容易出现混合版本 | 三个组件均发布出 digest 后才进入标签推进 |
| ARM64 构建没有显式 QEMU 初始化 | 跨架构构建环境不明确 | 发布阶段显式配置 QEMU/Buildx |
| 没有统一报告和超时 | 排错证据不足，任务等待无界 | 各阶段设置超时并保存测试、审计、构建身份和 digest |

## 2. 从旧项目沿用哪些做法

参考项目的结构为“后端回归、前端构建、Windows 桌面、CodeQL、Gitleaks、Python 依赖审计 → Quality gate → 发布”。

本仓库沿用：

- 测试、构建、安全审计并行执行。
- 必需检查失败、取消或跳过均阻止发布。
- CodeQL 分析 Python、JavaScript/TypeScript 和 GitHub Actions；检查 SARIF，而不是仅上传报告。
- Gitleaks 扫描完整 Git 历史，报告脱敏，发现项阻断。
- 运行依赖审计与应用安装包分离。
- 保存构建产物和证据，PR 只检查、不登录发布仓库。
- PR 的旧运行可自动取消，发布任务不被自动取消。

没有复制：

- 参考项目的 EXE、`desktop.spec`、桌面依赖文件和 GUI 冒烟脚本。本仓库尚未实现对应入口。
- 参考项目自己的 Gitleaks 指纹豁免和 npm 漏洞例外。它们不适用于本仓库。
- 整套目录结构、镜像名、分支名或 Release 发布描述。

本仓库额外加入 workflow 语法检查、门禁回归、Windows 后端回归、三组件 Docker 预构建及 digest 完整性校验。

## 3. 改造后的流程

```text
main 推送 / main PR / v* 标签 / 手动运行
  ├─ workflow-checks：actionlint + 门禁/发布规则单元测试
  ├─ backend-tests：Linux、Windows 安装锁定依赖并运行现有后端回归
  ├─ frontend-build：Web 回归 + Vue 构建；Crawler TypeScript 构建
  ├─ npm-audit：Web、Crawler 的 high/critical 漏洞及审计错误
  ├─ python-audit：按带哈希运行锁文件严格审计
  ├─ code-audit：三种语言的 CodeQL，检查高风险结果/执行错误
  ├─ secrets-audit：Gitleaks 全历史扫描
  └─ docker-check：三个 amd64 镜像只构建，不推送
           ↓
      quality-gate：所有必需检查均成功
           ↓ 仅 main/版本标签的允许发布事件
      publish-images：按组件推送完整 SHA 标签，保存 digest
           ↓ 三组件均成功
      promote-images：核对来源、组件与 digest
           → main 更新 latest；版本标签更新对应版本
           → 配置完整时，按精确 digest 镜像到 ACR
```

后端现有测试覆盖范围有限。本次将其放进门禁，并不意味着已经验证真实闲鱼登录、MySQL 迁移、Redis 业务、真实 QQ 收发或桌面安装。Crawler 当前只有编译构建检查，没有虚构出不存在的业务测试。Docker 检查不是服务启动/订单闭环测试。

## 4. 触发与权限

| 事件 | 检查 | 发布 |
| --- | --- | --- |
| 向 main 提 PR，包括 Fork PR | 全部检查 | 不发布，不读取 ACR 凭据 |
| 推送 main | 全部检查 | 通过后发布 SHA 镜像；仍是当前 main 时推进 latest |
| 推送合法 `v` 版本标签，如 `v1.2.0` | 全部检查 | 通过后发布 SHA 与版本标签，不覆盖 latest |
| 手动运行，不勾选 publish_docker | 全部检查 | 不发布 |
| 手动运行并勾选 publish_docker | 全部检查 | 仅 main 或合法版本标签允许发布 |
| feature 分支手动运行 | 全部检查 | 即使勾选也不发布 |

`v*` 是触发条件，具体镜像版本还要通过脚本的标签格式验证。latest 推进前读取当前 main 的 SHA，过时构建保留 SHA 镜像但跳过推进，降低延迟任务覆盖新版本的风险。此检查不是对远端分支和镜像仓库的跨系统原子锁。

所有 PR 使用 `pull_request`，不使用可执行不可信 PR 代码的 `pull_request_target`。checkout 不持久化 Git 凭据。CodeQL 在 Fork PR 保留本地分析和门禁，但不要求将 SARIF 上传到代码扫描服务；报告仍作为 artifact 保存。

## 5. 仓库需要配置什么

### 5.1 GHCR

默认不需要额外的个人访问 Token，使用 Actions 的 `GITHUB_TOKEN` 和仓库包写权限。默认镜像为：

```text
ghcr.io/12-test-12/xianyu-assistant-api
ghcr.io/12-test-12/xianyu-assistant-web
ghcr.io/12-test-12/xianyu-assistant-crawler
```

可选 Repository Variable：`GHCR_IMAGE_NAMESPACE`。只有实际拥有该用户/组织包发布权限时才设置。已有同名 GHCR 包也需要允许此仓库的 Actions 访问，workflow 文件无法替代账号/包权限设置。

标签为 `sha-<完整40位提交>`、当前 main 的 `latest` 或 `v1.2.0` 等版本标签。真正用于同步和构建证据的身份是 `sha256:...` digest；SHA 标签在同提交重跑时仍可能更新，不将标签宣传为不可变存储。

### 5.2 可选 ACR

四项全部不配置时关闭 ACR。要启用必须同时配置：

| 类型 | 名称 | 内容 |
| --- | --- | --- |
| Variable | `ALIYUN_ACR_REGISTRY` | 纯主机名，例如 `registry.cn-hangzhou.aliyuncs.com` |
| Variable | `ALIYUN_ACR_NAMESPACE` | 有权限的镜像命名空间 |
| Secret | `ALIYUN_ACR_USERNAME` | 登录账号 |
| Secret | `ALIYUN_ACR_PASSWORD` | 登录凭据 |

只配置部分项目会明确失败，不能显示为“镜像成功但悄悄没同步”。同步使用 `ghcr.io/...@sha256:...`，不再从 latest 查找源。

三组件构建完成后才推进标签，但多个仓库/多个标签无法一起原子提交；远端同步中途失败仍可能部分推进。遇到这种失败应核对本轮 digest，修复连接/权限后恢复，不声称已经实现跨注册表的事务。

### 5.3 分支保护与部署地址

建议在 GitHub 规则集中将 `Quality gate` 设置为 main 的必需检查。此项属于仓库设置，本次没有修改远端规则。

Compose 的活跃默认镜像仍是原 ACR 地址，没有擅自切换用户现有部署。使用本 Fork 的新 GHCR 镜像时，应在部署 `.env` 显式填写：

```dotenv
API_IMAGE=ghcr.io/12-test-12/xianyu-assistant-api:latest
WEB_IMAGE=ghcr.io/12-test-12/xianyu-assistant-web:latest
CRAWLER_IMAGE=ghcr.io/12-test-12/xianyu-assistant-crawler:latest
```

生产部署需要固定版本时，可使用同一轮的版本标签或各组件 digest。本次同步更新了 `.env.example` 的 GHCR 注释示例。

## 6. 架构、版本与缓存

- Python：CI 使用 3.11，与 API Dockerfile 对齐。运行依赖按原哈希锁安装，测试/审计工具放根目录 `requirements-ci.txt`，不进入应用镜像。
- Node/npm：按当前两个 package.json 使用 Node 22.23.1、npm 10.9.8，避免 web 的 engine-strict 导致安装失败。
- npm 安装使用 `npm ci --ignore-scripts`，不随意改锁文件。
- 缓存按实际锁文件、组件隔离。Buildx 缓存写入失败不会伪装成镜像构建成功；只是允许缓存保存失败不影响已经完成的构建。
- Gitleaks 固定 8.24.2，与参考版本一致；actionlint 固定 1.7.12。下载后核对供应方对应资产校验和，只取指定可执行文件。
- API/Web 发布 amd64+arm64；Crawler 保留 amd64。不能据此宣称整套 Compose 已支持原生 ARM64。
- Web/Crawler dist artifact 带源提交信息；Dockerfile 仍从同一提交源码构建。它们不是已完成打包的 Windows 软件。

## 7. 文件与本地验证

| 文件 | 作用 |
| --- | --- |
| `.github/workflows/docker-publish.yml` | 检查、门禁、构建与发布流程 |
| `scripts/ci/gates.py` | 验证依赖 job 结果及 CodeQL SARIF |
| `scripts/ci/images.py` | 校验镜像身份、来源提交、组件完整性与 digest，同步发布标签 |
| `scripts/ci/install_tool.py` | 固定版本工具下载、校验与安全读取资产 |
| `tests/ci/test_gates.py`、`test_images.py` | 失败/取消/跳过、报告缺失、严重级别、缺组件、错来源和迟到发布测试 |
| `requirements-ci.txt` | 固定直接测试/审计工具版本 |
| `.github/dependabot.yml` | 增加 CI 工具依赖维护 |

不需要网络和应用依赖的门禁回归：

```powershell
Set-Location D:\xianyu-pilot
python -m unittest discover -s tests/ci -v
```

后端依赖安装完毕后，以明确的测试配置执行现有回归：

```powershell
$env:APP_ENV = 'test'
$env:PYTHONPATH = 'apps/api'
python -m pytest apps/api/tests -q
```

本地使用的解释器应与选定虚拟环境一致。不要用测试模式启动对真实账号执行任务的服务。完整检查还包括 actionlint、前端构建、锁文件审计、Gitleaks 和远端 CodeQL/Docker；以实际结果为准。

新加入的审计可能暴露旧代码或历史提交问题。不能为了得到绿色流水线而关闭审计、使用 continue-on-error 或复制其他项目的豁免。发现误报时核对原始证据后单独处理；发现真实凭据时先撤销/轮换，而不是只删文件。

### 7.1 本次依赖修复与本地验证结果

实际运行 npm 审计后，发现旧 Web 锁文件有 9 个 high 条目，Crawler 有 5 个 high 和 1 个 critical 条目。没有通过降低阈值处理，而是：

- Web：Axios `1.16.1 → 1.21.0`、Vite `8.0.16 → 8.3.5`、Vue `3.5.35 → 3.5.44`，保持原大版本。
- Crawler：Express `4.22.2 → 4.22.3`；移除没有对应测试文件、也没有源码引用的 Vitest 开发依赖，避免无用依赖链及其更新时的 npm peer 解析错误。
- 更新两份锁文件中的兼容修复版本，并用项目指定的 Node 22.23.1/npm 10.9.8 重新执行 `npm ci` 和构建。

| 本地检查 | 实际结果 |
| --- | --- |
| actionlint 1.7.12 | 通过；本机未安装 ShellCheck，另行禁用其外部调用，不代表已完成 ShellCheck 扫描 |
| 门禁/镜像规则回归 | 17 项通过 |
| 现有 Web 回归 | 2 项通过 |
| Web 构建 | 新锁文件重新安装后通过 |
| Crawler 构建 | 新锁文件重新安装后通过 |
| Web npm audit（high 阈值） | 通过：0 high/critical；剩余 1 moderate 的 ECharts 公告，修复涉及大版本升级，未在本次强制升级 |
| Crawler npm audit（high 阈值） | 通过：0 项告警 |
| Gitleaks 全历史扫描 | 仍阻断：3 条商业桥接 Token 记录待核验，未豁免 |
| 现有后端 pytest | 依赖下载速度过低，本次已停止下载，尚未执行完整回归；Python 源码编译检查通过，不将门禁自身测试计作后端回归 |
| Docker、CodeQL、GitHub 实际运行 | 未完成；本机 Docker 验证权限请求未获批准，远端 workflow 尚未触发 |

Gitleaks 最初检出 6 条，已核对其中两处是相同公开协议 app key，一处是发布意图的 sessionStorage 键。仅将这三条历史提交/文件/规则/行号的精确指纹加入本仓库新建的 `.gitleaksignore`，其他位置仍受检查。

剩余 3 条位于旧提交的 `apps/api/app/core/config.py` 和 `.trae/rules/opensource-commercial-bridge-sync.md`，属于商业桥接 Token 相关记录。没有向第三方接口发送这些值去测试有效性，没有在文档中复制凭据，也没有假定“已公开”或“已混淆”就等于可放行。需核对实际用途和撤销/轮换状态，再决定后续修复。单独删除当前文件不会清除历史记录。

因此，本次交付是可执行、会真实阻断风险的流水线配置，不是“所有远端检查已绿”的声明。工作流未加路径过滤，以免文档 PR 导致必需门禁永久等待；成本通过缓存、并行和任务超时控制。

## 8. 后续桌面流水线如何接入

等桌面宿主、SQLite 与凭据、冻结构建入口真实存在后，再增加：

1. Windows 桌面依赖锁与构建任务。
2. 使用同一提交构建的 Vue 资源，验证资源哈希和版本。
3. 打包后启动、受保护本机 API、退出/托盘、单实例和恢复冒烟。
4. 干净 Windows 的无全局开发环境安装验证。
5. 桌面任务加入 Quality gate，通过后才创建 Release 并上传安装包与校验文件。

这些任务当前仍是后续工作，本次流水线没有假装产生可用 EXE。
