# 低配 NAS 性能优化当前状态

最后更新：2026-07-04

本文记录当前 NAS 低配性能优化的可交接状态。它只保留可复用结论和排障路径，不记录 API Key、token、授权 payload、真实长日志或截图证据。

## Goal 状态

当前 `/goal` 状态是 `paused`，不是已完成。

目标仍是：让 Miloco 在低配 NAS 上运行时，Miloco 服务整体 CPU 和 RAM 峰值都不超过宿主机 50%。CPU 指宿主机总核算力占比，例如 4 核机器的 50% 预算约等于 200% 进程 CPU；RAM 指 Miloco 进程 RSS（常驻内存，实际占用的物理内存）。

## 已完成到哪一步

已经完成：

- 梳理了 Miloco 运行链路：摄像头拉流和解码、Gate（画面变化检测）、Identity（身份识别与跟踪）、Omni（云端多模态理解）、事件回放。
- 证明 LLM API 已配置并不等于本地无压力。云端只接管理解，NAS 本地仍要做拉流、解码、画面检测、身份识别、视频构造和上传前处理。
- 在一路桌面摄像头上完成多轮 NAS 实测，定位过 CPU 峰值主要来自高频输入、身份识别、Omni 窗口叠加，以及部分本地视频处理链路。
- 已把低配关键参数纳入性能配置闭环，包括拉流质量、取帧间隔、缓存、输入 FPS、Omni FPS、身份识别模式、音频感知、硬件解码尝试等。
- 已做过热补丁验证：低配参数下单路静态场景 CPU/RAM 有明显余量；默认质量在一路静态场景通过线程收敛和 CPU 亲和性约束后可以压到 50% 预算附近。
- 已验证绿联 Docker 的端口映射模式会破坏摄像头感知：网页和 OpenClaw 能打开，但容器处在 bridge 网络内，摄像头视频流收不到有效帧。现场已把运行容器恢复到 host 网络，局域网地址保持为 `http://192.168.31.225:1810/`，OpenClaw 控制台地址为 `http://192.168.31.225:18789/`。

尚未完成：

- 上述性能页和后端补丁还没有全部固化到当前运行镜像和发布包。只在旧容器里热改的内容，容器重建后会丢失。
- 当前 NAS 容器重建后，Web 性能页回到了镜像自带的默认性能报告页。这不是前端自动切换，而是旧容器热改未固化导致的回退。
- 当前感知引擎曾出现 `OmniConfig.__init__() got an unexpected keyword argument ...`，说明运行时配置字段和容器内代码版本不一致。该问题需要先修复，否则“性能达标”没有意义。
- OpenClaw 的 Miloco 插件状态需要重新核验。容器重建后，如果插件是在旧容器内临时安装或热改的，也可能丢失。
- 还没有完成多路摄像头、有人移动、夜间、规则频繁触发、长时间运行的最终验收。

## 为什么性能页变回默认

恢复绿联快捷访问时，操作路径是通过绿联 Docker 项目更新，把 compose 从 `network_mode: host` 调回端口映射模式：

```yaml
ports:
  - "1810:1810"
  - "18789:18789"
```

这个操作会重建容器。重建后，容器内容来自镜像本身；之前直接在旧容器里替换的 Web 静态资源、后端热补丁和插件改动不会自动存在。

这个操作还有第二个副作用：摄像头视频链路会从宿主局域网直连变成 Docker bridge 网络。网页端口仍然能访问，但摄像头 PPCS/UDP（摄像头点对点视频通道）收不到可用帧，表现为摄像头 `connected=false`、感知引擎没有 `active_sources`。

因此当前看到默认性能报告页，根因是“热改没有固化到镜像/仓库部署路径”，不是用户点错页面，也不是浏览器缓存导致的唯一问题；而“没有摄像头在感知”的根因是 post/ports 网络模式破坏了视频通道。

2026-07-04 现场修复结果：

- 旧 bridge 容器路由为 `172.21.0.0/16`，摄像头均无法稳定进入感知。
- 停止并移除旧孤儿容器后，用同一数据目录创建 host 网络容器；绿联项目临时名为 `miloco-host`，容器名仍为 `miloco`。
- 已将 NAS 数据目录里的 `/data/docker-compose.yaml` 从 ports 映射改回 `network_mode: host`，旧文件备份为 `/data/docker-compose.yaml.bak-codex-ports-20260704-040225`。
- 新容器路由回到宿主 `192.168.31.225`，`/health` 恢复。
- 当前只开启一路摄像头，`主卧 电脑桌上` 为 `in_use=true`、`connected=true`，感知引擎 `active_sources` 已包含该摄像头。

2026-07-04 追加复验：

- OpenClaw 网关健康接口返回 `live`，`openclaw plugins list --enabled --verbose` 显示 `miloco-openclaw-plugin` 已启用。
- 后端主动感知问答可读取 `主卧 电脑桌上` 画面并返回中文描述。
- Miloco 首页小卡片曾卡在“已连接摄像头，等待画面…”。原因不是摄像头没有画面，而是小卡片常驻 `watch.html` iframe，会触发额外 H.264 预览转码链路；在低配 NAS 上这条链路既重又容易卡首帧。
- 当前热修把首页小卡片和放大弹窗都改为 `/api/miot/snapshot` JPEG 快照：直接复用感知缓冲里的最近 BGR 帧，小卡片缩到 640px 宽，放大态缩到 1280px 宽后返回 JPEG。Chrome 实测小卡片和放大态都显示真实画面，DOM 中不再常驻 iframe。
- 验证口径必须分开：`connected=true` 和主动感知问答成功只能证明后端有画面；必须再用浏览器截图或 DOM 检查确认面板实际显示了图片。

2026-07-04 08:15 追加复验：

- NAS 当前 `camera.video_quality` 曾被打回 `HIGH`，这不符合低配策略；已改回 `LOW`，并确认 `camera.frame_interval=5000`、`camera.max_cache_images=2`。
- Miloco 后端重启后 `/health` 返回 `ok`。Chrome 重新加载 `index-NFjRgGlc.js` 后，小卡片快照为 640x360；点开放大弹窗后无 iframe，放大快照约 1279x720。
- OpenClaw 报错 `reply session initialization conflicted` 是当前 dashboard 会话的回复锁冲突，不是 Miloco 插件未加载。重启 OpenClaw gateway 后，同一会话发送无隐私测试消息可正常回复 `OK`，冲突错误未再出现。

2026-07-04 09:20 追加复验：

- 用户刷新页面后仍看到“0 个在感知”，但接口实时状态已是 `主卧 电脑桌上 in_use=true connected=true`，`/api/perception/engine/status` 也显示 `active_sources=[1146439633]`。后端日志在 `09:09:30` 先出现 `connection pending`，随后 `09:10` 后已 `n_cam=1` 并持续产生感知结果。
- 根因不是摄像头没开，也不是 LOW 拉流失败；根因是前端初次读到 `in_use=true connected=false` 后没有自动刷新 scope camera 状态，页面停在“0 个在感知”的旧快照。
- 当前热修在前端加入短轮询：只要存在 `in_use=true` 且 `connected=false` 的摄像头，就每 2 秒刷新 scope cameras、camera channel 和 status，最多约 90 秒。Chrome 复验加载 `index-B4xA4qAJ.js` 后，页面显示 `1 个在感知`，快照 640x360 正常，无 iframe。
- OpenClaw 当前会话中的工具执行状态曾污染后续消息，表现为普通文本也被拉进 `miloco-perception` skill。重启 OpenClaw gateway 后，`主卧画面，一句话` 已正常调用 `miloco-cli perceive query --source 1146439633` 并返回“你正坐在书桌前专注地操作电脑”，没有新增会话冲突。

2026-07-04 10:18 追加复验：

- OpenClaw WebChat（网页聊天入口）报 `reply session initialization conflicted` 的根因是同一个 session（会话，同一段聊天上下文）里上一条回复还没结束，用户又发送了下一条。它不是 Miloco 插件未加载，也不是摄像头未感知。
- 只在 OpenClaw 后端加 retry（重试）不够：第二条消息已经先进入 WebChat queue（排队），后续仍可能撞到同一个会话初始化锁。
- 当前 NAS 热修和仓库固化改为两层保护：代理给 OpenClaw 页面加 no-store（不缓存）和发送提示；同时热补 OpenClaw control-ui 静态 JS，在 busy（上一条仍处理）时移除第二条队列消息并显示“上一条还在处理，请等回复完成后再发送。”
- Chrome 复验：连续发送 `防连发验证A` 和 `防连发验证B`，第二条没有进入聊天历史，没有出现 `Queued`，页面显示中文提示；10:15 之后 OpenClaw 日志没有新增 `reply session initialization conflicted` 或 `outcome=error`。
- 同轮核对 Miloco：`/data/miloco/config.json` 保持 `camera.video_quality=LOW`、`frame_interval=5000`、`max_cache_images=2`、`input.fps=1`、`tracking_service_mode=mock`、`identity_engine.enabled=false`；Miloco 首页显示 `1 个在感知`，不是“0 个在感知”。

正确修复路径是：

1. 先把当前代码仓库中的性能中心、配置 API、低配参数、视觉可读性修复全部确认可构建。
2. 生成新的镜像或可重复部署包。
3. 用该镜像重新部署 NAS。
4. 重启后验证性能页仍是低配资源中心，而不是默认性能报告页。

## 当前最高优先级问题

### 1. 先恢复感知引擎

症状：

- 首页提示“还没准备好”。
- 错误类似 `OmniConfig.__init__() got an unexpected keyword argument ...`。

含义：

- `OmniConfig` 是 Omni 配置对象。
- 这个错误表示配置文件里出现了容器内代码不认识的字段。
- 常见原因是代码和配置不是同一版本，例如配置里已有 `allow_h265_remux`，但运行镜像内的 `OmniConfig` 还没有这个字段。

处理原则：

- 不要只点“重启感知”反复撞。
- 先让配置 schema（配置字段定义）和运行镜像代码对齐。
- 修复后再通过 `/health` 或页面状态确认感知引擎真正 ready。

### 2. 再恢复低配性能页

性能页必须面向小白用户：

- CPU/RAM 卡片要用中文解释“现在用了多少、预算是多少、是否超限、会影响什么”。
- 饼图显示谁在吃时间或资源，例如拉流解码、画面变化检测、身份识别、云端理解。
- 柱状图显示 P95（95% 情况下不会超过的高位耗时），并用中文括号解释。
- 参数表要以中文为主，英文参数名低权重保留。
- “影响”列要说清楚参数作用、支持范围和改动代价。
- 点“应用并重启”后必须显示等待提示，并轮询健康接口；不能让用户误以为按钮失效或没有变化。

### 3. 最后做 NAS 复验

复验必须分两轮：

- 第一轮：不降低运行质量。验证默认画质、默认感知质量下，通过线程收敛、CPU 亲和性、remux、资源监控降频等方式是否能压住峰值。
- 第二轮：保留约 80% 服务质量。验证 LOW 拉流、低 FPS、弱身份识别或按需触发等低配方案是否在真实家庭场景可接受。

每轮都要在 NAS 上实际采样，不能只看本地测试或浏览器截图。

## 当前不要做什么

- 不要继续在旧容器里堆一次性热改，然后把它当作正式结果。
- 不要为了测试打开多个浏览器、多个控制台或长期后台脚本。
- 不要提交真实 token、授权 payload、家庭日志或长 trace。
- 不要在感知引擎未 ready 时宣布性能优化完成。

## 下一步建议顺序

1. 固化 `OmniConfig` 字段兼容，解决感知引擎启动异常。
2. 固化低配性能中心 UI 和后端 API 到仓库构建产物。
3. 重新构建并部署 NAS 镜像，确认容器重建后页面不再回退默认版。
4. 验证 OpenClaw Miloco 插件仍可用。
5. 用单路桌面摄像头跑 5-10 分钟只读采样。
6. 再进入多路、移动、夜间和规则触发场景验收。
