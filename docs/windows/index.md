# Windows 部署入口

Windows 只走 WSL2，不支持 Windows 原生后端。

## 入口

- Agent 一键部署：[agent-install.md](agent-install.md)
- Agent 一句话提示：[agent-prompt.md](agent-prompt.md)
- Release 包说明：[release-package.md](release-package.md)
- Release notes 模板：[release-notes-template.md](release-notes-template.md)
- 摄像头排障：[../fix-camera/camera-runbook.md](../fix-camera/camera-runbook.md)
- 摄像头 denylist 修复：[../fix-camera/camera-denylist-auto-fix-guide.md](../fix-camera/camera-denylist-auto-fix-guide.md)

## 验收口径

- `BASIC_READY=yes`：Miloco、OpenClaw 和插件基础链路可用。
- `FULL_READY=yes`：小米账号、模型配置、设备、摄像头 scope 和 OpenClaw 对话都可用。
- `FULL_READY=no` 不等于安装失败；按输出缺口补账号、模型、设备或摄像头。

## 隐私口径

不要把 Windows 实机日志、远程主机名、OAuth payload、API Key、token、设备 DID/PIN 或用户路径写入公开 docs。
