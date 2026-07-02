# NAS Docker 部署

默认使用 Docker Compose bridge 网络，并显式映射两个 WebUI 端口。这样绿联等 NAS 面板的“快速访问”可以直接列出 Miloco 面板和 OpenClaw 对话页。

## 硬门槛

- NAS 能运行 Docker 或 Container Manager。
- CPU 是 `x86_64/amd64` 或 `aarch64/arm64`。
- 容器镜像基于 Debian bookworm，满足 Miloco Linux runtime 的 `glibc >= 2.28` 要求。
- NAS 和摄像头在同一可达局域网。

## 一键启动

```bash
cd nas/docker
./manage.sh start
./manage.sh logs
```

默认使用在线镜像，不在 NAS 上现场构建：

```bash
./manage.sh start
```

国内 x86_64 NAS 优先按 `docs/nas/docker-deploy.md` 使用华为 SWR 普通 tag；面向普通用户的一键 YAML 不写 digest。

维护者调试才使用：

```bash
EASY_MILOCO_BUILD=1 ./manage.sh start
```

如果 Docker socket 权限不足，`manage.sh` 会自动尝试 `sudo docker`，按提示输入 NAS 用户密码即可。

如果 YAML 或 `.env` 里已经有 `OMNI_API_KEY`、`OMNI_BASE_URL`、`OMNI_MODEL`，容器会自动写入 Miloco 感知模型配置并启动服务。
模型配置和账号授权分开处理；公开 YAML 不填写 `MILOCO_ACCOUNT_AUTH`。首次部署后进入 Miloco 面板绑定小米账号即可。

OpenClaw 聊天模型必须单独填写 `OPENCLAW_CHAT_MODEL`、`OPENCLAW_CHAT_BASE_URL`、`OPENCLAW_CHAT_API_KEY`；不会复用 Miloco 的 `OMNI_*`。`OPENCLAW_CHAT_PROVIDER` 可以留空，容器会按 URL 和模型名自动推断。

如果这些值为空，容器只完成基础安装和服务启动；补齐 `.env` 后执行：

```bash
./manage.sh restart
```

当前 v0.5 release 尚未包含独立 NAS zip。入口脚本会优先找 NAS zip；`x86_64/amd64` NAS 可临时回退 Windows 包内的 Linux payload。`aarch64/arm64` NAS 需要后续发布包含 `linux-aarch64` runtime 的 NAS zip，或在 `.env` 里指定 `MILOCO_RELEASE_ZIP_URL`。

## 访问

在 NAS 本机：

- Miloco 面板：`http://127.0.0.1:1810/`
- OpenClaw 对话：`http://127.0.0.1:18789/`

在其他电脑或手机上，把 `127.0.0.1` 换成 NAS 的局域网 IP。

容器列表中应看到容器名 `miloco`；快速访问里应出现 `1810` 和 `18789` 两个端口：

- `1810`：Miloco 面板
- `18789`：OpenClaw 对话页

NAS 默认把 OpenClaw 网关放在容器内部 `18790`，公开的 `18789` 是容器内代理入口。快速访问 `18789` 会自动跳转到带 token 的 OpenClaw 对话页，不需要用户猜网关令牌。不要把内部 `18790` 映射到 NAS。容器会为局域网 HTTP 访问配置 OpenClaw Control UI，避免停在安全上下文/设备身份页面。

当前镜像应内置 Miloco Linux runtime payload 和感知模型文件。正常首次启动只从镜像本地文件初始化 `/data/runtime`，并同步模型到 `/data/miloco/models`，不会再到 GitHub Release 下载 zip。若日志出现 `Downloading release payload`，请先确认拉到的是最新镜像。当前自包含镜像先发布 `linux/amd64`，arm64 NAS 需要等待 NAS/Linux arm64 payload 进入 release 后再支持。OpenClaw Control UI 会开启 Host header 同源回退，避免容器只能识别 Docker 内网 IP 时拦截 NAS 局域网访问。

也可以直接运行：

```bash
./manage.sh urls
```

`./manage.sh urls` 会输出 Miloco 面板和带 token 的 OpenClaw 对话页。

## 数据目录

所有运行数据放在：

```text
nas/docker/data/
```

不要把 `data/`、`.env`、日志、授权 payload、API Key 提交到 git。

## 常用命令

```bash
./manage.sh status
./manage.sh logs
./manage.sh validate
./manage.sh restart
./manage.sh stop
```

需要重新执行安装流程：

```bash
MILOCO_FORCE_INSTALL=1 ./manage.sh start
```

更新前先备份：

```bash
./manage.sh update
```
