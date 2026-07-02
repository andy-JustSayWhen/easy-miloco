# Camera denylist 误拦截自动修复 Guide

用途：当 Miloco 面板或 `miloco-cli scope camera list --pretty` 显示某台摄像头“当前机型暂不支持感知”时，指导 Agent 快速判断它是真不支持，还是被 `camera_extra_info.yaml` 的 denylist 误拦截。

## 自动修复原则

1. 不要把 denylist 当成硬件能力边界。denylist 只能说明“当前配置会拦截这个型号”。
2. 不要直接改 UI、KV 或伪造 `connected=true`。摄像头是否能感知，必须以 raw/decoded frame 为证据。
3. 修复必须逐台闭环：一台一个 did、一条原因、一条修复动作、一条复测结果。
4. 只有 direct SDK probe 证明该型号能出帧，才允许从 denylist 移除该型号。
5. 修复后必须验证三件事：`connected=true`、进入 `perceive devices`、`perceive query` 能描述画面。

## Agent 自动处理流程

### 给普通用户的双击入口

不熟悉命令行的用户，直接双击：

```text
docs\scripts\fix-camera-denylist.bat
```

窗口出现后输入摄像头 did 或型号，例如：

```text
1039007350
chuangmi.camera.021a04
```

双击模式会自动执行：定位 WSL 环境、修 runtime denylist、重启 Miloco、启用 did（如果输入的是 did）、输出验证状态。

注意：双击入口只是降低使用门槛，不改变安全边界。仍然必须先确认 direct SDK probe 能出帧，不能把未知型号盲目移出 denylist。

### 1. 识别疑似误拦截

运行：

```bash
miloco-cli scope camera list --pretty
```

如果目标摄像头名称带“当前机型暂不支持感知”，记录：

- did
- name
- room_name
- `is_online`
- `in_use`
- `connected`

再通过 `/api/miot/home` 或 MIoT 设备详情确认 `model`。

### 2. 做 direct SDK probe

probe 要绕过 Miloco scope 和 denylist，手动构造 `MIoTCameraInfo` 后启动 native camera SDK，至少记录：

- `start ok` 或异常
- status events
- `raw_video_count`
- `decoded_jpg_count`
- `decoded_video_count`
- `first_frame_seconds`

判定：

| probe 结果 | 结论 | 动作 |
| --- | --- | --- |
| raw/decoded 任一计数大于 0 | denylist 误拦截 | 可以移除该型号 denylist |
| start ok 但 raw/decoded 全 0 | 不是配置误拦截证据 | 转 LAN/PPCS/Wi-Fi/设备侧排查 |
| create/start 报 native SDK 不支持 | 当前路径不支持 | 保留 denylist 或开发旁路接入 |

### 3. 一键修复 runtime denylist

已确认误拦截后，在 Windows PowerShell 中运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\docs\scripts\fix-camera-denylist.ps1 -Model "chuangmi.camera.xxxxx" -RestartService -Verify
```

如果只知道 did，并且 Miloco 后端正在运行，可运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\docs\scripts\fix-camera-denylist.ps1 -Did "<camera_did>" -RestartService -Enable -Verify
```

脚本会：

- 自动选择可用 WSL distro，或使用 `-Distro` 指定的 distro。
- 定位当前安装环境里的 `miot/configs/camera_extra_info.yaml`。
- 备份 YAML 到 `~/.openclaw/miloco/`。
- 从 `denylist.camera` 删除目标 model。
- 可选重启 Miloco、启用 did、输出验收状态。

如果用户不会打开 PowerShell，使用上面的 `docs\scripts\fix-camera-denylist.bat` 双击入口。

### 4. 修源码和测试

runtime 热修只是现场恢复。可复用修复必须同步源码：

1. 从 `backend/miot/src/miot/configs/camera_extra_info.yaml` 的 `denylist.camera` 移除该型号。
2. 在 `backend/miot/tests/test_camera.py` 的 camera model 判定测试中补断言：

```python
assert await is_camera_model("<model>", camera_extra_info=info) is True
```

3. 跑目标测试：

```powershell
uv run --project backend/miot pytest backend/miot/tests/test_camera.py -k test_is_camera_model_with_prefetched_info
```

### 5. 逐台记录

把结果写入验证记录，格式固定：

```text
did:
model:
原始现象:
direct SDK probe 证据:
根因:
处理办法:
复测结果:
```

## 本机案例

| did | model | 原因 | 修复结果 |
| --- | --- | --- | --- |
| `1039007350` | `chuangmi.camera.021a04` | denylist 误拦截，direct SDK probe 约 1.25 秒出首帧 | 移出 denylist 后 `connected=true`，视觉问答能描述画面 |
| `450305034` | `chuangmi.camera.036a02` | denylist 误拦截，direct SDK probe 约 1.37 秒出首帧 | 移出 denylist 后 `connected=true`，视觉问答能描述画面 |
| `1146439633` | `chuangmi.camera.061a01` | 不是 denylist 问题，raw/decoded 始终为 0 | 转设备视频数据面排查 |
