# easy-miloco

本仓库 fork 自 Xiaomi Miloco 官方仓库，核心功能随官方异步更新。本仓库主要做三件事：

1. 提供一键部署包。跟随官方更新，计划适配 Windows、macOS、NAS 和主流云服务器。截至 2026 年 6 月 29 日，Windows 和 macOS 均已有一键部署路线。
2. 提供小白友好的教程。帮助小白解决miloco在安装和使用过程中遇到的各类故障问题。

## 一键部署

[视频教程](https://www.bilibili.com/video/BV1JaTc6dEaW/)

### Agent 全自动

省心，适合不想自己处理 WSL、依赖、日志的人；缺点是会慢一点，也会多消耗一些 Token。

把下面这句话丢给 Agent，让 Agent 全程代劳：

```text
请为我一键部署 Miloco，按照：https://raw.githubusercontent.com/andy-JustSayWhen/easy-miloco/main/docs/install-guide.md
```

Agent 只需要先读上面这个总入口；进入后会按当前系统自动路由到 Windows 或 macOS 子指南。

### 用户自己动

速度最快，适合能按提示处理权限、WSL、网络问题的人。

打开 [GitHub Release](https://github.com/andy-JustSayWhen/easy-miloco/releases)，根据系统类型，下载对应的 `.zip` 一键部署包。下载后解压：

- Windows：双击文件夹根目录内的 `install.bat`。
- macOS：双击文件夹根目录内的 `install.command`。

期间遇到任何问题，请把这句话发给你的agent：

```text
请你在 install.ps1 所在目录查找并读取最新的 miloco-install-console-*.txt、miloco-install-inputs-*.txt、miloco-deploy-report-*.txt，根据这些日志和诊断报告定位并解决问题；如果日志里提示 WSL 内详细日志，再按提示继续读取对应的 /tmp/*.log 或 ~/.openclaw/miloco/log/miloco-backend.log。
```

#### 下载加速

如遇 GitHub 下载缓慢，可尝试以下方式：

1. **配置 GitHub 加速代理**

   - 可选网站：[gh-proxy.com](https://gh-proxy.com/) 或 [gitwarp.com](https://www.gitwarp.com/)
   - 使用方法：打开上述任一网站，按页面提示操作（也可自行搜索或问 AI）
2. **从网盘下载**

   - [夸克网盘备份](https://pan.quark.cn/s/5d839d2f3b0f)
   - 网盘可能滞后于GitHub Release，可以[提醒作者](https://space.bilibili.com/383423248)及时更新。

## 环境依赖

下载 release 包后，用户可能遇到以下依赖或系统能力要求：

| 依赖                    | 是否需要 | 原因                                                                                                                                               |
| ----------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 操作系统                | 必须     | Windows 建议 Windows 11 22H2+；macOS 建议 macOS 12+；低于建议版本不保证完整兼容。Linux/NAS 先走官方脚本和 runbook 路线                      |
| 兼容 Ubuntu WSL2        | Windows 必须 | Miloco 当前不作为 Windows 原生后端运行；Windows 安装器会复用已存在且通过能力检测的 Ubuntu WSL2，只有没有可用 Ubuntu 时才默认安装 Ubuntu-24.04。macOS 不使用 WSL |
| Linux 基础能力          | Windows/NAS 必须 | Windows 侧需要 WSL version 2、glibc >= 2.28、CPU 架构 x86_64/aarch64，并能运行 bash、curl、systemd user 相关命令；macOS 直接使用 darwin runtime |
| 管理员权限              | Windows 首次安装可能需要 | Windows 首次安装可能需要启用 WSL、VirtualMachinePlatform、Hyper-V 防火墙入站规则；macOS 通常不需要管理员权限 |
| 网络访问 GitHub Release | 必须     | 官方版本基准和更新包以 GitHub Release 为准                                                                                                         |
| 夸克网盘                | 可选     | 中国大陆用户 GitHub 下载慢时使用副本                                                                                                               |
| 小米账号                | 必须     | 用于绑定米家设备、读取家庭和设备列表                                                                                                               |
| LLM API Key / Base URL  | 必须     | 用于 Miloco 视觉/多模态感知推理。Base URL 需要是 OpenAI 兼容格式，通常以`/v1` 结尾                                                               |
| 米家摄像头              | 必须     | 用于让 Miloco 获取家中画面并做视觉理解；摄像头需已绑定米家 App，且在米家 App 里能正常打开画面。支持型号见`docs/cameras.md`                       |
| OpenClaw                | 必须     | Miloco 以 OpenClaw 插件/技能形式接入 Agent 对话和自动化                                                                                            |
| Python / Node / uv      | 可选     | 用户无需预装，一键包会自动准备；如果自动安装失败，诊断报告会指出失败层                                                                             |

兼容声明：

当前 Windows 一键包只对 Windows 11 22H2 及以上版本提供完整部署保证；macOS 一键包优先支持 arm64/x86_64 的 macOS 12+。低于建议版本可能能跑基础服务，但摄像头实时流、系统服务、OpenClaw/Miloco 联动都不保证稳定。

## 项目说明

### 目录树

仓库目录树：

```text
.
├── .ci/                  # CI 辅助脚本、依赖守卫和 OpenGrep 规则
├── .github/              # GitHub Actions、CodeQL 和仓库自动化配置
├── assets/               # README / 文档图片素材
├── backend/              # Miloco 后端
├── cli/                  # miloco-cli
├── docs/                 # 部署、排障、发版和 Windows 一键包文档
├── knowledge/            # 架构、功能、设计和研发知识库
├── macos/                # 本 fork 新增：macOS 懒人包源码、打包和双击入口模板
├── nas/                  # 本 fork 新增：NAS Docker/Compose 部署适配
├── plugins/              # OpenClaw 插件和 skills
├── scripts/              # 官方安装/构建脚本
├── web/                  # Miloco WebUI
├── windows/              # 本 fork 新增：一键部署包源码、打包、更新、回滚
├── .gitattributes        # Git 换行规则；确保 shell 脚本保持 LF
├── .gitignore
├── AGENTS.md
├── LICENSE.md
└── README.md
```

Release 包目录树示例：

```text
easy-miloco-v0.5-windows/
├── README.md
├── install.bat
├── install.ps1
├── manifest.json
├── release-notes.md
├── scripts/
│   └── windows/
├── docs/
└── payload/
    ├── install.sh
    └── miloco-linux-x86_64-*.tar.gz
```

## 差异对比

本节从用户Features视角，对比官方仓库和本仓库的差异。

| 功能                              | 官方仓库 | 当前仓库 | 差异点                                                                                                                                    |
| --------------------------------- | -------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 通用常识危险识别                  | ☑️     | ☑️     | 核心感知与 Agent 规则链路沿用官方：摄像头输入进入感知流水线，DYNAMIC 规则经 OpenClaw Agent 执行。                                         |
| 身份识别                          | ☑️     | ☑️     | 沿用官方`person`、identity engine、tier_a/tier_c 样本库；当前仓库补充启动时 tier_a ReID embedding 幂等 backfill。                       |
| 家庭记忆                          | ☑️     | ☑️     | 沿用官方 home profile 注入；当前仓库补充跨平台文件锁兜底，减少 Windows/WSL 场景对 Unix-only`fcntl` 的依赖。                             |
| 家庭任务                          | ☑️     | ☑️     | 沿用官方`task` + `task_record` + OpenClaw cron/skill 编排；当前仓库保留 task 终止审计和跨日 rollover 兜底。                           |
| 主动智能                          | ☑️     | ☑️     | 核心仍是感知事件/规则/任务投递到 OpenClaw；当前仓库增强 dispatcher 与观测数据，便于排查主动推送。                                         |
| 家庭面板                          | ☑️     | ☑️     | 官方提供 Web dashboard；当前仓库把构建产物纳入后端 static 托管，并新增性能报告入口。                                                      |
| 米家设备查询与控制                | ☑️     | ☑️     | 官方通过`miloco-devices` skill、CLI 和后端 MIoT service；当前仓库保持 Cloud/LAN 双路径与 scope 校验。                                   |
| 小米账号绑定                      | ☑️     | ☑️     | 官方 CLI/面板绑定；当前仓库增加 Windows 部署脚本里的 OAuth 引导与后授权收尾 runbook。                                                     |
| 模型配置与用量查看                | ☑️     | ☑️     | 官方面板模型页和 admin cost；当前仓库新增运行级性能报告，与 token/trace 观测分开。                                                        |
| 摄像头感知开关                    | ☑️     | ☑️     | 官方通过 camera scope 启用指定摄像头；当前仓库修正 cloud/lan/connected 三类在线证据，减少假离线。                                         |
| 实时摄像头观看                    | ☑️     | ☑️     | 官方 WebSocket + jMuxer；当前仓库增加最后订阅者断开后的延迟 teardown，避免刷新面板导致频繁冷启动。                                        |
| 按需视觉感知                      | ☑️     | ☑️     | 官方依赖当前 active source；当前仓库在 OpenClaw 请求时刷新摄像头元数据并短等目标源/缓冲，降低首次请求失败。                               |
| 摄像头音频参与感知                | ☑️     | ❌       | 官方以视频与声音为全模态入口；当前仓库默认不订阅摄像头音频解码流，优先保证视频感知稳定，避免部分设备音频流拖垮后端。                      |
| OpenClaw 插件                     | ☑️     | ☑️     | 官方注册 service、hooks、webhooks、tools；当前仓库保持同样插件面，并补充大量部署/排障文档。                                               |
| `miloco-devices` skill          | ☑️     | ☑️     | 两边均支持设备查询、属性读取、控制和场景触发。                                                                                            |
| `miloco-perception` skill       | ☑️     | ☑️     | 两边均支持视觉感知；当前仓库在摄像头冷启动、LAN hint 和首帧等待上更保守。                                                                 |
| `miloco-miot-identity` skill    | ☑️     | ☑️     | 两边均支持成员/宠物身份管理；当前仓库保留与家庭档案联动清理。                                                                             |
| `miloco-miot-admin` skill       | ☑️     | ☑️     | 两边均支持系统状态和用量查询；当前仓库另加性能报告 API 与 Web 页面。                                                                      |
| `miloco-create-task` skill      | ☑️     | ☑️     | 两边均支持任务创建、列表、日志、启停和更新。                                                                                              |
| `miloco-terminate-task` skill   | ☑️     | ☑️     | 两边均支持终止任务；当前仓库强调审计快照、级联清理和 cron pending 清理。                                                                  |
| `miloco-notify` skill           | ☑️     | ☑️     | 两边均支持感知异常分级和通知；当前仓库文档补充通知渠道排障路径。                                                                          |
| `miloco-cli` 服务/设备/配置管理 | ☑️     | ☑️     | 官方 CLI 提供 service、account、config、device、scope 等命令；当前仓库保留并补充 Windows/WSL 验收脚本。                                   |
| macOS/Linux 安装                  | ☑️     | ☑️     | 官方主线是`install.sh`；当前仓库保留源码和脚本路线，并新增 macOS 一键 zip 与 Agent 部署子指南。                                           |
| Windows WSL 安装                  | ☑️     | ☑️     | 官方说明 Windows 需 WSL；当前仓库增加 Windows 一键包、预检、安装、后授权、验收和故障矩阵。                                                |
| Windows 原生后端                  | ❌       | ❌       | 两边都不支持 Windows 原生后端；当前仓库明确用 WSL2 承载 Linux 后端。                                                                      |
| 一键部署 zip 包                   | ❌       | ☑️     | 当前仓库新增 Windows/macOS release 包，用户解压后分别双击根目录 `install.bat` / `install.command` 即可开始安装。                         |
| 桌面控制台菜单                    | ❌       | ☑️     | 当前仓库生成 Windows `Miloco 控制台.bat` 和 macOS `miloco控制台.command`，提供重启 OpenClaw、重启 Miloco、整套重启、关闭服务、查看日志等入口。 |
| Windows 诊断/验收脚本             | ❌       | ☑️     | 当前仓库新增`docs/scripts/*` 和 `windows-preflight`/`wsl-miloco-validate`/`win-miloco-workflow`，区分 BASIC_READY 与 FULL_READY。 |
| 国内下载副本                      | ❌       | ☑️     | GitHub Release 是版本基准；GitHub 慢时可用夸克网盘副本下载。                                                                              |
| 教程、FAQ、runbook                | ❌       | ☑️     | 当前仓库新增`docs/`，覆盖一键部署、Windows、摄像头、SSH 命令传输、NAS 安装、性能报告等复用经验。                                        |
| 性能报告 WebUI                    | ❌       | ☑️     | 当前仓库新增`performance_report.py`、`performance_report_router.py` 和 `PerformanceReportsPage.tsx`，展示每次后端运行报告。         |
| Agent 可读备份恢复包              | ❌       | ☑️     | 当前仓库新增`backup_export.py`、`BackupPage.tsx` 和 `/admin/backup/export`，导出家庭档案、成员、任务、模型配置的逻辑恢复 zip。      |
| 摄像头 Wi-Fi/首帧排障规则         | ❌       | ☑️     | 当前仓库把 Game/5G Wi-Fi、坏 LAN override、无首帧 cooldown、误删 OAuth 等实战规则沉淀到`docs/windows/camera-runbook.md`。               |

## 其他

本仓库遵循以下原则：

- GitHub Release 是唯一版本基准。
- Release 包是构建产物，不手工修改。
- 用户问题优先通过诊断报告定位，不盲目重装。
- 更新前只备份本项目相关状态，不默认导出整个 WSL。
- 失败经验和成功经验必须沉淀到 `docs/faq/known-issues.md` 或对应 runbook。
- 当前优先保证 Windows 11 22H2+ 和 macOS 12+ 的一键部署；NAS、云服务器等路线后续再展开。
