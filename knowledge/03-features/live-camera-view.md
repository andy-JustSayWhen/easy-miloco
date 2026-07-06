# 实时摄像头观看

## 背景与目标

用户想随时查看家里摄像头的实时画面——孩子是否安全回到家、老人状态如何、有没有陌生人闯入。传统方式需要打开米家 App，在众多设备中找到摄像头，且依赖手机 App 安装。

Miloco 让用户通过浏览器直接看到家中摄像头的实时画面，无需安装任何 App，无需设备配对——在家庭面板的浏览器标签页里打开即可。

---

## 产品面

### 能做什么

- **跨平台无插件**：支持任意现代浏览器（Linux Chrome / macOS Safari / iOS Safari / Android Chrome），无需安装额外组件
- **多标签低 CPU 复用**：多个浏览器标签页同时观看同一摄像头，编码仅发生一次，额外订阅者只增加网络转发开销，不增加 CPU
- **与感知流水线共解码**：直播和感知流水线共用同一次解码，不额外占用摄像头资源
- **多摄像头支持**：家庭面板可切换查看不同摄像头和 channel

### 典型场景

**场景 1 — 下班前确认**：父母下班路上，在手机浏览器打开 Miloco 家庭面板，切到摄像头直播，确认孩子已回家、安全做作业。无需 App，扫码或书签即可访问。

**场景 2 — 多标签同时监看**：家庭面板在电脑上开多个标签，分别观看客厅和卧室摄像头。两路直播同时运行，但 CPU 占用不成倍增加，因为同一摄像头只做一次 H.264 编码。

### 能力边界

- 不支持 PTZ 控制或双向语音
- 实时观看依赖摄像头与 Miloco 服务在同一局域网；PPCS P2P 连接需要 UDP 入站（防火墙配置见 [故障排查 · 摄像头连接问题](../06-dev-guide/troubleshooting.md#摄像头连接问题)）
- 不支持录制或历史回放（有价值事件的视频片段另有 meaningful_events 机制保存）
- 不支持跨局域网/公网访问，需摄像头和服务在同一网络

---

## 研发面

### 架构概览（数据流图）

```
GET /api/miot/watch → watch.html（server.token 注入）
  → 浏览器 WebSocket 接入 /api/miot/ws/video_stream?camera_id=...&channel=...
  → MIoTVideoStreamManager（miot/ws.py）
      第一个订阅者 → 创建 H264LiveEncoder（miot/transcoder.py）+ 注册帧回调
      后续订阅者  → 复用已有编码输出
  → H264LiveEncoder（统一重编为浏览器兼容 H.264 NAL 流）
  → WebSocket 推给浏览器
  → 浏览器解码渲染：WebCodecs VideoDecoder（secure context）或 MSE+jmuxer（LAN HTTP 回退）
```

解码层由 MiOT SDK PyAV 完成（摄像头原始码流 → BGR ndarray）。感知流水线和直播通过 `start_camera_decode_video_stream`（`multi_reg=True`）共用同一次解码，各自独立回调，互不干扰。

### 核心模块

**`/api/miot/watch` 端点**（`miot/router.py::watch_page`）

入口端点：读取 `static/watch.html` 模板，将 `__MILOCO_TOKEN__` 占位符替换为真实 `server.token` 后返回给浏览器。浏览器收到注入 token 的页面后，用 token 调 `/api/perception/devices` 拉摄像头列表，用户选择后通过 WebSocket 接入视频流。

**信任边界**：`/api/miot/watch` 响应体内嵌明文 token，等价于"能访问该 URL 的人拥有 token"。默认仅监听 `127.0.0.1`；若开放 LAN 访问，应自行评估网络可信边界。`server.token` 未配置则返回 `503`。

**MIoTVideoStreamManager**（`miot/ws.py`）

管理所有 WebSocket 订阅者。每个摄像头持有一个 `H264LiveEncoder` 实例；第一个订阅者触发编码器创建和帧订阅，后续订阅者直接复用已编码输出。首帧超时检测：若摄像头在指定时间内一帧都没出，向前端发送明确的 error 信令后关闭连接，避免用户看到"正在连接"一直等下去。

**H264LiveEncoder**（`miot/transcoder.py`）

将 SDK 解码出的 BGR 帧重编为浏览器普遍兼容的 H.264 NAL 流（限定 level 上限以保证兼容，具体见 `transcoder.py`）。WebSocket 新连接先发 init 消息（含编码格式信息），后续为视频帧数据。

### 关键设计决策

**为什么不直传原始码流而要重编**：摄像头原始码流可能是 H.264 或 H.265（HEVC）。H.265 在部分浏览器/系统中受专利限制无法直接播放；不同平台对 H.264/H.265 的硬解支持差异很大，直传需要逐平台适配。统一重编为浏览器普遍兼容的 H.264（限定 level 上限），任何现代浏览器都支持。代价是额外的 CPU 开销和一轮解码+编码的延迟。

**浏览器端解码双路径**：secure context（HTTPS / localhost）下用 WebCodecs `VideoDecoder` API，通过多档 `hardwareAcceleration` 轮试确保兼容性，解决 Linux Chrome / VAAPI 过度乐观导致运行时失败的问题。非 secure context（如 LAN HTTP 访问）下 WebCodecs 不可用，回退到 MSE + jmuxer（`/vendor/jmuxer.min.js`）：把 Annex-B NAL 重封为 fmp4 喂给 `<video>` 播放。

**直播与 scope/感知解耦**：watch 视频流由独立的 camera manager 维持，scope 切换、摄像头停用、感知暂停/停止都不会中断正在进行的直播——只要摄像头还在账号内，manager 即保活；仅当摄像头真正从账号消失才销毁。正因如此，前端无需在切换 scope/感知时弹"停止直播"确认框。

### 如果我要修改直播相关功能

| 修改目标                              | 去看哪个文件                                           |
| ------------------------------------- | ------------------------------------------------------ |
| 修改 WebSocket 订阅/管理逻辑          | `miot/ws.py`（MIoTVideoStreamManager）                 |
| 修改编码参数或 WebSocket 帧格式       | `miot/transcoder.py`（H264LiveEncoder）                |
| 修改 watch.html 页面或 token 注入逻辑 | `miot/router.py`（`watch_page`）和 `static/watch.html` |
| 修改浏览器端解码逻辑                  | `static/watch.html` 内的 JavaScript 部分               |

### 与其他模块的关系

**上游**：`MIoTVideoStreamManager` 通过 `MiotService.start_video_stream` / `stop_video_stream` 管理 SDK 订阅生命周期。

**共享**：感知流水线和直播共用 `start_camera_decode_video_stream`（`multi_reg=True`）的解码层，两者互不干扰——感知引擎不运行时，直播仍可正常工作。

### 身份录入里的摄像头预览

身份录入弹窗的“摄像头录制”不使用 `/api/miot/watch` iframe 直播作为取景器，而使用 `/api/miot/snapshot` 快照轮询。原因是身份录入真正需要的是“用户能确认人站进画面里”，不需要持续直播解码。

这样做有三个好处：

- 降低低配 NAS 压力：快照是最近一张 JPEG 图片，不会让浏览器额外跑 H.264/H.265 播放链路。
- 避开浏览器兼容问题：LAN HTTP 下 WebCodecs 不可用时，直播要回退 MSE + jmuxer；取景器走快照更稳定。
- 不影响录制质量：点“开始录制”后仍由后端 `/api/miot/record_clip` 从摄像头帧录制 MP4，再交给身份抽取接口分析。

排障时要区分三条链路：

| 链路 | 端点 | 用途 |
| --- | --- | --- |
| 快照预览 | `/api/miot/snapshot` | 首页卡片和身份录入取景器 |
| 直播观看 | `/api/miot/watch` + `/api/miot/ws/video_stream` | 用户主动打开实时观看 |
| 录制注册 | `/api/miot/record_clip` | 身份录入时生成 MP4 |

### 首页“已开启但没画面”的语义

首页的摄像头开关只表示 scope 已启用；真正能否进入感知，还要看后端是否拿到第一张可解码画面。

排障时不要只看开关状态，应同时看两组数据：

| 字段 | 含义 | 判断 |
| --- | --- | --- |
| `in_use` | 用户是否允许 Miloco 使用这台摄像头 | `true` 说明开关已保存 |
| `connected` | 后端是否已经收到可用于感知的视频帧 | `false` 说明还没进感知 |
| `active_sources` | 当前正在投喂感知引擎的摄像头列表 | 为空时，OpenClaw 看不到画面 |
| `stream_state` / `stream_message` | 后端流状态和给用户看的原因 | 优先展示给用户，避免只提示“打开开关” |

如果摄像头已启用但 60 秒内没有第一张解码帧，后端会记录流健康状态并触发一次底层连接重建；再次失败才进入冷却。这样低配 NAS 不会被无效重试持续占满，前端也能给出“正在等首帧 / 重试中 / 冷却后重试”的中文解释。

米家 App 能看到画面，不等于 Miloco 已经能感知。手机 App 可能走云端或自己的视频通道，而 Miloco 必须在 NAS 上通过底层 MIoT SDK 拿到可解码帧。若目标摄像头 `online=true`、`in_use=true`，但 `lan_online=false`、`local_ip=null`、`connected=false`，并且快照返回 `no recent frame`、短录制返回 `no keyframe`，页面应明确告诉用户“摄像头在线，但 NAS 没在局域网发现它的地址或没有拿到关键帧”，不能再显示“打开开关开启感知”。

这个状态的用户行动建议应是网络侧排查：确认 NAS 和摄像头同网段，关闭访客网络、AP 隔离或客户端隔离，重启摄像头/路由器/NAS，必要时重新绑定摄像头。产品侧只能把真实断点讲清楚，不能伪装成已经修复了画面。
