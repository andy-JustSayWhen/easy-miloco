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
| 米家 App 能看，但 Miloco 仍提示没有摄像头在感知 | 不要把手机 App 画面当作 Miloco 已拿到画面。优先查 NAS 是否发现摄像头局域网地址、Miloco 是否收到 keyframe。 |
| `lan_online=true`、`local_ip` 有值，但仍无画面 | 不要继续让用户反复点开关。继续查底层 SDK 是否收到 raw/JPEG/frame，必要时调用设备 spec 中的视频流动作做验证。 |

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
- 首页空态不能只提示“打开开关”。如果存在 `in_use=true` 且 `connected=false` 的摄像头，必须展示 `stream_message`；只有所有摄像头 `in_use=false` 时，才提示用户打开开关。
- 如果设备只能通过单点 LAN 探测找到 IP，写入 `camera_lan_overrides.json` 只能修复“找不到局域网地址”这一层；仍需用快照、短录制或 SDK probe 证明确实有画面帧。

### 已开启但 0 个在感知

这个状态要先拆成两层，不要反复让用户点开关：

| 字段组合 | 含义 | 下一步 |
| --- | --- | --- |
| `in_use=false`、`connected=false` | 用户没有允许 Miloco 使用这台摄像头 | 引导用户打开该摄像头开关 |
| `in_use=true`、`connected=false` | 开关已保存，但后端没有收到可解码视频帧 | 查 `stream_state`、快照、短录制和底层 SDK probe |
| `in_use=true`、`connected=true` | 后端已经收到帧 | 再查 `active_sources` 和 OpenClaw 视觉链路 |

如果 `stream_state=lan_not_found`，且快照返回 `no recent frame`、短录制返回 `no keyframe`，必须继续做 direct SDK probe。probe 结果如果是 `raw=0`、`jpg=0`、`frame=0`，同时状态停在 `CONNECTING`，说明视频数据面没有打通；这时不能把“米家 App 能看”当作 Miloco 已恢复的证据。

### 米家 App 能看，但 Miloco 没画面

米家 App 能预览，只能证明摄像头和米家云端账号可用；不能证明 NAS 上的 Miloco 已经拿到本地视频流。Miloco 需要在 NAS 侧通过底层 MIoT SDK 建立视频通道，再拿到可解码帧后才能进入感知。

按下面顺序判断：

1. 查 scope 状态。如果目标摄像头 `online=true`、`in_use=true`，但 `connected=false`，说明开关已经打开，问题不在前端按钮。
2. 查摄像头列表。如果目标摄像头 `lan_online=false` 且 `local_ip=null`，同时同一网络里的其他摄像头有 `lan_online=true` 和局域网 IP，优先判断为 NAS 没发现这台摄像头的局域网地址。
3. 查感知引擎。如果 `active_sources=[]`，说明当前没有任何摄像头正在给感知引擎投喂画面。
4. 查快照。如果 `/api/miot/snapshot` 返回 `no recent frame`，说明后端缓存里没有最近画面。
5. 查短录制。如果 `/api/miot/record_clip` 超时并提示 `no keyframe`，说明视频通道没有产出可独立解码的关键帧。
6. 查日志。如果日志只有 `Start video stream`、`Recorder attached`，但随后没有解码出帧，并出现 `no keyframe within ...s`，说明问题在视频数据面，不是 UI 展示。
7. 如果单点 LAN 探测能把目标摄像头映射到局域网 IP，可把该 IP 写入 `camera_lan_overrides.json` 后重启后端；但重启后仍必须验证 `connected=true`、快照 HTTP 200 或短录制 HTTP 200。
8. 如果 `lan_online=true`、`local_ip` 有值但 direct SDK probe 仍是 `raw=0`、`jpg=0`、`frame=0`，说明已经过了“找 IP”阶段，断点在底层视频通道。继续查设备 spec 是否有 `start-p2p-stream` / `stop-stream` 之类动作，只读确认后再谨慎调用。

### `chuangmi.camera.061a01` 不出帧

`chuangmi.camera.061a01` 已验证不是“摄像头开关未开启”问题：`on@摄像机控制=true`，LOW 画质、LAN override、先注册 JPG 回调再启动 SDK、以及启动前执行 `stop-stream` / `start-p2p-stream` 均不能让底层 SDK 吐出 raw/JPG/frame。

2026-07-06 NAS 复测补充：

- 当前容器已具备 host 网络视角，可直接看到 NAS 局域网地址 `192.168.31.225`，排除 bridge/NAT 网络层导致的 P2P 不通。
- 三台摄像头均 `is_set_pincode=0`，排除 PIN 导致的鉴权失败。
- direct SDK probe 对照：`chuangmi.camera.021a04` 与 `chuangmi.camera.036a02` 约 2 秒内分别拿到 raw/JPG；同账号、同 NAS、同 LOW 画质下，`chuangmi.camera.061a01` 在 `channel_count=1` / `channel_count=2` 均为 raw=0、JPG=0，状态停留在 CONNECTING。
- 启动 SDK 后再调用 `stop-stream` / `start-p2p-stream` 返回 code=0，但仍 raw=0、JPG=0；排除“动作触发时机”导致的不出帧。
- 官方 `v2026.7.3` 发行包里的 `libmiot_camera_lite.so` 与 NAS 当前运行库 sha256 前缀同为 `82c4b30a9838c797`，排除“公开最新版 SDK 还没升级”这一层。
- `HIGH` 画质、`LOW + enable_audio=True` 两种额外启动参数仍为 raw=0、JPG=0、audio=0，排除“画质参数或音频握手”导致的不出帧。
- 运行态修复应先把 Miloco scope 切到已验证能出帧的摄像头，例如同房间 `450305034`。切换后需验证 `connected=true` 且 `/api/miot/snapshot` 返回 `image/jpeg`。

当前处理口径：

- 后端 `scope camera list` 返回 `stream_state=native_stream_no_frames`，不要再提示用户“打开开关开启感知”。
- 如果没有外部桥接流，后端应拒绝把该型号重新启用为感知源，避免单摄像头家庭反复进入“没有摄像头在感知”的状态。
- 如果已经配置外部桥接流，后端应返回 `stream_state=external_stream_configured`，并允许启用；预览、录入和感知统一改用桥接流。
- 前端应显示“底层视频通道未出帧”的原因，避免误导用户反复开关。
- 身份录入先走上传照片/视频路径，或换一台已验证可出帧的摄像头。
- 不要把米家 App 能看画面当成 Miloco 已可感知的证据；App 可能走云端或不同视频通道。

### 外部桥接流兜底

当目标摄像头在米家 App 能看、但 Miloco 原生 SDK 始终 `raw=0`、`JPG=0`、`frame=0` 时，可以给该摄像头配置外部桥接流。桥接流只解决“视频帧如何进入 Miloco”，不负责替用户拿到小米私有通道凭据；上游可以是 go2rtc、已开放 RTSP 的摄像头、或其他能输出 HTTP/MJPEG/RTSP 的网关。

配置写入 `$MILOCO_HOME/config.json`：

```json
{
  "camera": {
    "video_quality": "LOW",
    "external_stream_frame_interval": 1000,
    "external_streams": {
      "<camera_did>": "rtsp://127.0.0.1:8554/<stream_name>"
    }
  }
}
```

字段含义：

- `external_streams`：按摄像头 DID 映射到外部视频流地址。
- `external_stream_frame_interval`：外部流投喂给 Miloco 的最小帧间隔，低配 NAS 建议从 `1000` 毫秒开始。
- `video_quality=LOW`：保留低画质配置，避免原生路径或其他摄像头被误切回高负载。

验证顺序：

1. 重启后端。
2. `miloco-cli scope camera list --pretty` 中目标摄像头应显示 `stream_state=external_stream_configured`。
3. 打开该摄像头开关。
4. 等待首帧后，目标摄像头应变成 `connected=true`。
5. 用 `/api/miot/snapshot` 或首页实时画面确认 Miloco 已拿到真实画面。

如果桥接流地址不可达，状态会停留在“等待第一张可分析画面”。这时不要再反复切开关，先用 ffmpeg、ffprobe 或 go2rtc 页面验证桥接流本身是否可播放。

#### go2rtc 桥接小米摄像头

`chuangmi.camera.061a01` 这类米家 App 可看、Miloco 原生 SDK 不吐帧的机型，可先用 go2rtc 建立小米视频源，再把 go2rtc 输出的 RTSP 地址交给 Miloco。

NAS x86_64 手动安装示例：

```bash
mkdir -p /data/go2rtc
curl -L -o /data/go2rtc/go2rtc \
  https://github.com/AlexxIT/go2rtc/releases/download/v1.9.14/go2rtc_linux_amd64
chmod +x /data/go2rtc/go2rtc
cat >/data/go2rtc/go2rtc.yaml <<'YAML'
api:
  listen: ":1984"
rtsp:
  listen: ":8554"
webrtc:
  listen: ":8555"
log:
  level: info
streams: {}
YAML
nohup /data/go2rtc/go2rtc -config /data/go2rtc/go2rtc.yaml \
  >/data/go2rtc/go2rtc.log 2>&1 &
```

打开：

```text
http://<nas-ip>:1984/
```

在 go2rtc WebUI 中添加 Xiaomi 源并登录小米账号。Miloco 的 OAuth token 不能直接替代 go2rtc 需要的小米网页登录凭据；如果当前机器只有 `MIOT_TOKEN_INFO_KEY.access_token` / `refresh_token`，仍需要在 go2rtc 里单独登录或提供 passToken。

建议流名固定为：

```text
mi_061a01
```

go2rtc 源创建成功后验证：

```bash
curl -fsS http://127.0.0.1:1984/api/streams
```

确认存在 `mi_061a01` 后，在 Miloco 配置中写入：

```json
{
  "camera": {
    "video_quality": "LOW",
    "external_stream_frame_interval": 1000,
    "external_streams": {
      "<camera_did>": "rtsp://127.0.0.1:8554/mi_061a01"
    }
  }
}
```

然后重启 Miloco 后端并打开该摄像头开关。最终验收仍以 Miloco 的 `connected=true`、首页真实画面或 `/api/miot/snapshot` 成功为准。

排除项：

- 临时停止手机端预览或调用设备 stop stream 后仍无 keyframe：不是手机 App 占用导致。
- 临时调用 start p2p 后仍无 keyframe：不是缺少显式启动动作导致。
- 临时把目标摄像头从 LOW 切到 HIGH 后仍无 keyframe：不是低画质流不兼容导致。测试后必须恢复 LOW，避免低配 NAS 压力升高。
- 旧版 MIoT SDK 缺少 raw packet 注销方法时，重建相机 manager 不能因此中断；应兼容缺失方法并继续执行底层 camera destroy/evict，否则下一次重建可能复用已损坏实例。

处理建议：

- 确认 NAS 和摄像头在同一个 Wi-Fi / 网段。
- 关闭访客网络、AP 隔离、路由器客户端隔离。
- 重启目标摄像头、路由器或 NAS，再观察 `lan_online` 和 `local_ip` 是否恢复。
- 如果其他摄像头正常、只有单台失败，优先处理该摄像头的网络接入、固件状态或重新绑定。
- 交付时不得只说“服务健康”。必须说明是否已经满足 `connected=true`、`active_sources` 包含目标摄像头、快照或短录制成功。

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
