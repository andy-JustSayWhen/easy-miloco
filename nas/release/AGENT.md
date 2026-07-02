# NAS Agent 自动部署说明

目标：通过 SSH 在用户 NAS 上部署 easy-miloco Docker 项目。

## 先向用户索要

- 让用户先在 NAS 管理界面开启终端机/SSH。
- NAS SSH 地址、端口、用户名和密码或密钥。
- LLM API Key、Base URL、模型名。
- NAS 是否有 Docker 专用文件夹；如果有，项目目录放进去。

## 部署原则

- 优先用本包的 `compose.ugreen.yaml`。
- 不要索要小米账号授权 payload；首次启动后让用户在 Miloco 面板绑定。
- 项目目录放在 Docker 专用文件夹下的子文件夹，例如 `/volume1/docker/miloco`。
- 没有 Docker 专用文件夹时，在用户确认的位置创建 `miloco` 子文件夹。
- 不提交、不打印 API Key、SSH 密码、授权信息。

## SSH 步骤

1. 登录 NAS，确认 Docker 可用：
   ```bash
   docker --version
   docker compose version || docker-compose version
   ```
2. 创建项目目录：
   ```bash
   PROJECT_DIR=/volume1/docker/miloco
   mkdir -p "$PROJECT_DIR"
   cd "$PROJECT_DIR"
   ```
3. 上传或写入 `compose.yaml`，只替换：
   - `OMNI_API_KEY`
   - `OPENCLAW_CHAT_API_KEY`
   - 需要换供应商时的 `MODEL` 和 `BASE_URL`
   - `volumes` 左侧路径
4. 启动：
   ```bash
   docker compose -f compose.yaml up -d
   ```
5. 查看进度：
   ```bash
   docker compose -f compose.yaml ps
   docker compose -f compose.yaml logs -f --tail=120
   ```

## 交付给用户

- Miloco 面板：`http://<NAS-IP>:1810/`
- OpenClaw 对话：`http://<NAS-IP>:18789/`
- 是否 running
- 如果未完成，列出缺口，不要说已经完成。
