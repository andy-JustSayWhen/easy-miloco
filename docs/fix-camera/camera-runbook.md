# 摄像头排障 Runbook

本文只保留通用排障方法。真实设备名、DID、PIN、家庭名、截图和实机日志不得写入公开 docs。

## 六层模型

按下面顺序定位，不要一上来重装：

1. 小米账号：`miloco-cli account status` 必须显示已绑定。
2. 设备列表：`miloco-cli device list` 必须能列出设备。
3. 摄像头 scope：`miloco-cli scope camera list --pretty` 能看到目标摄像头，且目标摄像头已启用。
4. 局域网状态：确认本机和摄像头在可互通网络内，排除访客网络、隔离 SSID、VPN、防火墙和跨小区网络。
5. 流连接：Miloco 后端能拿到帧，`connected=true`，engine status 的 `active_sources` 包含目标摄像头。
6. OpenClaw 视觉：在 OpenClaw 聊天中询问摄像头画面，确认回答基于真实画面。

## 快速判断

| 现象 | 优先判断 |
| --- | --- |
| 米家 App 正常，Miloco 设备列表为空 | 账号授权、home 选择、MIoT token |
| 设备在线但摄像头无画面 | 局域网、视频数据面、scope 是否启用 |
| WebUI 有画面但 OpenClaw 看不到 | `active_sources`、视觉模型配置、OpenClaw 插件状态 |
| 单个摄像头失败，其他摄像头正常 | 摄像头所在 Wi-Fi、设备固件、设备侧重启 |
| 所有摄像头失败 | 本机网络、WSL mirrored networking、防火墙、后端 camera service |

## 必查命令

```bash
miloco-cli account status
miloco-cli device list
miloco-cli scope camera list --pretty
miloco-cli service status
```

后端健康：

```bash
curl -fsS http://127.0.0.1:<miloco_port>/health
```

OpenClaw：

```bash
openclaw gateway status
openclaw plugins inspect miloco-openclaw-plugin
```

## Windows/WSL 注意事项

- Windows 必须通过 WSL2 跑 Miloco 后端。
- 摄像头本地流通常需要 WSL mirrored networking 和 Hyper-V 防火墙允许入站。
- 远程 SSH 排障时，简单命令直传；复杂命令先落到临时脚本再执行，避免多层引号污染判断。

## denylist 修复

如果摄像头出现在 scope 列表，但名称带“不支持感知”或疑似被 denylist 误拦截，使用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\docs\scripts\fix-camera-denylist.ps1 -Model "<model>" -RestartService -Verify
```

普通用户可双击：

```text
docs\scripts\fix-camera-denylist.bat
```

## 交付标准

摄像头满血交付至少同时满足：

- 小米账号已绑定。
- 目标摄像头已在 scope 中启用。
- 目标摄像头 `online=true`、`in_use=true`。
- Miloco 能拿到视频帧，`connected=true`。
- engine status 的 `active_sources` 包含目标摄像头。
- OpenClaw 能描述对应摄像头画面。
