# NAS Docker 部署

本文是 NAS 的 Docker Compose 部署说明。先确认 [index.md](index.md) 的硬门槛；不满足系统、架构、网络条件时不要继续。

## 能不能 YAML 一键部署

可以，但分两档：

| 档位 | 条件 | 结果 |
| --- | --- | --- |
| 基础一键 | 粘贴 YAML 或运行 `./manage.sh start` | 拉取在线镜像、自动创建容器、从镜像内置载荷安装 Miloco/OpenClaw、启动基础服务 |
| 模型一键 | YAML 或 `.env` 已有 `OMNI_API_KEY`、`OMNI_BASE_URL`、`OMNI_MODEL` 和 OpenClaw 聊天模型三项 | 自动写入模型配置、启动插件和基础服务 |

YAML 不能公开内置小米账号授权和模型 API Key；这些只能由用户或 Agent 写入本机 `.env`。
模型配置和账号授权是两条独立链路：只填 `OMNI_API_KEY` / `OMNI_BASE_URL` / `OMNI_MODEL` 时，Miloco 面板也应显示模型已配置；缺小米账号授权只影响米家绑定和 FULL_READY。
公开的一键 YAML 不放 `MILOCO_ACCOUNT_AUTH`。首次部署前用户拿不到授权 payload，应先启动镜像，再进入 Miloco 面板绑定小米账号；只有 Agent 已经拿到授权 payload 的维护场景才写入 `.env`。

OpenClaw 聊天模型必须单独填写，不会复用上面的 `OMNI_MODEL` / `OMNI_BASE_URL` / `OMNI_API_KEY`：

```text
OPENCLAW_CHAT_MODEL=<模型名>
OPENCLAW_CHAT_BASE_URL=<OpenAI-compatible Base URL>
OPENCLAW_CHAT_API_KEY=<API Key>
```

`OPENCLAW_CHAT_PROVIDER` 可留空，容器会按 URL 和模型名自动推断。只有排障或接入特殊 OpenClaw provider 时才手动填，例如 `deepseek`、`minimax`、`xiaomi-token-plan`。
它不是账号类型、计费类型或 Token Plan 类型；普通用户不需要理解或填写它。
从 CC Switch 复制时，把 `ANTHROPIC_MODEL`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` 分别填到 `OPENCLAW_CHAT_MODEL`、`OPENCLAW_CHAT_BASE_URL`、`OPENCLAW_CHAT_API_KEY`，Base URL 原样复制，不要自行补 `/v1` 或 `/anthropic`。
自动推断会优先看 `BASE_URL` 域名，再看模型名；例如商汤/SenseNova 使用 `deepseek-v4-flash` 这类模型名时，只要 `BASE_URL` 是 `https://token.sensenova.cn/v1`，也会按 SenseNova 处理。
`OPENCLAW_CHAT_API` 也是排障字段，普通用户留空。DeepSeek、MiniMax、商汤日日新/SenseNova 会自动按 URL/provider 选择请求形状；SenseNova 的 `https://token.sensenova.cn/v1` 默认走 `openai-completions`。
OpenClaw 模型栏里模型名后面的 `Off` / `Adaptive` 是思考/推理模式状态，不是“模型关闭”或“未配置”。

默认不在 NAS 上现场构建镜像。现场构建会拉 `node`、apt、npm、uv 等多条外网链路，实测在家庭 NAS 上很容易低速卡住。普通部署走在线镜像；只有维护者调试才设置 `EASY_MILOCO_BUILD=1`。

## 文件

部署文件在仓库：

```text
nas/docker/
├── .env.example
├── compose.build.yaml
├── Dockerfile
├── README.md
├── compose.yaml
├── compose.ugreen-template.yaml
├── entrypoint.sh
└── manage.sh
```

## 推荐命令

```bash
cd nas/docker
./manage.sh start
./manage.sh logs
```

如果当前用户不能直接访问 Docker socket，`manage.sh` 会自动尝试 `sudo docker`；按提示输入 NAS 用户密码即可。

当前 v0.5 release 尚未包含独立 NAS zip。入口脚本会优先找 NAS zip；`x86_64/amd64` NAS 可临时回退 Windows 包内的 Linux payload。`aarch64/arm64` NAS 需要发布包含 `linux-aarch64` runtime 的 NAS zip，或在 `.env` 里填写 `MILOCO_RELEASE_ZIP_URL`。

访问：

- Miloco 面板：`http://<NAS-IP>:1810/`
- OpenClaw 对话：`http://<NAS-IP>:18789/`

Docker 项目显示 running 后，容器里的 Web 服务可能还需要 1-2 分钟完成二阶段启动；如果刚点开 `1810` 或 `18789` 出现连接拒绝，等 1-2 分钟再刷新。
新镜像中 `18789` 可能先显示“OpenClaw 正在启动”等待页，这表示公开入口已经起来、内部网关仍在初始化；页面会自动刷新，不要因此反复删除项目或重部署。

## 网络和快捷访问

默认使用：

```yaml
container_name: miloco
ports:
  - "1810:1810"
  - "18789:18789"
```

这是 NAS 图形界面的默认选择：容器列表中显示一个容器 `miloco`，快速访问里列出两个入口。

- `1810`：Miloco 面板
- `18789`：OpenClaw 对话页

Miloco 后端在容器内默认监听 `0.0.0.0:1810`；OpenClaw 网关默认在容器内部 `18790` 以 `OPENCLAW_AUTH=token` 启动，公开的 `18789` 是容器内代理入口。NAS 面板快速访问打开 `18789` 时，代理会自动跳到带 token 的 OpenClaw 对话页；浏览器历史里的裸 `/chat?session=main` 深链也会被补上 token，用户不需要猜登录凭证。

不要把内部 `18790` 映射到 NAS；只映射 `18789`。容器启动时会为局域网 HTTP 访问开启 `gateway.controlUi.allowInsecureAuth`、`gateway.controlUi.dangerouslyDisableDeviceAuth` 和 Host header 同源回退，避免普通用户停在安全上下文/设备身份页面。
如果 `18789` 先进入“OpenClaw 正在启动”页，说明代理已接管入口；继续等待自动刷新到聊天页即可。

NAS 镜像从 `v0.5` 起应内置 Miloco Linux runtime payload 和感知模型文件。维护者发布的 NAS 镜像由 GitHub Actions 先按当前 `NAS` 分支构建 runtime payload，再拷进镜像。正常情况下，首次启动只从镜像内置文件初始化 `/data/runtime`，并同步模型到 `/data/miloco/models`，不再在容器启动时访问 GitHub Release。若日志出现 `Downloading release payload`，说明正在使用旧镜像、内置 payload 缺失，或显式设置了 `MILOCO_RELEASE_ZIP_URL` / `MILOCO_FORCE_DOWNLOAD=1`。当前自包含镜像先发布 `linux/amd64`，arm64 NAS 需要等待 NAS/Linux arm64 payload 进入 release 后再支持。

## v0.5 国内镜像

国内 x86_64 NAS 优先使用华为 SWR 普通 tag：

```text
swr.cn-north-4.myhuaweicloud.com/easy-miloco/easy-miloco-nas:v0.5
```

维护者和 Agent 上传、校验、清理 SWR 镜像时，按 [../huawei-swr-docker-image-runbook.md](../huawei-swr-docker-image-runbook.md) 执行。

面向普通用户的一键 YAML 不写 digest。digest 只用于发布方校验镜像内容，不提升拉取速度，也容易让 NAS 图形界面配置变复杂。

如果拉镜像很慢或失败，不要反复重跑 `start`。优先处理以下三种：

```bash
# 1. 国内 x86_64 NAS 推荐：华为 SWR
EASY_MILOCO_IMAGE=swr.cn-north-4.myhuaweicloud.com/easy-miloco/easy-miloco-nas:v0.5 ./manage.sh start

# 2. Docker Hub 官方发布源
EASY_MILOCO_IMAGE=docker.io/andywu114/easy-miloco-nas:v0.5 ./manage.sh start

# 3. 毫秒镜像 Docker Hub 通道，当前链路不稳定，仅作备用
EASY_MILOCO_IMAGE=docker.1ms.run/andywu114/easy-miloco-nas:v0.5 ./manage.sh start

# 4. 使用你自己的镜像仓库或内网镜像
EASY_MILOCO_IMAGE=<registry>/<repo>/easy-miloco-nas:v0.5 ./manage.sh start

# 5. 维护者本地调试才现场构建
EASY_MILOCO_BUILD=1 ./manage.sh start
```

## 数据和隐私

- 持久目录：`nas/docker/data/`
- 本机环境变量：`nas/docker/.env`
- 不提交 `.env`、`data/`、授权 payload、API Key、日志和个人环境信息。

## 常用控制

```bash
./manage.sh urls
./manage.sh status
./manage.sh logs
./manage.sh validate
./manage.sh restart
./manage.sh stop
```

补齐 `.env` 后，执行 `./manage.sh restart`。入口脚本有安装标记，不会在普通重启时无脑重复安装。
如果只是补模型配置而没有小米账号授权，重启后 Miloco 面板应显示模型已配置，但 `FULL_READY` 仍会因为账号未绑定保持 `no`。

`./manage.sh urls` 会输出 Miloco 面板和 OpenClaw 对话页；OpenClaw 直达地址会带 token。

更新或卸载前：

```bash
./manage.sh backup
./manage.sh update
./manage.sh uninstall
```
