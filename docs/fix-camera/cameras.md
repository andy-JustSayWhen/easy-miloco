# 摄像头支持说明

Miloco 的摄像头能力依赖米家摄像头。摄像头需要先绑定到米家 App，并且在米家 App 中能正常打开画面。

## 状态分层

排障时不要只看“在线/离线”一个词，至少分四层：

| 层级 | 含义 | 典型来源 |
| --- | --- | --- |
| 云端在线 | 米家云端认为设备在线 | MIoT 设备列表、米家 App |
| 局域网在线 | 摄像头 SDK 在局域网中发现设备和 IP | `lan_online`、`local_ip`、LAN table |
| 流连接成功 | Miloco 后端已经拿到摄像头帧 | `connected`、`active_sources`、frame count |
| Agent 可用 | OpenClaw 对话能基于画面回答问题 | OpenClaw 聊天页视觉问答 |

WebUI 中“实时画面能看到”说明流连接可能成功；设备列表里的“离线”可能只是局域网状态层没有同步，不能直接等同于 OpenClaw 不能看画面。

## 常见边界

- `online=true` 只说明云端在线，不保证 Miloco 已拿到画面。
- `lan_online=false` 时，优先检查本机是否在家庭局域网、摄像头是否在访客/隔离/特殊 SSID、VPN 或防火墙是否阻断局域网流量。
- `connected=false` 但米家 App 正常时，优先看视频数据面、首帧、冷启动等待和后端日志。
- `active_sources` 不含目标摄像头时，OpenClaw 视觉问答可能拿不到对应画面。

## 模型能力提醒

- 视觉问答必须使用支持图像输入的模型。
- 配置模型时同时核对 API Key、Base URL 和 model 名称。

## 记录要求

公开 docs 只记录通用问题和修复方法。真实设备名、家庭名、DID、PIN、截图、日志和用户环境路径不得写入公开仓库。
