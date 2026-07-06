# easy-miloco Docs

公开仓库只保留可复用、可发布、可审计的文档。实机日志、用户环境记录、授权过程、截图证据、长验证记录和个人记忆不得放入 `docs/`。

## 用户入口

- 一键部署总入口：[install-guide.md](install-guide.md)
- Windows：[windows/index.md](windows/index.md)
- macOS：[macos/index.md](macos/index.md)
- NAS：[nas/index.md](nas/index.md)
- NAS Docker：[nas/docker-deploy.md](nas/docker-deploy.md)
- 低配 NAS 性能优化状态：[nas/low-config-performance-current-status.md](nas/low-config-performance-current-status.md)
- 摄像头：[fix-camera/index.md](fix-camera/index.md)
- Miloco 资源占用：[miloco资源占用分析报告.md](miloco资源占用分析报告.md)
- 常见问题：[faq/known-issues.md](faq/known-issues.md)
- 方法论：
  - [通知类副作用保护](methodologies/notification-side-effect-guard/index.md)
  - [摄像头面板画面修复与验收](methodologies/camera-panel-visual-verification/index.md)

## Agent 入口

Agent 先读 [AGENT.md](AGENT.md)，再按系统进入：

- Windows Agent 部署：[windows/agent-install.md](windows/agent-install.md)
- macOS Agent 部署：[macos/agent-install.md](macos/agent-install.md)
- NAS Agent Docker 部署：[nas/agent-install.md](nas/agent-install.md)
- NAS 硬门槛：[nas/index.md](nas/index.md)
- NAS Docker 部署：[nas/docker-deploy.md](nas/docker-deploy.md)
- 华为 SWR 镜像上传/管理：[huawei-swr-docker-image-runbook.md](huawei-swr-docker-image-runbook.md)
- Release 打包：[runbooks/make-release-package.md](runbooks/make-release-package.md)
- 变更排障：[runbooks/change-and-debug-runbook.md](runbooks/change-and-debug-runbook.md)

## 保留范围

| 路径 | 用途 |
| --- | --- |
| `windows/` | Windows 一键包和部署指南 |
| `fix-camera/` | 摄像头接入、感知、denylist 和视频流排障文档 |
| `macos/` | macOS 一键包和 Agent 指南 |
| `nas/` | NAS 部署硬门槛、Docker Compose 部署和后续适配入口 |
| `methodologies/` | 可复用的问题分析、修复和验证方法论 |
| `scripts/` | release 包复用的预检、收尾、验收和发布脚本 |
| `runbooks/` | 通用发版、排障和 NAS 安装说明 |

## 隐私规则

- 不提交 API Key、OAuth code、token、设备 PIN、真实家庭名、真实主机名、真实用户路径或实机长日志。
- 验证记录只保留结论和可复用步骤；原始日志放在本机 ignored 目录或用户私有知识库。
- `docs/` 只服务公开发行和 Agent 路由，不做聊天记录归档。
