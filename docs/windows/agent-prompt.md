# Agent 一键部署提示词

用途：把下面提示词复制给具备 SSH 能力的 Agent，让它按官方流程在 Windows + WSL 机器上部署 Miloco。

第一次部署先看 [Windows部署总入口](index.md)。摄像头异常专项见 [摄像头问题快速定位与修复Runbook](../fix-camera/camera-runbook.md)。

## 标准提示词

```text
你现在接管一台 Windows 电脑的 Miloco 部署。目标是按 Xiaomi Miloco 官方说明，在 Windows 的 WSL2 内完成满血部署，并给出简短状态摘要。

目标机器：
- SSH：<windows_user>@<host_or_ip>
- WSL distro：<Ubuntu-24.04 或实际名称>
- WSL 用户：<linux_user>
- 如在中国大陆或 GitHub 慢：优先使用显式代理环境变量，例如 http://127.0.0.1:7897

硬性要求：
1. 不在 Windows 原生安装 Miloco；Windows 必须进入 WSL 安装。
2. 不关闭 Clash Verge / TUN；下载慢时用 http_proxy/https_proxy/all_proxy、镜像或官方缓存解决。
3. 按官方 Agent 流程执行：
   - Step 1: install.sh --agent-prepare
   - Step 2: 根据 JSON 询问/收集账号授权码和模型 API Key
   - Step 3: install.sh --agent-finish --account-auth ... --omni-api-key ...
4. 小米账号授权和 MiMo API Key 必须按顺序处理：先账号，再模型；不要同时问两个问题。
5. 记录关键命令、输出摘要、错误、判断和修复；不要把私有日志写入公开 docs。
6. 最终不能只验证服务启动，还要验证满血能力。
7. 摄像头异常不要直接重装，按“云端设备 → LAN 可达 → scope → stream connected → engine active_sources → OpenClaw 视觉推理”六层定位。

预检：
- Windows: wsl -l -v
- 如果没有 WSL: wsl --install -d Ubuntu-24.04
- 如果正确 wsl --install 仍提示参数无效: 管理员 PowerShell 用 DISM 启用 Microsoft-Windows-Subsystem-Linux 和 VirtualMachinePlatform，设置默认 WSL2，重启后再安装 Ubuntu
- WSL: cat /etc/os-release, uname -m, curl GitHub/OpenClaw
- Windows: netsh interface ipv4 show excludedportrange protocol=tcp
- Windows 管理员: Get-NetFirewallHyperVVMSetting ... DefaultInboundAction 应为 Allow
- WSL: 检查 ~/.wslconfig 是否 mirrored networking

安装：
- 下载 https://github.com/andy-JustSayWhen/easy-miloco/releases/latest/download/install.sh
- 运行 bash /tmp/miloco-install.sh --agent-prepare
- 如果 uv 长时间无输出，检查 ps/ss/du，不要重复启动安装
- Miloco 端口默认从 18860 起自动选择可用端口，并同步 server.url/server.port
- 安装 OpenClaw CLI/Gateway；若 WSL 无 node 且不能 sudo，就用户目录安装 Node tarball
- 如果已拿到账号授权和 Key，运行 bash /tmp/miloco-install.sh --agent-finish --account-auth '<授权码>' --omni-api-key '<MiMo API Key>'
- 如果还没有账号授权和 Key，可先运行 bash /tmp/miloco-install.sh --agent-finish 完成插件基础安装，但必须标记为等待用户授权，不能判定满血
- openclaw gateway restart

基础验收：
- 如果部署包里已有脚本，优先运行：
  powershell.exe -ExecutionPolicy Bypass -File <temp>\win-miloco-workflow.ps1 -Action AllBasic -Distro <distro> -MilocoPort <miloco_port> -OpenClawPort 18789
- 如需留档或交给别的 Agent 排查，运行：
  powershell.exe -ExecutionPolicy Bypass -File <temp>\win-miloco-workflow.ps1 -Action Report -Distro <distro> -MilocoPort <miloco_port> -OpenClawPort 18789 -ReportPath <temp>\miloco-report.txt
- miloco-cli service status
- curl -fsS http://127.0.0.1:<miloco_port>/health
- openclaw gateway status
- openclaw plugins inspect miloco-openclaw-plugin
- openclaw plugins doctor
- Windows curl.exe 访问 Miloco 和 OpenClaw

满血验收：
- 如果部署包里已有脚本，优先运行：
  powershell.exe -ExecutionPolicy Bypass -File <temp>\win-miloco-workflow.ps1 -Action Finish -AuthPayload '<授权码>' -MimoApiKey '<MiMo API Key>' -OmniModel '<Omni model>' -OmniBaseUrl '<Omni Base URL>' -Distro <distro> -MilocoPort <miloco_port> -OpenClawPort 18789
- miloco-cli account status 需要 is_bound=true
- miloco-cli config get model.omni.api_key --value-only 需要非空
- miloco-cli device list 需要 TSV 表头后有设备行
- miloco-cli scope camera list --pretty 能列出摄像头
- 如果要验收摄像头，逐个 did 核对 is_online=true、in_use=true、connected=true，并确认 /api/perception/engine/status 的 active_sources 包含目标 did
- 在 OpenClaw 聊天里逐个询问目标摄像头画面；视觉模型必须支持看图，MiMo v2.5 可用于视觉，MiMo v2.5-pro 不作为视觉模型
- 后端日志不能有 access token is empty 或 多模态大模型 API Key 未配置

交付：
- 给出 Miloco URL、OpenClaw URL、插件状态、账号状态、模型状态、设备/摄像头状态
- 把通用坑位抽象回 Windows 部署教程
- 如果缺用户授权码/API Key，不要宣称满血完成，只能说明基础服务就绪并等待用户提供材料
```

## 给用户的最短下一步

```text
请打开 Agent 生成的小米 OAuth 链接，完成登录后把授权码发给 Agent；同时提供 MiMo API Key。
```
