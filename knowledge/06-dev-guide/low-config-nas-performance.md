# 低配 NAS 性能优化

## 目标

低配 NAS 上运行 Miloco 时，Miloco 服务整体 CPU 和 RAM 峰值都应低于宿主机 50%。这里的 CPU 指宿主机总核算力占比，RAM 指 Miloco 进程常驻内存（RSS，操作系统实际分配给进程的物理内存）。

本页用于沉淀低配 NAS 的运行机制、压力来源、两轮优化方向和实测方法。具体配置字段、默认值和接口以代码与 schema 为准。

## 运行链路

```mermaid
flowchart LR
  A["摄像头压缩流<br/>(H.264/H.265 视频包)"] --> B["本地拉流与解码<br/>(还原成 BGR 像素帧)"]
  B --> C["时间窗缓冲<br/>(按窗口收集音视频)"]
  C --> D["Gate<br/>(本地变化检测)"]
  D -->|无变化| X["跳过 Identity / Omni<br/>(省掉后续算力)"]
  D -->|有变化| E["Identity<br/>(身份识别与跟踪)"]
  E --> F["Omni<br/>(云端多模态理解)"]
  F --> G["事件回放<br/>(复用 Omni 看到的视频字节)"]
```

关键点：

- 摄像头只拉一次流。实时感知链路不会为了 Omni 再向摄像头拉第二次。
- 本地拿到的是解码后的 BGR 像素帧（OpenCV/NumPy 常用的彩色图片数组），不是摄像头原始压缩包。
- Gate（本地变化检测）和 Identity（身份识别与跟踪）复用这批解码帧。
- Omni（云端多模态理解）需要把选中的帧重新编码成可上传的视频或图片格式。事件回放复用 Omni 看到的那份视频字节，不再二次编码。
- 实时观看页面是另一条消费路径。用户打开直播预览时，可能额外增加拉流、解码或传输压力。

当前已补上原始压缩视频包旁路：采集摄像头时，Miloco 可以同时保存 H.264/H.265 原始视频包和解码后的 BGR 图片帧。BGR 帧仍服务 Gate、Identity；原始视频包先随窗口带到 `DeviceSnapshot.encoded_video`，并记录 `encoded_video_packets` 计数。

Omni 上传路径已接入 remux：当本窗没有音频要合入视频，且原始 H.264 包可被 PyAV/FFmpeg 解析时，Miloco 会优先把原始包 streamcopy/remux 成 MP4 上传。这个过程不解码、不缩放、不重新压缩画面，所以目标是降低 Omni 上传前的本地 CPU 峰值。若 remux 失败、缺 I 帧、包格式不被解析，或需要把音频合入视频，则自动回退到旧的 BGR 图片帧重新编码 MP4，保证质量不打折。H.265 remux 默认仍关闭，因为前序验证发现长窗口 H.265 上传给 Omni 存在空回答风险；但已经增加实验开关 `perception.engine.omni.allow_h265_remux=true`，用于在真实 NAS 上验证“同一次 H.265 拉流资产能否直接复用到云端上传”。

二次编码的根因可以这样理解：摄像头送来的本来就是压缩视频包，解码是把它拆成图片给本地算法看；如果原始压缩包没有保留，云端要视频时只能把图片再压回视频。保留原始压缩包后，理想路径是只做 remux（重封装，只换 MP4 容器，不重新压缩画面），CPU 压力会明显低于重新编码。

2026-07-03 在 NAS 当前一路桌面摄像头上复查 trace：默认保护策略下，Omni 窗口能看到 `encoded_video_packets=1233`、`raw_encoded_video_window_packets=1200`、`raw_encoded_video_keyframes=26`，说明同一次拉流拿到的原始压缩包已经随窗口进入上传链路；但同一条 trace 也显示 `remux_success=0`、`remux_fallback=1`、`reencode=1`、`h265_remux_skipped=1`。结论是：默认情况下不是“Omni 又向摄像头拉了一次流”，而是“已经拿到的 H.265 原始包因兼容性保护不用来 remux，改用同一窗口里的 BGR 帧重新编码成 MP4 上传”。随后打开实验开关 `allow_h265_remux=true` 后，主动查询正常返回画面描述，视频构造统计变为 `remux_success=1`、`reencode=0`、`input_packets=432`、`output_bytes=462034`、`h265_remux_skipped=0`，说明这路 H.265 在短主动查询窗口里可以复用原始包上传，不再重新编码。

## 当前压力判断

NAS 上看到 CPU 或内存高时，先不要只看总数，要判断是哪一段在吃资源：

| 指标 | 通俗解释 | 常见含义 |
| --- | --- | --- |
| `decode_video_ms` | 解码耗时（把摄像头压缩视频还原成图片的时间） | 高分辨率、高码率或软件解码会拉高 CPU |
| `gate_video_ms` | 画面变化检测耗时（本地对图片做缩放、灰度、帧差） | 画面尺寸大、窗口帧多或摄像头多会拉高 CPU |
| `identity_ms` | 身份耗时（检测人、跟踪人、比对身份） | 多人、多摄像头或 ReID 模型会拉高 CPU/RAM |
| `omni_ms` | 云端理解耗时（上传视频并等待模型回答） | 高主要是网络/API 等待，不一定是本地 CPU |
| RSS | 常驻内存（进程实际占用物理内存） | 大量图片帧、模型、SDK 缓冲会推高 RAM |

已有 NAS 样本显示：即使只开一路摄像头，`decode_video_ms` 和 `gate_video_ms` 也可能成为主要压力，而 `omni_ms=0` 时说明当轮没有实际进入 Omni。此时瓶颈通常在本地拉流、解码和 Gate，而不是 LLM API。

## 已落地的降载能力

- 禁用摄像头后释放对应解码管理器，避免用户以为关了摄像头但后台仍在解码。
- 低配安全模式会调低采集深度、缓存、身份识别频率和 Omni 输入频率。
- 硬降载策略支持在队列堆积时丢弃旧窗口，避免积压把机器拖死。
- 性能页暴露运行期 CPU/RAM 预算、诊断、参数应用和后端重启闭环。
- 摄像头拉流质量已暴露为可调项，让低配 NAS 能选择较低码流，减少解码入口压力。
- Gate 的视觉检测改为流式比较，保持同样判定结果，同时减少窗口内临时灰度图驻留。
- 实时窗口 drain 后只保留最近一个已处理窗口给主动查询复用，避免 `keep` 模式把历史解码帧长期留在 RSS 中。
- BGR 帧回调现在遵守 `camera.frame_interval`。此前该参数只节流 JPEG 预览输出，不节流感知使用的 BGR 帧，导致 60 秒窗口仍进入 400 多帧。
- 资源监控的内存明细采样延后并降频。`smaps`（Linux 进程内存区域明细）和 Python heap（Python 对象堆）采样本身会遍历大量进程状态，在低配 NAS 上可能制造启动期或周期性 CPU 尖峰；运行期默认只保留轻量 CPU/RSS 采样，明细内存快照按较低频率采集。
- ONNX Runtime 推理线程自适应低核机器：4 核及以下默认减少 intra-op（算子内部并行）线程，inter-op（算子之间并行）固定为 1，避免检测模型和 ReID 模型在 NAS 上各自开满线程池互相抢 CPU。模型、输入、阈值和输出不变，只收敛调度并行度。
- 性能配置 API 会标记被 `MILOCO_*` 环境变量覆盖的参数，前端会显示“外部锁定”并禁用输入；直接调用应用接口时也会拒绝这类参数，避免写入 `config.json` 后重启仍不生效。
- 性能页阶段耗时区新增小白可读的资源归因饼图和 P95 柱状图：中文主标签说明“拉流解码、画面变化检测、身份识别、云端理解”等阶段，英文原阶段名低权重保留，便于把“谁吃资源”直接视觉化。

## 第一轮：不降低运行质量

第一轮只接受“不改变感知语义”的优化。目标是让同样的输入质量、同样的窗口策略下，本地少做无效工作。

推荐方向：

1. 解码链路前移优化  
   使用摄像头或 SDK 已支持的低开销通道，例如硬件解码（显卡/核显/芯片的视频解码单元）或 SDK 原生低码流能力。若输出给 Miloco 的有效画面质量不变，优先替换软件解码热点。

2. Gate 内存与临时数组收敛  
   Gate 只需要相邻抽检帧的差异，不需要长期持有整窗预处理结果。流式比较能减少 RSS 峰值，且不改变变化检测结果。

3. 窗口缓冲有界化  
   实时推理只处理最新窗口；主动查询也只需要最近窗口。已处理旧窗口应释放，只保留最新窗口给非破坏性读取，避免解码帧在内存里无限累积。

4. 编码路径复用  
   保持“Omni 看到的视频字节就是事件回放视频字节”的原则，避免上传后又为事件回放重复编码。下一步进一步复用摄像头原始 H.264/H.265 压缩包，优先走 remux（重封装，只换容器、不重新压缩画面），失败再回退到 BGR 重新编码。

5. 可观测性先于大改  
   性能页需要把 CPU 饼图和阶段柱状图做成小白可读：谁在吃 CPU、吃的是拉流/解码/Gate/身份/Omni 哪一段，必须直接显示。

候选技术：

- GStreamer 硬件解码（多媒体流水线，可自动或显式使用硬件解码器），适合 NAS 平台驱动可用时验证。
- FFmpeg 硬件解码（视频工具链，可接 VAAPI/QSV/NVDEC 等硬件后端），适合独立基准测试后替换解码层。
- FFmpeg/PyAV streamcopy/remux（流拷贝/重封装），官方语义是不解码、不滤镜、不编码，适合把摄像头原始 H.264/H.265 包直接封装成 Omni 可上传的 MP4；限制是必须拿到时间戳、codec 参数，并从 I 帧开始切片。
- FFmpeg motion vectors（运动向量，压缩视频里已有的块运动信息），可用于减少像素级帧差，但需要拿到原始压缩包，当前 SDK 回调只给解码帧，属于实验方向。
- OpenCV 流式帧差（当前使用的本地图片算法），优先做内存和临时对象优化。

外部来源和落地判断：

- [FFmpeg 硬件加速说明](https://trac.ffmpeg.org/wiki/HWAccelIntro)覆盖 VAAPI/QSV 等后端，适合作为 NAS 上“软件解码换硬解”的第一轮无损方向；Miloco 当前用 PyAV 包 FFmpeg，因此应优先验证 PyAV codec 是否可用，而不是只看系统 `ffmpeg` 命令。
- [FFmpeg streamcopy 文档](https://ffmpeg.org/ffmpeg.html#Streamcopy)说明 streamcopy 是直接拷贝压缩流，不经过解码/滤镜/编码；这正对应 Miloco 的 remux 路径，适合复用摄像头 H.264 原始包，避免上传 Omni 前再次压缩。
- [Intel VPL 文档](https://intel.github.io/libvpl/latest/index.html)覆盖硬件解码、编码和视频处理，但引入成本比 PyAV 直接用 FFmpeg QSV 更高；当前只作为后续镜像/runtime 层补齐后的备选，不作为先行改造。
- [OpenCV cvtColor 文档](https://docs.opencv.org/4.x/d8/d01/group__imgproc__color__conversions.html)确认当前 BGR/颜色转换语义；Miloco 当前 gate 只需要 448 灰度差分，优先收益来自“少帧、少拷贝、流式处理”，不是先引入更复杂的 GPU 图像管线。

硬件解码的部署前提必须单独确认。2026-07-03 在测试 NAS 上核实：CPU 为 Intel Celeron N5105，内核侧 `/sys/class/drm` 能看到 `renderD128`，PyAV/FFmpeg codec 列表里有 `h264_qsv`、`hevc_qsv` 等 Intel Quick Sync 入口；但 Miloco 当前运行环境里没有 `/dev/dri`。这说明硬件加速方向是可落地的，但部署层尚未把核显渲染设备暴露给 Miloco。仓库已新增 NAS Docker 的可选 `compose.hwaccel.yaml`，`manage.sh` 在宿主存在 `/dev/dri` 时可自动映射到容器；后续真正替换解码链路前，必须先在 NAS 上确认容器内能看到 `/dev/dri/renderD128`。

SDK 解码器也要配合部署前提。旧代码虽然有 `enable_hw_accel` 参数，但实际创建解码器时仍固定使用 `h264` / `hevc` 软件解码；旧的 `detect_hwaccel()` 还依赖系统 `ffmpeg -hwaccels`，而测试 NAS 当前没有 `ffmpeg` 命令。当前改为读取 PyAV 自身的 codec registry：启用硬件加速时优先尝试 `h264_qsv` / `hevc_qsv`，其次尝试 `v4l2m2m`，创建失败或解码中失败都自动回退到软件解码。这样硬件存在时可以省 CPU，硬件不可用时质量和行为不变。

产品配置链路也已经补齐：新增 `camera.enable_hw_accel`，默认 `true`，并纳入性能配置 API、低配安全模式和 supervisor `env -u` 解锁列表。这个参数不是“强制硬解”，而是“优先尝试硬件解码”：硬件设备或驱动不可用时仍自动使用软件解码，画质和感知语义不变。前端参数面板以中文显示为“硬件视频解码”。

2026-07-03 又做了一次更小的 QSV 探针：根据 `/sys/class/drm/*/dev` 临时创建 `/dev/dri/card0` 和 `/dev/dri/renderD128` 后，用 PyAV 生成 64x64 的 H.264 小片段并分别用 `h264_qsv`、`h264_v4l2m2m`、`h264` 解码。结果是 `h264_qsv` 在 `avcodec_send_packet()` 阶段失败，`h264_v4l2m2m` 在 `avcodec_open2()` 阶段失败，软件 `h264` 成功。这说明当前 NAS 不只是缺 `/dev/dri` 节点，还缺可工作的 QSV/V4L2 解码运行时组合。因此代码进一步改为：没有 `/dev/dri` 时直接跳过 QSV，没有 `/dev/video*` 时跳过 v4l2m2m，避免每次摄像头启动都先走一次注定失败的硬解路径。

## 第二轮：保留 80% 服务质量

第二轮允许改变工作流，目标是用明显更低硬件占用换取可接受的感知质量。

推荐方向：

1. 先用传感器或事件触发摄像头  
   门磁、人体传感器、设备状态变化先做粗触发，摄像头只在有必要时进入高成本链路。

2. Omni 输入从视频改成关键帧组  
   把一段视频压缩成少量关键图片或拼图，牺牲一部分时间连续性，显著减少编码和上传压力。

3. Identity 分层降级  
   平时只做轻量跟踪，重要场景再做身份确认；陌生人或规则命中时再提高识别强度。

4. Gate 先低分辨率粗筛，再高分辨率复核  
   大多数静止窗口在低成本阶段就丢弃，只有疑似变化才进入更精细判断。

5. 工作流限流  
   多摄像头时做轮询和优先级，而不是所有摄像头同频率持续进入完整链路。

## NAS 实测方法

每轮优化都必须在 NAS 上跑，不用浏览器堆窗口，不开多余 App，不写入包含密钥或私密日志的报告。

推荐步骤：

1. 记录测试配置  
   摄像头数量、拉流质量、采集间隔、输入 FPS、Omni FPS、身份识别模式、缓存策略。

2. 运行固定时长  
   至少覆盖空场景、轻微移动、有人经过、规则触发四类窗口。

3. 每 30 秒采样  
   采样性能预算、引擎状态、阶段耗时和内存，避免长时间无反馈的远程命令。

4. 判断准出  
   Miloco CPU 峰值低于宿主总 CPU 50%；Miloco RSS 峰值低于宿主总内存 50%；引擎仍可用；摄像头感知、身份识别和 Omni 能力符合本轮质量目标。

5. 汇总证据  
   只记录必要指标和结论，不保存 API Key、token、账号授权 payload 或私密日志。

## 迭代记录

| 轮次 | 改动 | 本地验证 | NAS 验证 | 结论 |
| --- | --- | --- | --- | --- |
| 第一轮-准备 | 暴露拉流质量、释放禁用摄像头、Gate 流式比较 | `pytest backend/miloco/tests/perception/engine/gate/test_visual_gate.py` 通过 | 待实测 | 目标是先降低入口解码与 Gate 压力 |
| 第一轮-内存 | `keep` 模式下已处理窗口只保留最近一个 | `pytest backend/miloco/tests/perception/test_stream_buffer_overflow.py` 通过 | 部署前 2 分钟采样：CPU 峰值 95.0% / 预算 200%，RSS 峰值 5015.6MB / 预算 3905.5MB，内存持续超限；`identity_ms=0`、`omni_ms=0` | 目标是释放历史解码帧，降低 RSS 峰值 |
| 第一轮-内存 | 周期结束后调用 `malloc_trim`（glibc 原生堆归还，帮助 NumPy/OpenCV 释放后把页还给系统） | `pytest backend/miloco/tests/perception/test_latency_rtf.py` 通过 | 2 分钟采样：CPU 峰值 271.8% / 预算 200%，RSS 峰值 4541.5MB / 预算 3905.5MB；初始 RSS 会降，但周期内峰值仍超 | 只解决“释放后归还系统”，不能解决“窗口内原始大图太多”的峰值 |
| 第一轮-内存 | 解码帧进入长窗口缓存前等比缩到身份识别有效上限（默认 1280x720）；低于上限的帧不复制 | `pytest ...test_camera_adapter_decode_latency.py ...test_latency_rtf.py ...test_stream_buffer_overflow.py ...test_visual_gate.py` 54 passed；ruff 通过 | 4 分钟采样：CPU 峰值 328.4% / 预算 200%，RSS 峰值 2457.7MB / 预算 3905.5MB；`gate_video_ms` 从旧样本 7-15s 降到约 2.1-2.4s | RAM 首次达标；CPU 仍超，说明剩余瓶颈主要不在内存缓存，而在持续拉流/解码与少量 Gate |
| 第一轮-CPU | 创建摄像头实例时关闭未使用的音频流（当前仓库摄像头音频不参与感知，关闭不影响现有视频/身份/Omni 能力） | 同上 54 passed；ruff 通过 | 4 分钟采样：CPU 峰值 357.9%（含启动窗口），稳态约 213-264% / 预算 200%；RSS 峰值 2488.5MB / 预算 3905.5MB；最新 trace 中 `decode_ms` 约 1.17-1.33s、`gate_video_ms` 约 1.8-2.0s、`omni_ms` 为云端等待 | RAM 稳定达标；CPU 有改善但仍未达标。第一轮下一步必须继续处理拉流/解码层，或进入第二轮接受 LOW 质量/更低 FPS/更少 Gate 抽检 |
| 第一轮-CPU A/B | 仅把 `MILOCO_CAMERA__FRAME_INTERVAL` 改为 5000ms，不改代码 | 无代码改动 | 4 分钟采样：新 trace 仍有 367-453 帧/60s；CPU 峰值 317.8%、平均 267.5%；RSS 峰值 2457.1MB | 证明旧代码中 `frame_interval` 没有节流 BGR 感知帧。源码对应：`MIoTMediaDecoder` 只用该参数节流 JPEG 预览，`decode_video_frame` 路径标注为 no rate limiting |
| 第一轮-CPU | `MIoTMediaDecoder` 对 BGR 帧回调也应用 `frame_interval`；仍解码每个 H.264/H.265 包以保持参考帧有效，只跳过间隔内的 BGR 转换和下游感知 | `pytest backend/miot/tests/test_units.py backend/miloco/tests/perception/test_camera_adapter_decode_latency.py backend/miloco/tests/perception/test_latency_rtf.py backend/miloco/tests/perception/test_stream_buffer_overflow.py backend/miloco/tests/perception/engine/gate/test_visual_gate.py -q`：91 passed；ruff 通过 | 5000ms 验证：新窗口降到 12 帧/60s，稳定期 CPU 峰值 115.6%；1000ms 默认质量复验：新窗口 52-58 帧/60s，运行期 CPU 约 200.2-210.8%，仍擦线超预算 | 证明节流修复有效，但默认质量下还需要继续压非跳过窗口和 Omni 上传前编码峰值 |
| 第一轮-CPU | Omni 上传 mp4 编码使用 `ultrafast/zerolatency` H.264 参数；不改上传帧数、分辨率、内容，只降低编码器计算量 | `pytest backend/miloco/tests/perception/engine/omni/test_prompt_builder.py backend/miloco/tests/perception/engine/test_pipeline.py backend/miot/tests/test_units.py ... -q`：243 passed；ruff 通过；本地 `_encode_video_mp4` 可生成 payload | NAS 默认 1000ms 复验：热补丁后非跳过 Omni 窗口 CPU 约 173-176%，跳过窗口稳定期 CPU 峰值 164.0%，RSS 峰值 809.3MB（稳定跳过期 689.1MB）；窗口 52-58 帧/60s | 单路桌面摄像头默认采样质量下，运行期 CPU/RAM 已低于预算；启动后旧窗口/启动期仍可出现 300%+ 尖峰，需要单独处理或在验收口径中排除启动阶段 |
| 第一轮-观测 | 资源监控延后并降频采集内存明细；运行期每分钟仍更新 CPU/RSS，重型 `smaps`/Python heap 明细默认 120 秒后开始、300 秒一次 | `pytest backend/miloco/tests/node_monitor/test_resource_monitor.py -q`：19 passed；`ruff check backend/miloco/src/miloco/node_monitor/resource_monitor.py backend/miloco/tests/node_monitor/test_resource_monitor.py` 通过 | NAS 默认 1000ms、一路桌面摄像头、7 分钟只读采样：CPU 峰值 172.4%（4 核宿主约 43.1%），平均 166.2%；RSS 峰值 694.0MB；覆盖 8 个 trace，其中 1 个 Omni 窗口 `omni_ms=33492.9` | 运行期观测链路不再制造明显超预算尖峰；单路默认质量在含 Omni 调用窗口下仍低于 CPU/RAM 50% 预算 |
| 第一轮-码流复用准备 | 新增原始压缩视频包的 I 帧对齐切片模块；后续 remux 必须从 I 帧开始，否则 P 帧缺少参考画面可能无法解码 | `pytest backend/miloco/tests/perception/test_encoded_video.py -q`：4 passed；`ruff check backend/miloco/src/miloco/perception/encoded_video.py backend/miloco/tests/perception/test_encoded_video.py` 通过 | 待接入 raw_video 旁路后上 NAS 复验 | 为减少 Omni 上传前 BGR → MP4 重新编码做前置保障；当前只是可测试基础件，尚未改变运行期资源 |
| 第一轮-码流复用准备 | MIoT SDK 增加 raw video packet 多订阅，感知采集侧保存 H.264/H.265 原始包并按窗口附到 `DeviceSnapshot.encoded_video`；性能 trace 记录 `encoded_video_packets` | `pytest backend/miloco/tests/perception/test_camera_adapter_decode_latency.py backend/miloco/tests/perception/test_encoded_video.py backend/miloco/tests/perception/test_collector_pack_aggregates.py backend/miot/tests/test_camera.py::test_raw_video_packet_multi_reg_coexists_with_legacy_raw_video -q`：33 passed；ruff 通过 | 待安全部署后复验；上轮 compose 热补丁传输方式触发容器启动失败，已恢复旧 compose，未把失败热补丁当作运行期证据 | 现在具备“同一次拉流资产可被后续上传链路复用”的代码基础；下一步是实现 PyAV/FFmpeg remux，并在 NAS 上验证 Omni 上传前编码 CPU 是否下降 |
| 第一轮-CPU | Omni 上传优先 remux 原始 H.264/H.265 包；无音频且 remux 成功时跳过 BGR → H.264 重新编码，失败自动回退旧路径 | `pytest backend/miloco/tests/perception/test_encoded_video.py backend/miloco/tests/perception/engine/omni/test_prompt_builder.py backend/miloco/tests/perception/engine/test_pipeline.py backend/miloco/tests/perception/test_camera_adapter_decode_latency.py backend/miloco/tests/perception/test_collector_pack_aggregates.py -q`：188 passed；ruff 通过 | 待 NAS 复验 | 这是第一轮“不降低质量”的真正 CPU 优化点：同样画面内容优先 streamcopy/remux，不重新压缩；仍需 NAS 上测 Omni 触发窗口 CPU 峰值 |
| 第一轮-CPU | raw packet 关键帧识别改为解析 H.264/H.265 NAL（视频压缩包里的小单元），不再只信 SDK 的 `frame_type`；trace 增加 raw 包、raw 关键帧、窗口 raw 包诊断 | `pytest backend/miloco/tests/perception/test_encoded_video.py backend/miloco/tests/perception/test_camera_adapter_decode_latency.py backend/miloco/tests/perception/test_collector_pack_aggregates.py backend/miloco/tests/perception/engine/omni/test_prompt_builder.py -q`：136 passed；`pytest backend/miloco/tests/perception/engine/omni/test_prompt_builder.py backend/miloco/tests/perception/test_encoded_video.py -q`：107 passed；ruff 通过 | NAS 一路桌面摄像头热补丁后：健康接口 `ok`；Miloco 约 117% CPU、RSS 约 624-647MB；camera raw_video 约 15.22fps、decode_video 约 0.98fps；最近 trace 中 raw 关键帧从 0 变为 25/40/55/68，`encoded_video_packets` 出现 900/899/956/951 等；实际 Omni 窗口 `omni_ms` 约 31.6s，CPU/RAM 仍低于 4 核/7.8GB 宿主 50% 预算 | 证明“同一次拉流资产”已经能进入上传候选窗口，避免了因 SDK 未标 I 帧而永远退回再编码；INFO 级 remux 日志未落盘，仍需下一次补更强的运行期 remux 成功指标 |
| 第一轮-观测 | Omni 视频构造结果写入 trace timing：`omni_video_*_remux_success`、`*_remux_fallback`、`*_reencode`、`*_input_packets`、`*_output_bytes`；字段全是数字，便于性能页做饼图/柱状图 | `pytest backend/miloco/tests/perception/engine/omni/test_prompt_builder.py backend/miloco/tests/perception/engine/test_pipeline.py backend/miloco/tests/perception/test_encoded_video.py -q`：167 passed；ruff 通过 | NAS 热补丁后服务健康；自然运行约 9 分钟未触发新的 Omni 上传窗口，最新窗口均为 Gate 跳过；Miloco CPU 约 115-125%，RSS 约 536-634MB；trace 继续显示 `encoded_video_packets` 约 899-957、raw 关键帧约 69 | 结构化指标已可用，但本轮静止场景没有新 Omni 窗口，因此还不能宣称真实上传已 remux 成功；需要下一次有人/画面变化触发 Omni 后查询这些字段 |
| 第一轮-CPU | 主动查询路径补齐 raw 包窗口选择，并在 Omni 失败时保留视频构造统计 | `pytest backend/miloco/tests/perception/test_camera_adapter_decode_latency.py backend/miloco/tests/perception/engine/test_pipeline.py backend/miloco/tests/perception/engine/omni/test_prompt_builder.py backend/miloco/tests/perception/test_encoded_video.py -q`：191 passed；ruff 通过 | NAS 热补丁后主动查询成功：`remux_success=1`、`reencode=0`、`input_packets=297`、`output_bytes=1372689`；回答正常返回；查询后 CPU 约 118.0%、RSS 约 464.6MB；camera `raw_video` 约 15.1fps、`decode_video` 约 0.97fps | 证明“同一次拉流资产”已经能复用到上传云端环节：上传前走 remux（转封装，不重新压缩画面），没有再编码；此前 `input_packets=0` 是主动查询 `drain=False` 未给 raw 包选择窗口导致 |
| 第一轮-CPU | remux MP4 时间戳改用原始视频包 `wall_ms`，避免把 15fps 摄像头包按 1fps/2fps 写成慢动作长视频 | `pytest backend/miloco/tests/perception/test_encoded_video.py backend/miloco/tests/perception/engine/omni/test_prompt_builder.py backend/miloco/tests/perception/engine/test_pipeline.py -q`：169 passed；ruff 通过 | NAS 热补丁后主动查询成功：`remux_success=1`、`reencode=0`、`input_packets=97`、`output_bytes=527647`；Omni 往返约 10.82s；资源监控更新后 CPU 约 125.0%、RSS 约 641.3MB；camera `raw_video` 约 15.18fps、`decode_video` 约 0.98fps | 修复前 remux 使用感知 FPS 造时间戳，可能把原始码流拉成长慢动作，增加云端处理/超时风险；修复后仍不再编码，但视频时间轴按真实采集时间播放 |
| 第一轮-CPU/IO | remux 从磁盘临时文件改为内存流（`BytesIO`），避免每次 Omni 上传前写 raw 临时文件和 mp4 临时文件 | `pytest backend/miloco/tests/perception/test_encoded_video.py backend/miloco/tests/perception/engine/omni/test_prompt_builder.py backend/miloco/tests/perception/engine/test_pipeline.py -q`：169 passed；ruff 通过 | NAS 热补丁后主动查询成功：`remux_success=1`、`reencode=0`、`input_packets=168`、`output_bytes=814536`；资源监控更新后 CPU 约 124.7%、RSS 约 608.9MB；camera `raw_video` 约 15.05fps、`decode_video` 约 0.97fps | 不改变画面内容、不重新编码，只减少 NAS 磁盘 I/O 和临时文件风险；适合低配 NAS 的长时间运行稳定性 |
| 第一轮-质量保护 | H.265 remux 暂时禁用，保留 H.264 remux；H.265 继续走 BGR 再编码兜底 | `pytest backend/miloco/tests/perception/test_encoded_video.py backend/miloco/tests/perception/engine/omni/test_prompt_builder.py backend/miloco/tests/perception/engine/test_pipeline.py -q`：171 passed；ruff 通过 | NAS 长窗口 H.265 remux 曾达到 `remux_success=1`、`reencode=0`，但 Omni 返回空答案；禁用 H.265 remux 后主动查询恢复答案：`answer='没有。'`，`reencode=1`，CPU 约 131.6%、RSS 约 704.7MB | 第一轮要求质量不打折；H.265 remux 虽能省 CPU，但当前会导致 Omni 空答案，必须先保守回退。后续可单独研究 H.265→Omni 兼容或低成本转码 |
| 第一轮-观测 | 视频构造统计增加 `h265_remux_skipped` 数字字段，解释 H.265 为什么仍走再编码 | `pytest backend/miloco/tests/perception/engine/omni/test_prompt_builder.py backend/miloco/tests/perception/engine/test_pipeline.py backend/miloco/tests/perception/test_encoded_video.py -q`：172 passed；ruff 通过 | NAS 主动查询：`h265_remux_skipped=1`、`reencode=1`、`answer='没有。'`；CPU 约 113.5%、RSS 约 513.2MB | 性能页/Agent 诊断可直接说明“为保证 Omni 正常回答，H.265 当前跳过 remux”，避免用户只看到再编码和 CPU 波动却不知道原因 |
| 第一轮-内存/拷贝 | H.265 既然因质量保护不参与 remux，采集侧只保留 H.265 原始包 metadata（codec、时间戳、关键帧、序号），不再把 payload bytes 长期放进 4096 包队列；H.264 payload 仍完整保留给 remux | `pytest tests/perception/test_camera_adapter_decode_latency.py tests/perception/test_collector_pack_aggregates.py tests/perception/test_encoded_video.py tests/perception/engine/omni/test_prompt_builder.py -q`：142 passed；定向 ruff 通过 | NAS 热补丁后 `/health` 为 ok；新 trace `1783046798240` 显示 `encoded_video_packets=1233`、`encoded_video_payload_bytes=0`、`h265_remux_skipped=1`、`reencode=1`、`raw_encoded_video_window_packets=1200`；Miloco 进程 RSS 约 332.7MB，无 `/tmp/codex-*` 残留 | 不改变画面、不改变 Omni 输入结果，只移除当前 H.265 路径里不会被使用的大块原始 payload，减少常驻内存和窗口传递拷贝；H.265 仍按质量保护走再编码 |
| 第一轮-CPU/拷贝 | H.265 metadata 路径进一步避免 NAL 扫描；只有 H.264 remux 路径继续解析 payload 判断 I 帧 | `pytest tests/perception/test_camera_adapter_decode_latency.py tests/perception/test_collector_pack_aggregates.py tests/perception/test_encoded_video.py tests/perception/engine/omni/test_prompt_builder.py -q`：144 passed；定向 ruff 通过 | NAS 微验证：构造 H.265 与 H.264 raw packet 后，扫描函数调用列表只有 `h264`；H.265 `payload_len=0`、`is_keyframe=false`，H.264 `payload_len=7`、`is_keyframe=true`；`/health` 为 ok，无 `/tmp/codex-*` 残留 | 当前 H.265 不会 remux，所以不再为它解析压缩包内容；保留 H.264 的安全关键帧识别，避免破坏真正省 CPU 的 remux 路径 |
| 第一轮-观测 | H.265 remux skip 后做 6 分钟只读稳态采样，不额外触发浏览器、主动查询或 Omni 调用 | NAS 实机采样 13 次，每 30 秒一次 | 一路桌面摄像头：CPU 峰值 126.5%、平均 115.9%；RSS 峰值 719.9MB、平均 634.0MB；raw_video 平均 15.12fps、decode_video 平均 0.97fps；RTF 峰值 0.52 | 静态运行期已低于 4 核宿主 200% CPU 预算和约 3.8GB RAM 预算；后续峰值风险主要来自触发 Omni 上传时 H.265 退回 BGR 再编码，而不是常规拉流空转 |
| 第二轮-拉流质量 | 将 NAS 运行配置显式设为 `camera.video_quality=LOW`，从源头拉低清流，降低解码、缩图、Gate 和再编码输入压力 | `uv run pytest miloco/tests/admin/test_performance_tuning.py miloco/tests/test_miot_filter_and_cameras.py -q`：79 passed；`uv run ruff check ...` 通过 | NAS 热补丁后 `/api/admin/performance-config` 显示 `camera.video_quality=LOW`；一路桌面摄像头 6 分钟只读采样：CPU 峰值 18.5%、平均 14.7%；RSS 峰值 429.5MB、平均 424.3MB；raw_video 平均 15.08fps、decode_video 平均 0.97fps。主动问答两次均正常回答 `没有。`，H.265 仍走 `h265_remux_skipped=1`、`reencode=1`；第二次问答期间容器内 1 秒 `ps` 采样 Miloco 进程 CPU 峰值约 17.5%、RSS 峰值约 447.6MB | LOW 会牺牲画面细节，属于第二轮“服务质量约 80%”方案；但对单路低配 NAS 的运行期和主动问答峰值非常有效，当前远低于 4 核宿主 200% CPU / 约 3.8GB RAM 预算 |
| 第二轮-配置生效 | 清理 NAS compose 里的 `MILOCO_CAMERA__FRAME_INTERVAL=1000` 覆盖，并让 supervisor 启动后端时 `env -u MILOCO_CAMERA__FRAME_INTERVAL`，使 `config.json` / 性能页应用值成为真实运行值 | NAS 运行期验证：`/api/admin/performance-config` 从 `camera.frame_interval=1000` 变为 `5000`；`/api/monitor/nodes` 的 `decode_video` 从约 0.97fps 降为 0.20fps | 3 分钟短采样：CPU 峰值 16.6%、平均 13.6%；RSS 峰值 327.4MB、平均 323.9MB；raw_video 平均 15.12fps、decode_video 平均 0.20fps；RTF 峰值 0.422 | 修复了“配置写了但运行值不变”的真实根因；后续前端应用 `camera.frame_interval` 才会真正影响拉流解码后的取帧频率 |
| 运维固化 | `performance-config` 返回每个参数的 `env_override` 状态；前端对被环境变量覆盖的参数显示“外部锁定”，直接应用接口也拒绝这类参数 | `uv run pytest miloco/tests/admin/test_performance_tuning.py -q`：13 passed；`uv run ruff check ...` 通过；`pnpm run typecheck` 通过 | 基于上一行 NAS 根因固化到仓库，未再次改动 NAS 运行态 | 避免 `MILOCO_CAMERA__FRAME_INTERVAL` 这类部署环境变量再次让用户误以为面板应用无效；如果 Docker/启动脚本仍锁定参数，UI 会直接说明 |
| 观测-资源归因 | 性能页阶段耗时从纯表格增强为“平均占比饼图 + P95 峰值柱状图 + 中文阶段解释”，直接回答“谁带崩 CPU/耗时” | `pnpm run typecheck` 通过；`pnpm run build` 通过 | 只读验证 `/api/stats?metric=stage_percentiles&window=1h`：`identity_ms` P95 约 66160ms、`omni_ms` P95 约 54124ms、`decode_ms` P95 约 1974ms、`gate_ms` P95 约 1412ms，样本数据可支撑图表；随后热部署 Web 静态资源到 NAS，HTTP 首页已引用 `assets/index-D5PcsUEp.js` / `assets/index-C6A6D_Za.css`，新 JS 内含“谁在吃资源、峰值压力、拉流解码、画面变化检测、身份识别”等文案 | 这是诊断可视化，不改变运行负载。注意 `omni_ms` 主要是云端/网络等待，不等于本地 CPU；本地 CPU 优先看 `decode/gate/identity` |
| 观测-上传视频 | 新增 `/api/stats?metric=omni_video_summary` 和性能页“云端上传视频”卡片，显示最近 Omni 上传前是 remux（复用原始视频包）还是 reencode（重新编码），并显示 P95 上传体积、H.265 质量兜底次数；随后补充 `raw_window_packets/raw_keyframes/raw_window_h264_packets/raw_window_h265_packets`，区分“原始包不存在”“H.264 缺关键帧”和“H.265 质量保护” | `uv run pytest tests/perception/test_collector_pack_aggregates.py tests/perception/test_camera_adapter_decode_latency.py tests/observability/test_processor_publish_trace.py -q`：46 passed；`env MILOCO_SERVER__TOKEN= uv run pytest tests/observability/test_stats.py -q`：17 passed；定向 ruff 通过；`pnpm run typecheck` 与 `pnpm run build` 通过 | NAS 热补丁后按正确 supervisor 进程名 `miloco-backend` 重启，`/health` 为 ok；最新 trace：`raw_encoded_video_window_packets=1200`、`raw_encoded_video_window_h264_packets=0`、`raw_encoded_video_window_h265_packets=1200`、`raw_encoded_video_keyframes=0`、`raw_encoded_video_h265_packets=4096`；同一 trace 的 Omni 上传统计：`reencode=1`、`remux_success=0`、`input_packets=0`、`output_bytes=2139687`；当前进程采样约 `23.0% CPU / 324608 RSS`；清理本地 HTTP 服务、传输包和 NAS `/tmp/codex-*` | 这不直接降 CPU，但把“为什么配了 LLM API 本地仍吃 CPU”变成可见数据：当前这一路摄像头原始包已经在同一次拉流里存在，但全是 H.265，不是 H.264；现在退回重编码不是因为又拉了一次流，而是 H.265 质量保护。下一步第一轮无损优化应优先验证是否能从 SDK/设备侧请求 H.264 子码流，或安全启用 H.265 直传/封装给 Omni；如果不能，才考虑第二轮降低上传质量/帧率 |
| 第一轮-实验 | 增加 `perception.engine.omni.allow_h265_remux` 实验开关；默认仍为 `false`，打开后 H.265 原始包可像 H.264 一样参与 remux，并保留失败回退到 BGR 再编码的质量兜底 | `pytest tests/perception/test_camera_adapter_decode_latency.py tests/perception/test_encoded_video.py tests/perception/engine/omni/test_prompt_builder.py -q`：139 passed；定向 ruff 通过 | NAS 先因 schema 未声明 `OmniConfig.allow_h265_remux` 导致后端不健康，补齐配置字段后 `/health` 恢复；打开 `allow_h265_remux=true` 后主动查询成功返回画面描述；视频构造统计：`remux_success=1`、`reencode=0`、`input_packets=432`、`output_bytes=462034`、`h265_remux_skipped=0`；查询后进程约 `35.4% CPU / 331MB RSS`，后续约 `26.7% CPU / 336MB RSS`；已清理 NAS `/tmp/codex-miloco-h265-*` | 证明至少在当前一路桌面摄像头的短主动查询窗口里，H.265 原始包可以复用到云端上传并避免再编码。默认仍不全量开启，原因是长窗口曾出现 Omni 空答案；下一步需要做更长窗口、运动画面和不同光照复验，再决定是否从实验开关升为常规策略 |
| 第一轮-运维化 | 把 `perception.engine.omni.allow_h265_remux` 纳入性能配置 API 和前端参数文案，安全模式明确设为 `false` | `uv run pytest tests/admin/test_performance_tuning.py tests/perception/test_camera_adapter_decode_latency.py tests/perception/engine/omni/test_prompt_builder.py -q`：139 passed；定向 ruff 通过；`pnpm run typecheck` 通过 | NAS 热补丁 `performance_tuning.py` 和 `settings.yaml` 后重启 `miloco-backend`，`/health` 为 ok；`/api/admin/performance-config` 返回该参数，当前值 `true`，`env_override.active=false`；进程约 `60.8% CPU / 313MB RSS`；本地传输文件和 NAS `/tmp/codex-*` 已清理 | 之后可在性能参数闭环中打开/关闭 H.265 直传实验，不再靠手改 `config.json`。这降低了后续 NAS A/B 测试风险；低配安全模式仍会关闭该实验项，优先保证回答稳定 |
| 第二轮-H.265 主动查询 | 在当前低配运行态 `LOW + frame_interval=5000 + allow_h265_remux=true` 下触发一次主动视觉查询，同时每秒采样 Miloco 进程 CPU/RSS | 无代码变更 | 查询 15.83 秒返回正常中文画面描述；16 笔 1 秒采样：CPU 峰值 21.1%、平均 21.0%，RSS 峰值 342.1MB；视频构造统计：`remux_success=1`、`reencode=0`、`input_packets=1107`、`output_bytes=618002`、`h265_remux_skipped=0`；测试脚本、传输包、本机 HTTP 服务和 NAS `/tmp/codex-*` 均已清理 | 在第二轮低配质量下，H.265 直传显著避免了上传前再编码，且主动查询峰值远低于 4 核宿主 200% CPU / 约 3.8GB RAM 预算。它仍不能替代默认高质量、长窗口或移动场景验收 |
| 第一轮-质量保护 | 主动查询路径增加 H.265 remux 空回答自动回退：如果 H.265 直传已成功但 Omni 解析结果为空，则临时去掉原始包，复用同一窗口的解码帧走 BGR 再编码再问一次 | `uv run pytest tests/perception/engine/test_pipeline.py::test_query_empty_h265_remux_retries_with_reencode tests/perception/engine/test_pipeline.py::test_query_omni_error_preserves_video_encode_stats -q`：2 passed；`uv run pytest ...test_prompt_builder.py` 定向通过；ruff 通过 | NAS 热补丁 `pipeline.py` 并重启后 `/health` 恢复 ok；当前低配态主动查询 21.64 秒返回正常中文画面描述；22 笔 1 秒采样：CPU 峰值 26.7%，RSS 峰值 336.7MB；统计仍是 `remux_success=1`、`reencode=0`、`input_packets=1147`、`output_bytes=1476941`，说明正常 H.265 直传路径未被破坏；传输服务和 `/tmp/codex-*` 已清理 | 这是第一轮“不降低质量”的护栏：H.265 直传成功时省 CPU；若再遇到空回答，则自动退回旧的再编码路径，优先保证用户能拿到答案。下一步仍要用长窗口/运动场景专门触发一次空回答，验证实际回退分支 |
| 第二轮-静态运行复验 | 在已生效的低配参数下做 3 分钟只读采样：`camera.video_quality=LOW`、`camera.frame_interval=5000`、`camera.max_cache_images=2`、`input.fps=1`、`omni_fps=1`、`period_sec=60`、`tracking_service_mode=mock`、`identity_engine.enabled=false`，且这些参数均未被环境变量锁定 | 无代码变更 | 7 笔采样，每 30 秒一次：CPU 峰值 13.5%、平均 12.4%，预算 200%；RSS 峰值 339.0MB、平均 337.3MB，预算 3905.5MB；没有 CPU/RAM 超预算；阶段历史 P95：`decode_ms` 约 1973ms、`gate_ms` 约 1411ms、`identity_ms` 约 66160ms、`omni_ms` 约 54124ms | 一路桌面摄像头静态运行已经非常轻，远低于 CPU/RAM 50% 预算；但这属于第二轮 80% 质量低配配置，不证明多路摄像头、有人移动、身份识别开启或 Omni 触发峰值已全部达标 |
| 第二轮-主动查询复验 | 同一路低配配置下触发一次主动视觉查询，问题为“现在画面里有什么？请用一句话回答。”，同时每秒采样 CPU/RAM | 无代码变更 | 查询约 29.7 秒返回正常答案；29 笔采样 CPU 峰值/平均均为 12.0%，RSS 峰值/平均均为 336.6MB，无 CPU/RAM 超预算；视频构造统计：`h265_remux_skipped=1`、`remux_success=0`、`remux_fallback=1`、`reencode=1`、`input_packets=886`、`output_bytes=1764429` | 证明在 LOW + 5000ms + 1 FPS + 身份关闭的低配配置下，即使 H.265 因质量保护退回再编码并触发 Omni，当前一路摄像头峰值仍远低于预算；仍不能替代默认质量、多路摄像头或身份识别开启场景 |
| 第一轮-默认质量反证 | 把 NAS 恢复到默认质量参数做短 A/B：`video_quality=HIGH`、`frame_interval=1000`、`max_cache_images=6`、`window_size=4`、`max_windows=3`、`input.fps=3`、`period_sec=4`、`tracking_service_mode=deep_sort`、`identity_engine.enabled=true` | 无代码变更 | 有效样本 19 笔；CPU 峰值 276.6%、平均 116.5%，超过 4 核宿主 200% 预算；RSS 峰值 466.8MB、平均 432.2MB，低于内存预算；阶段历史 P95：`identity_ms` 约 66088.6ms、`omni_ms` 约 54021.7ms、`decode_ms` 约 1972.5ms、`gate_ms` 约 1409.9ms | 默认高质量 + 深度身份识别在一路桌面摄像头上仍可能冲破 CPU 预算；低配 NAS 的稳定方案不能只靠第一轮无损优化，还必须保留第二轮 LOW/降频/身份降级预设 |
| 运维固化 | `miloco-cli service start/restart` 生成 supervisor 配置时主动 `env -u` 性能页可调的 `MILOCO_*` 环境变量，避免旧 compose/shell 环境在每次重启后重新覆盖 `config.json` | `cd cli && uv run pytest tests/test_commands.py -q`：141 passed；定向 `ruff check` 通过。全量 backend ruff 仍有 3 个既有测试 import 排序问题，和本改动无关 | NAS 现场先热修 `/data/miloco/supervisord.conf` 为 `env -u MILOCO_CAMERA__FRAME_INTERVAL ... python -m miloco.main` 并重启；随后 `/health` 恢复，进程环境不再含该变量，`/api/admin/performance-config` 显示 `camera.frame_interval=5000` | 解决“低配配置已写入但重启后又变回 1000ms”的反复根因；后续 CLI 管理服务不会再次生成会继承旧性能环境变量的 supervisor 命令 |
| 第一轮-CPU | ONNX Runtime session 线程自适应：`MILOCO_ORT_NUM_THREADS` 可覆盖；默认在 4 核及以下机器把 intra-op 收敛到 2/1，并把 inter-op 固定为 1，避免 detector 与 ReID 多 session 线程池互相抢占 | `uv run pytest miloco/tests/perception/test_ort_utils.py -q`：3 passed；`uv run pytest miloco/tests/perception/engine/test_get_reid_extractor_fallback.py miloco/tests/perception/engine/identity/test_deep_sort_v12.py::TestDeepSortConfigDC -q`：5 passed；定向 ruff 通过 | NAS 热补丁 `ort_utils.py` 并重启后，临时恢复默认高质量/deep_sort normal 配置做 90 秒采样：18 笔，每 5 秒一次，CPU 峰值 150.0%、平均 143.7%，RSS 峰值 558.8MB、平均 500.1MB；随后恢复 LOW 低配配置、重启，`/health` 为 ok，临时脚本已删除 | 不改变模型、画质、阈值和识别语义，只降低 ONNX 推理并行抢占。短采样显示默认质量一路摄像头 CPU 峰值从上轮 276.6% 降到 150.0%，低于 4 核宿主 200% 预算；仍需更长时间、有人移动和多路摄像头复验 |
| 第一轮-长采样复验 | 继续使用 ORT 线程收敛后的默认高质量/deep_sort normal 配置，只读采样 5 分钟，不开浏览器、不触发主动查询 | 无代码变更 | 60 笔采样，每 5 秒一次：CPU 峰值 195.0%、平均 151.7%，RSS 峰值 609.2MB、平均 505.6MB；低于 4 核宿主 200% CPU 预算和约 3905.5MB RAM 预算；测试后恢复 LOW 低配配置并重启，`/health` 为 ok，临时脚本已删除 | 5 分钟一路默认质量静态运行仍达标，但 CPU 峰值已贴近预算线，只证明当前桌面摄像头/静态场景；有人移动、规则触发、Omni 上传、更多摄像头仍必须继续复验 |
| 第一轮-默认 fast 反证 | 把默认高质量配置中的 `deep_sort.mode` 从 `normal` 改为项目默认的 `fast`，`human_reid_skip_windows=4`，其它保持 HIGH/1000ms/3 FPS/4s 窗口，只读采样 5 分钟 | 无代码变更 | 60 笔采样，每 5 秒一次：CPU 峰值仍为 195.0%、平均 150.8%，RSS 峰值 627.1MB、平均 511.6MB；测试后恢复 LOW 低配配置并重启，`/health` 为 ok，临时脚本已删除 | 当前单路静态场景的峰值并没有因 fast 模式下降，说明峰值更可能来自检测、每窗首次 ReID、启动/窗口调度或非静止可复用阶段；不能把“切 fast”当成主要余量来源 |
| 第一轮-硬件解码准备 | 核实 NAS 硬件视频设备和 PyAV/FFmpeg codec，并给 NAS Docker 增加可选 `/dev/dri` 映射 override | `bash -n nas/docker/manage.sh` 通过 | NAS 只读核实：`/sys/class/drm` 有 `renderD128`，当前运行环境无 `/dev/dri`；PyAV codec 有 `h264_qsv`、`hevc_qsv`，无 `vaapi`；未重启 NAS 容器，未改变运行配置 | Intel Quick Sync 方向具备条件，但当前 Miloco 看不到设备；下一步如要无损降低拉流/解码 CPU，必须先让容器看到 `/dev/dri/renderD128`，再做独立硬解基准和代码接入 |
| 第一轮-硬件解码接入 | MIoT 解码器在 `enable_hw_accel` 开启时按 PyAV registry 优先尝试 QSV/v4l2m2m 硬件解码器，创建或解码失败自动回退软件解码 | `cd backend && uv run pytest miot/tests/test_units.py -q`：40 passed；`uv run ruff check miot/src/miot/decoder.py miot/tests/test_units.py` 通过 | NAS 热补丁 `miot/decoder.py` 并重启后 `/health` 为 ok；当前环境仍无 `/dev/dri`，所以应回退软件解码；LOW/5000ms/mock 低配短采样 6 笔：CPU 峰值 19.5%，RSS 峰值 368.4MB；清理传输 HTTP 服务、`/tmp/codex-miloco-*` 和热补丁备份文件 | 这是无损接入点：有硬件时才省解码 CPU，没有硬件时自动回退不改变质量。真正证明 QSV 降 CPU 还需要下一轮让容器看到 `/dev/dri/renderD128` 后做 HIGH/1000ms A/B |
| 第一轮-硬件解码配置链路 | 新增 `camera.enable_hw_accel` 配置、性能页参数、安全模式默认值和 supervisor 环境变量解锁；MIoT client 创建摄像头实例时传入该配置 | `cd backend/miloco && uv run pytest tests/admin/test_performance_tuning.py -q`：13 passed；`cd backend/miot && uv run pytest tests/test_units.py -q`：40 passed；`cd cli && uv run pytest tests/test_commands.py -q`：141 passed；定向 ruff 和 `web pnpm run typecheck` 通过 | NAS 热补丁 settings / performance_tuning / miot client / decoder 后重启，`get_settings().camera.enable_hw_accel=True`；`build_performance_config_payload()` 返回 `camera.enable_hw_accel` 且无 env lock；LOW/5000ms/mock 短采样 6 笔 CPU 峰值 24.8%、RSS 峰值约 356.3MB，`/health` 为 ok，无 `/tmp/codex-miloco-*` | 用户现在可以在性能配置闭环里看到并应用“硬件视频解码”。当前 NAS 仍没有 `/dev/dri` 暴露，所以这轮验证的是配置链路和软件回退稳定性；QSV 实际降 CPU 仍待设备映射后 A/B |
| 第一轮-硬件解码反证 | 临时创建 `/dev/dri/card0` 和 `/dev/dri/renderD128` 后做 PyAV 小片段硬解探针；随后清理设备节点恢复原状态 | `cd backend/miot && uv run pytest tests/test_units.py -q`：41 passed；`uv run ruff check miot/src/miot/decoder.py miot/tests/test_units.py` 通过 | NAS 探针：`h264_qsv` 创建成功但解码失败 `avcodec_send_packet()`，`h264_v4l2m2m` 打开失败，软件 `h264` 成功；清理 `/dev/dri` 和 `/tmp/codex-*` 后 `/health` 为 ok。热补丁“无设备时跳过硬解候选”后，LOW/5000ms/mock 稳定样本 CPU 约 19.6-21.1%，RSS 约 313MB | 当前 NAS 的硬解路径暂不可用，不应继续把“手工 mknod /dev/dri”当优化方案。下一步要么补齐 Intel Media/QSV 运行时并做离线探针成功后再接入，要么转向其它无损优化点 |

## 当前结论（2026-07-03 NAS 实测）

在一路桌面摄像头场景下，早期缩帧把 RAM 峰值从 4.5GB 级别压到 2.5GB 内，已经低于 7.8GB 宿主内存的 50% 预算。`gate_video_ms`（本地画面变化检测耗时）也从 7-15 秒级降到约 2 秒。

进一步 A/B 证明，旧版 `camera.frame_interval` 不会节流感知使用的 BGR 帧：即使设为 5000ms，60 秒窗口仍有 367-453 帧。原因是 SDK 的 `MIoTMediaDecoder` 只用 `frame_interval` 节流 JPEG 预览输出，BGR 回调路径没有节流。

修复 BGR 回调节流后，5000ms 低频配置可把窗口降到 12 帧/60s，但这只用于验证节流是否生效，不作为第一轮“不降低质量”的验收依据。将采样间隔恢复到默认 1000ms 后，新窗口稳定在 52-58 帧/60s。

默认 1000ms 下，单靠 BGR 节流仍有非跳过窗口在 200% CPU 预算边缘。继续把 Omni 上传 mp4 编码改成低 CPU 的 `ultrafast/zerolatency` 参数后，默认采样质量下的运行期采样达标：非跳过 Omni 窗口 CPU 约 173-176%，跳过窗口稳定期 CPU 峰值 164.0%，RSS 峰值 809.3MB，均低于 4 核宿主 200% CPU / 约 3905.5MB RAM 预算。

资源监控自身也可能成为压力来源。早期实现启动后会立即试探完整内存区域采样，后续每 60 秒跟随资源监控采一次 `smaps` 和 Python heap。低配 NAS 上这类遍历会和感知周期争 CPU。延后并降频重型内存明细后，默认 1000ms、一路桌面摄像头、7 分钟运行期复验中，CPU 峰值 172.4%（4 核宿主约 43.1%）、平均 166.2%，RSS 峰值 694.0MB；采样覆盖 8 个 trace，其中 1 个实际进入 Omni 调用，仍低于 CPU/RAM 50% 预算。

当前结论：单路桌面摄像头的静态运行期 CPU/RAM 已达成低配 NAS 预算，且使用默认 1000ms 采样间隔，不依赖 5000ms 降频。H.265 remux skip 后的 6 分钟只读复验中，CPU 峰值 126.5%、平均 115.9%，RSS 峰值 719.9MB、平均 634.0MB。仍未完成全目标，因为还需要在更长时段、更多摄像头、有人移动、规则触发、Identity 实际进入，以及 H.265 云端上传退回再编码的场景下复验最高峰值。

第二轮低清拉流复验显示，`camera.video_quality=LOW` 是当前最直接的降载手段：同样一路桌面摄像头、`MILOCO_CAMERA__FRAME_INTERVAL=1000` 仍由 compose 环境变量覆盖的前提下，6 分钟只读采样 CPU 峰值只有 18.5%、平均 14.7%，RSS 峰值 429.5MB。主动视觉问答仍因 H.265 兼容性走再编码，但回答正常，容器内 1 秒进程采样 CPU 峰值约 17.5%、RSS 峰值约 447.6MB。

随后清理 NAS 当前 `/data/docker-compose.yaml` 中的 `MILOCO_CAMERA__FRAME_INTERVAL=1000`，并把 `/data/miloco/supervisord.conf` 的后端启动命令改为 `env -u MILOCO_CAMERA__FRAME_INTERVAL ... python -m miloco.main`，避免当前容器父环境继续覆盖用户配置。重启后 `/api/admin/performance-config` 显示 `camera.frame_interval=5000`，`decode_video` 降到 0.20fps。3 分钟短采样 CPU 峰值 16.6%、平均 13.6%，RSS 峰值 327.4MB、平均 323.9MB。这个修复解释并解决了此前“前端应用参数但待应用/运行值没变化”的核心原因。

在这组低配参数继续生效的状态下，2026-07-03 又做了一轮 3 分钟只读短采样：CPU 峰值 13.5%、平均 12.4%，RSS 峰值 339.0MB、平均 337.3MB；预算分别是 200% CPU 和 3905.5MB RAM。采样时确认 `camera.video_quality=LOW`、`camera.frame_interval=5000`、`camera.max_cache_images=2`、`perception.engine.input.fps=1`、`omni_fps=1`、`period_sec=60`、`tracking_service_mode=mock`、`identity_engine.enabled=false`，且所有这些性能参数都没有被环境变量锁定。这说明一路静态低配运行已经有很大余量，但它仍是第二轮“约 80% 服务质量”方案，不可替代第一轮默认质量或多路/移动/身份识别触发场景的最终验收。

同一轮又触发了一次主动视觉查询，返回答案能正确描述电脑桌面且确认房间内无人。查询期间 29 秒每秒采样 CPU/RAM，CPU 峰值仍为 12.0%，RSS 峰值 336.6MB。视频构造统计显示当前摄像头仍是 H.265 路径：`h265_remux_skipped=1`、`reencode=1`、`input_packets=886`、`output_bytes=1764429`。也就是说，即使为了保证 Omni 正常回答而放弃 H.265 remux、走 BGR 再编码，当前低配配置下主动查询峰值仍远低于预算。

随后做了一轮默认质量反向 A/B：恢复 HIGH 拉流、1000ms 取帧、3 FPS、短窗口和 deep_sort 身份识别后，CPU 峰值升到 276.6%，超过 4 核宿主的 200% 预算；RSS 峰值 466.8MB，内存仍安全。这说明当前真正会把低配 NAS 带崩的是“高频输入 + 深度身份识别 + Omni 长等待窗口叠加”带来的 CPU 峰值，而不是 LLM API Key 是否配置。LLM API 只把理解放到云端；本地仍要完成拉流、解码、Gate、身份识别、视频构造和上传前准备。

针对这个默认质量 CPU 峰值，源码进一步收敛 ONNX Runtime 线程：低核 NAS 上 detector（目标检测模型）和 ReID（人体特征模型）不再各自用 4 个 intra-op 线程再配 4 个 inter-op 线程，而是 4 核机器默认 intra-op=2、inter-op=1。这里的 intra-op 指单个算子内部并行，inter-op 指多个算子之间并行；这只改变线程调度，不改变模型本身和识别输出。NAS 热补丁后，在同样 HIGH/1000ms/3 FPS/deep_sort normal 配置下做 90 秒短采样，CPU 峰值 150.0%、平均 143.7%，RSS 峰值 558.8MB，低于 4 核宿主 200% CPU 预算。测试后已恢复 LOW 低配配置并重启，健康接口恢复 `ok`。

进一步把同一默认质量配置延长到 5 分钟只读采样：60 笔、每 5 秒一次，CPU 峰值 195.0%、平均 151.7%，RSS 峰值 609.2MB、平均 505.6MB。这个结果仍低于 4 核宿主的 200% CPU 预算，但已经贴近预算线，说明第一轮无损优化在“单路静态桌面摄像头”上基本够用，却不能直接外推到多人移动、多路摄像头或规则频繁触发。采样结束后已恢复 LOW/5000ms/mock 身份识别的低配配置，并清理 `/tmp/codex-miloco-*` 临时文件。

同样默认高质量下，把 `deep_sort.mode` 改回项目默认的 `fast` 并复验 5 分钟，CPU 峰值仍为 195.0%、平均 150.8%，RSS 峰值 627.1MB。也就是说，当前静态单路场景里，fast 模式的静止 ReID 缓存没有明显降低峰值；后续第一轮优化应继续看检测模型调用、每窗首次 ReID、窗口启动/调度，或者更底层的硬件解码/硬件推理，而不是只依赖 deep_sort fast。

硬件解码方向已经补上代码入口：`enable_hw_accel` 开启时会优先尝试 PyAV 暴露的 QSV/v4l2m2m 解码器，失败回退软件解码。当前 NAS 热补丁复验只能证明“无硬件设备暴露时不会破坏现有低配运行”，不能证明“QSV 已降低 CPU”，因为 Miloco 进程仍看不到 `/dev/dri`。下一步必须通过 NAS Docker override 让容器内出现 `/dev/dri/renderD128`，然后用 HIGH/1000ms/deep_sort 配置做硬解开关 A/B。

配置层面，`camera.enable_hw_accel=true` 已进入性能页和低配安全模式。这个开关只表达“允许尝试硬件解码”，不会牺牲画质；硬件失败时仍回退软件解码。2026-07-03 NAS 热补丁后确认配置 payload 中该项存在，且没有被 `MILOCO_CAMERA__ENABLE_HW_ACCEL` 环境变量锁定。

但当前测试 NAS 的 QSV 硬解还不能作为第一轮有效优化项：即使临时补出 `/dev/dri` 设备节点，PyAV 的 `h264_qsv` 仍无法完成实际解码。已清理临时节点并恢复原状态。当前更稳妥的代码行为是“没有设备节点就不尝试硬解”，避免多一次失败和回退开销。若后续继续这条路线，需要先在 NAS/镜像层补齐 Intel Media Driver / QSV 运行时，并以独立 PyAV 小片段探针成功为准，再做 Miloco HIGH/1000ms A/B。

仓库侧已经把这个故障模式固化为产品行为：`GET /admin/performance-config` 会给每个性能参数返回 `env_override`，说明对应的 `MILOCO_*` 环境变量是否正在覆盖 `config.json`；前端会把这类参数标记为“外部锁定”，禁用输入，并提示需要先从 Docker/启动脚本移除变量。`POST /admin/performance-config/apply` 也会拒绝被外部锁定的参数，避免静默写入一个重启后仍不会生效的值。

还要注意另一类运维根因：只在 NAS 上手工修改 `/data/miloco/supervisord.conf` 不够，因为 `miloco-cli service restart` 会重新生成 supervisor 配置。若生成的新配置继续继承旧 compose/shell 里的 `MILOCO_CAMERA__FRAME_INTERVAL=1000`，性能页写入的 `camera.frame_interval=5000` 会在下一次后端重启后再次失效。仓库 CLI 已改为在托管服务启动命令前加 `/usr/bin/env -u ...`，清掉性能页可调参数对应的环境变量；显式前台运行仍保留环境变量语义，避免破坏开发者临时调试。

为了让非研发用户能看懂“到底谁吃资源”，性能页现在把阶段耗时表上方改成两个图：饼图按平均耗时显示占比，柱状图按 P95（95% 情况下不会超过的高位耗时）排序显示峰值压力。当前 NAS 一小时只读验证里，`identity_ms` 和 `omni_ms` 的 P95 最高，但含义不同：`identity_ms` 是本地身份识别与跟踪，可能消耗 CPU；`omni_ms` 多数是上传和等待云端模型，不应直接等同为本地 CPU。持续本地 CPU 的优先观察项仍是 `decode_ms`（拉流解码）、`gate_ms`（画面变化检测）和 `identity_ms`（身份识别）。

2026-07-03 已把这版 Web 静态资源热部署到 NAS 当前 Miloco 容器：备份文件为 `/data/miloco/static-backup-codex-20260703-082741.tar.gz`，替换后 `/` 返回的新资产为 `assets/index-D5PcsUEp.js`、`assets/vendor-BqyWff5t.js`、`assets/index-C6A6D_Za.css`。本轮只替换静态资源，不重启后端；NAS `/health` 保持 `ok`。部署时使用的临时 NAS 文件和本机 HTTP 传输服务已清理。

源码已接入摄像头原始码流 remux：无音频窗口会优先复用同一次拉流得到的 H.264/H.265 压缩包生成 MP4，减少 BGR 重新编码成 MP4 的 CPU 压力。2026-07-03 的 NAS 热补丁复验确认，真实摄像头流里的原始压缩包已经被保留下来，NAL 解析能识别关键帧，窗口里也已经出现 `encoded_video_packets`。后续主动查询复验进一步确认上传路径已实际 remux 成功：`remux_success=1`、`reencode=0`、`input_packets=297`、`output_bytes=1372689`，且 Omni 正常返回答案。

“为什么还会再编码”的判断口径如下：如果 `input_packets=0`，说明上传云端时没有拿到可复用的原始压缩视频包，只能把 BGR 图片帧重新压成 MP4，这就是 reencode（再编码，重新压缩画面，CPU 高）；如果 `remux_success=1` 且 `reencode=0`，说明复用了同一次拉流资产，只做 remux（转封装，只换 MP4 容器，不重新压缩画面，CPU 低）。本轮之前主动查询出现 `input_packets=0`，根因是 `drain=False` 的非破坏性读取只拿了解码帧，没有给 raw 包选择窗口；补齐窗口后，NAS 实测已经变为 `input_packets=297`。

用非研发口径描述，Miloco 现在不是“到上传云端时再拉一次流”。一次摄像头拉流会同时进入两条缓存：一条是 decoded frame（解码后的画面，BGR 图片数组），供 gate_video（画面变化检测）、身份识别和必要时的视频重新编码使用；另一条是 encoded packet（摄像头原始压缩视频包），供 Omni 上传前直接 remux 使用。拉流和解码仍不可避免，因为本地要看画面内容；但上传云端时优先复用 encoded packet，只有这条路不可用时才用 decoded frame 重新压成 MP4。

当前复用规则是：

1. H.264（常见摄像头压缩格式）窗口、没有音频、能找到关键帧时，走 remux（转封装，不重新压缩画面）。这是最省 CPU 的无损路径。
2. H.264 找不到关键帧、原始包缺失、混入不同 codec，或者 remux 失败时，回退 reencode（再编码，把解码后的画面重新压成 MP4）。这是质量兜底路径，CPU 更高。
3. H.265（HEVC，另一种压缩格式）默认不走 remux。NAS 实测本地能封装，但长窗口曾让 Omni 返回空答案；为保证回答质量，默认策略只保留 metadata（时间戳、序号、关键帧标记等），不长期保留大块 payload（视频包内容），上传时走 reencode。实验开关 `allow_h265_remux=true` 会保留 H.265 payload 并允许 remux；当前一路桌面摄像头短主动查询已验证 `remux_success=1`、`reencode=0` 且回答正常，但还不能作为全量默认依据。
4. 低配 NAS 想减少 reencode 压力，最直接的可落地方向是让摄像头源头输出 H.264 或低清流。H.264 解决“能不能复用原始包”，低清解决“即使必须再编码，画面也更小、CPU 更低”。

仍需保留边界：remux 省 CPU，但如果摄像头当前是高码率高清流，转封装后的 MP4 可能比重新编码更大。NAS 上曾观察到约 4.35MB 的 remux 包触发 Omni `WriteTimeout`（写入超时，即请求体上传阶段超时）；后续同一路摄像头在较短窗口中 remux 包约 1.37MB，查询成功。之后又修正了 remux MP4 时间戳：不能用 perception fps（感知帧率）给原始摄像头包造时间轴，否则 15fps 原始包会被按 1fps/2fps 写成慢动作长视频，增加云端处理和超时风险。修复后同一路按需查询约 0.53MB，Omni 往返约 10.82 秒。最新实现还把 remux 的 raw 输入和 mp4 输出都放在内存流里，避免每次 Omni 上传前写两个磁盘临时文件。H.265 码流现在只能作为实验开关启用：真实 NAS 长窗口 H.265 remux 曾本地成功但 Omni 空答案；最新短主动查询窗口又验证了 H.265 remux 可以正常回答。因此当前策略是默认保守回退，现场实验可打开 `allow_h265_remux` 做分场景复验。

下一步优先级：

1. 第一轮继续：用 2-4 路摄像头复验默认 1000ms 下的峰值，重点观察有运动窗口、Identity 和 Omni 触发窗口。
2. 第一轮继续：评估硬件解码（用 NAS 芯片的视频解码单元替代纯 CPU 解码）的可落地性，作为多路摄像头的进一步安全余量。
3. 第一轮继续：为 remux 上传体积增加更直观的性能页展示，避免用户只看到空答案，看不出是高码率包上传超时。
4. 第二轮继续：LOW 拉流已经在单路桌面摄像头上显著达标；下一步要用多人/移动/夜间光照和更多摄像头复验，确认 80% 画面质量是否仍满足日常看家与身份识别。
5. 运维固化：当前 NAS 已清理 `MILOCO_CAMERA__FRAME_INTERVAL` 覆盖；后续打包/部署脚本不要再把性能页可调参数写死到 compose 环境变量里，除非 UI 同步展示“被环境变量锁定”。
