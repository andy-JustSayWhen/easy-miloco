# Known Issues

这里沉淀部署、更新、回滚和运行过程中的常见问题。Agent 排障时应先查本文件；如果遇到新问题，修复后补充到这里。

## 低版本 Windows 的兼容边界

现象：

- 摄像头实时流不稳定。
- WSL mirrored networking 不可用或行为不一致。
- Hyper-V 防火墙相关命令不可用。

原因：

- v0.2 完整体验只保证 Windows 11 22H2+。

处理：

- 低于该版本可以尝试基础服务，但不承诺摄像头实时流、持续感知和 OpenClaw/Miloco 联动稳定。

## 夸克网盘副本不能作为版本基准

现象：

- 用户拿到夸克网盘下载链接，误以为它是独立版本源。

原因：

- 本项目版本基准只认 GitHub Release。夸克网盘只是人工同步副本。

处理：

- release notes 和 manifest 以 GitHub Release 为准。

## 摄像头 WebUI 有画面，但设备列表显示离线

现象：

- Miloco WebUI 实时画面能看到摄像头画面。
- 页面左上角或设备列表仍提示摄像头失败/离线。
- OpenClaw 有时能描述画面，有时拿不到 active perception source。

原因：

- 摄像头状态至少分云端在线、局域网在线、流连接成功、Agent 可用四层。
- 旧逻辑曾把云端 `online`、LAN `lan_online`、流 `connected` 混用，导致 UI 状态和实际画面不同步。

处理：

- 先按 [../fix-camera/cameras.md](../fix-camera/cameras.md) 的四层状态定位。
- 查看 Miloco 后端日志中该摄像头是否有 frame count 或 active source。
- 如果只有设备列表离线但实时画面可用，优先修正状态展示和聚合逻辑，不要直接重装。

## 摄像头 LAN override 过期导致误判在线

现象：

- `camera_lan_overrides.json` 中有旧 IP。
- SDK 局域网表没有该摄像头，但系统仍曾把摄像头标记为 `lan_online=True`。
- 旧 IP ping 不通或端口不通，摄像头被误判为可用。

原因：

- 旧逻辑在 SDK LAN table 无命中时仍强行采用 override IP。

处理：

- 当前代码已改为：SDK LAN table 无命中时忽略 override，不强行标记为局域网在线。
- 日志中看到 `Camera LAN override ignored because SDK LAN table has no hit` 属于预期保护行为。
- 相关测试：`backend/miloco/tests/test_miot_filter_and_cameras.py`。

## 误报修复类消息不应刷米家推送或小爱播报

现象：

- 手机收到多条相同的米家推送，例如“水浸卫士误报了一次……不用担心”。
- 小爱音箱也可能重复播报同类“已处理、无需担心”的文本。

原因：

- OpenClaw Agent 或自动修复链路可能把“状态说明”当成通知执行。
- 这类内容不是告警，也不需要用户处理，不能用手机推送或音箱播报打扰用户。

处理：

- 后端 MIoT 出口会静默拦截 status-only 消息（状态说明：例如误报、已恢复、已修复，并明确“不用担心/无需处理”）。
- 真正需要用户处理的告警仍允许通知，例如“客厅检测到水浸，请立即检查”。
- 同一米家推送文案默认 30 分钟内只发送一次；同一 `call_action`（设备动作，例如小爱播报）默认 5 分钟内只执行一次。
- 日志中看到 `Suppressed status-only Mi Home notification` 或 `Suppressed status-only MIoT call_action` 属于预期保护。

## 本地 Python 缺少 tzdata 导致测试收集失败

现象：

```text
ModuleNotFoundError: No module named 'tzdata'
ZoneInfoNotFoundError: No time zone found with key Asia/Shanghai
```

原因：

- Windows Python 环境没有系统 IANA 时区数据库，测试导入 `ZoneInfo("Asia/Shanghai")` 时失败。

处理：

```powershell
cd backend
uv run --group dev --with tzdata pytest miloco/tests/test_miot_filter_and_cameras.py -q
```

## 测试路径写错导致 `No module named miloco`

现象：

```text
ModuleNotFoundError: No module named 'miloco'
```

原因：

- 在仓库根目录直接跑 `backend/miloco/tests/...` 时，Python 包路径没有按 backend workspace 初始化。

处理：

```powershell
cd backend
uv run --group dev --with tzdata pytest miloco/tests/test_miot_filter_and_cameras.py -q
```
