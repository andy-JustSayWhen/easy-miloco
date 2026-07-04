# NAS 部署硬门槛

本文只写“能不能部署”的硬门槛。达不到任一条，就不要把该 NAS 作为 Miloco 直接部署目标。

## 必须满足

| 项目 | 硬门槛 | 自检命令 |
| --- | --- | --- |
| 系统类型 | 必须是 Linux。DSM/QTS/UGOS 等可以，但必须能进入标准 Linux shell。 | `uname -s` 必须输出 `Linux` |
| CPU 架构 | 只支持 `x86_64` 或 `aarch64`。 | `uname -m` 必须输出 `x86_64`、`amd64`、`aarch64` 或 `arm64` |
| C library | Linux runtime 使用 `manylinux_2_28`，glibc 必须 `>= 2.28`。 | `ldd --version` 第一行版本必须 `2.28+` |
| Shell | 必须有 `bash`。 | `command -v bash` |
| 基础工具 | 必须有 `curl`、`tar`、`python3`。 | `command -v curl tar python3` |
| 用户目录 | 当前用户 home 必须可写，长期配置会落在 `~/.openclaw/` 和 uv tool 目录。 | `test -w "$HOME"` |
| 网络 | 必须能访问 OpenClaw、npm、uv、GitHub Release，或允许本机下载后传包到 NAS。 | `curl -I https://openclaw.ai` 等 |
| 摄像头局域网 | 如果要使用摄像头实时流/持续感知，NAS 必须和摄像头处于可互通局域网。 | NAS 能访问摄像头所在网段 |

## 明确不支持

- 32 位 NAS：`armv7l`、`armhf`、`i386`、`i686`。
- 非 Linux 系统直接部署：FreeBSD、TrueNAS CORE、Windows 原生、路由器固件裸系统。
- glibc 低于 `2.28` 的老系统。
- 只有 BusyBox/ash、没有 bash 和标准用户目录的精简系统。
- 不能写 home、不能运行用户态后台服务、不能安装/运行 uv 和 Node.js 的受限账号。
- 想用摄像头但 NAS 与摄像头不在同一可达局域网的环境。

## Docker/虚拟机边界

Docker 或虚拟机可以作为绕过 NAS 宿主限制的方式，但容器/虚拟机本身也必须满足上面的 Linux、架构、glibc 和网络门槛。

摄像头场景下，不建议默认用隔离网络容器。至少要保证容器能访问家庭局域网摄像头；否则设备云控可能可用，但实时画面和持续感知不可用。

满足硬门槛后：

- 用户自己部署走 [docker-deploy.md](docker-deploy.md)。
- Agent 自动部署走 [agent-install.md](agent-install.md)。
- 一句话提示走 [agent-prompt.md](agent-prompt.md)。
- 低配 NAS 性能优化当前交接状态走 [low-config-performance-current-status.md](low-config-performance-current-status.md)。

## 一条命令自检

在 NAS SSH 中运行：

```bash
printf 'os='; uname -s
printf 'arch='; uname -m
printf 'glibc='; ldd --version 2>/dev/null | head -n 1 || true
command -v bash curl tar python3
test -w "$HOME" && echo 'home=writable' || echo 'home=not-writable'
```

判定：

- `os=Linux`
- `arch=x86_64` / `amd64` / `aarch64` / `arm64`
- glibc `2.28` 或更高
- `bash`、`curl`、`tar`、`python3` 都有路径
- `home=writable`

以上全部满足，才进入 NAS 部署适配流程。
