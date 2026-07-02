# AGENT.md

这是公开文档入口。Agent 在本仓库处理部署、排障、发版或文档任务时，先读本文件，再进入对应指南。

## 总规则

1. 先判断系统和任务类型：部署、诊断、摄像头、发版、更新文档。
2. 不盲目重装；先看诊断报告和分层状态。
3. GitHub Release 是唯一版本基准。
4. 公开 `docs/` 不保存实机长日志、授权码、API Key、token、设备 PIN、家庭名、真实主机名或个人路径。
5. 私有实录放入用户私有知识库或 ignored 目录，不进入 release 包。

## 任务路由

| 用户说法 | 读取 |
| --- | --- |
| 部署 Miloco | [install-guide.md](install-guide.md) |
| Windows 部署 | [windows/agent-install.md](windows/agent-install.md) |
| macOS 部署 | [macos/agent-install.md](macos/agent-install.md) |
| NAS 部署 | [nas/index.md](nas/index.md)、[nas/agent-install.md](nas/agent-install.md)、[nas/docker-deploy.md](nas/docker-deploy.md) |
| 华为 SWR 镜像上传/管理 | [huawei-swr-docker-image-runbook.md](huawei-swr-docker-image-runbook.md) |
| 摄像头排障 | [fix-camera/index.md](fix-camera/index.md) |
| 制作 release 包 | [runbooks/make-release-package.md](runbooks/make-release-package.md) |
| 通用变更排障 | [runbooks/change-and-debug-runbook.md](runbooks/change-and-debug-runbook.md) |

## 文档维护

- 新增公开经验时，优先更新现有小文档，避免新增零散文件。
- 不能脱敏的内容不要写入 `docs/`。
- 删除文档后必须同步修正索引和链接。
