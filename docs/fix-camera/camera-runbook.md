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
| 首页显示“已开启，但还没拿到画面” | 摄像头开关已保存，优先查后端是否收到第一张可解码画面，而不是反复开关 |
| WebUI 有画面但 OpenClaw 看不到 | `active_sources`、视觉模型配置、OpenClaw 插件状态 |
| 单个摄像头失败，其他摄像头正常 | 摄像头所在 Wi-Fi、设备固件、设备侧重启 |
| 所有摄像头失败 | 本机网络、WSL mirrored networking、防火墙、后端 camera service |
| 身份录入弹窗黑屏，但首页摄像头有快照 | 优先查 `/api/miot/snapshot`，身份录入取景器应走轻量快照，不再依赖直播 iframe |
| 上传照片提示“未识别到人物” | 先确认照片里有上半身或全身；身份注册需要人体样本，不是只做人脸识别 |

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

感知状态：

```bash
curl -fsS -H "Authorization: Bearer <server_token>" \
  http://127.0.0.1:<miloco_port>/api/perception/engine/status

curl -fsS -H "Authorization: Bearer <server_token>" \
  http://127.0.0.1:<miloco_port>/api/miot/scope/cameras
```

判断：

- `in_use=true` 且 `connected=false`：开关已开启，但后端还没拿到可用于感知的视频帧。
- `active_sources=[]`：当前没有摄像头正在给感知引擎投喂画面。
- `stream_state` / `stream_message` 有值：优先按后端返回的中文原因排查，例如等待首帧、首帧超时、冷却后重试。
- 如果连续 60 秒没有第一张画面，后端会先重建底层摄像头连接；如果仍失败，再进入冷却，避免低配 NAS 被无效重试拖垮。

摄像头快照：

```bash
curl -fsS -o /tmp/miloco-snapshot.jpg \
  "http://127.0.0.1:<miloco_port>/api/miot/snapshot?camera_id=<did>&max_width=640&quality=72&token=<server_token>"
ls -lh /tmp/miloco-snapshot.jpg
```

身份录入短链路：先录一段，再让身份抽取接口找候选人物。这里的 body 是人体样本，face 是人脸样本。

```bash
curl -fsS -o /tmp/miloco-record.mp4 -X POST \
  -H "Authorization: Bearer <server_token>" \
  "http://127.0.0.1:<miloco_port>/api/miot/record_clip?camera_id=<did>&channel=0&duration_ms=3000"

curl -fsS -o /tmp/miloco-extract.json \
  -H "Authorization: Bearer <server_token>" \
  -F media=@/tmp/miloco-record.mp4 \
  -F max_frames=6 \
  "http://127.0.0.1:<miloco_port>/api/identity/persons/<person_id>/extract"

python - <<'PY'
import collections
import json

d = json.load(open("/tmp/miloco-extract.json"))["data"]
print("frames", d["n_frames"])
print("candidates", len(d["candidates"]))
print(collections.Counter(c["type"] for c in d["candidates"]))
PY
```

判断：

- 快照 HTTP 200 且文件大于 0：摄像头画面数据能到 Miloco。
- 录制 HTTP 200 且 MP4 大于 0：后端录制链路能复用摄像头帧。
- `candidates` 大于 0：身份抽取模型能在当前画面中找到人物。
- 只有上传照片失败：通常是照片质量或构图问题，要求上半身/全身、脸部清楚、光线足够。
- 自拍照如果 detector 已识别到 body 和 face，但 `/extract` 仍返回 0，重点检查质量门控。大幅自拍的人体框里常有大量墙面、衣服和天花板，整框 sharpness（清晰度分）会被平滑区域稀释；这类照片应允许“高置信 body + 高置信 face”通过注册门控。

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
