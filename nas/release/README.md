# easy-miloco NAS 部署包

本包用于在 NAS Docker / Container Manager 里部署 easy-miloco。

## 文件

- `compose.ugreen.yaml`：在线部署 YAML，优先用于绿联云 NAS。
- `AGENT.md`：给 AI Agent 的 SSH 自动部署说明。

## 手动部署

1. 准备 LLM API Key、Base URL、模型名。
2. 在 NAS 文件管理器里创建一个项目文件夹，建议放在 Docker 专用文件夹下，例如 `docker/miloco`。
3. 右键复制这个文件夹路径。
4. 打开 `compose.ugreen.yaml`，修改：
   - `OMNI_API_KEY`
   - `OPENCLAW_CHAT_API_KEY`
   - 如需换模型，同时修改对应 `MODEL` 和 `BASE_URL`
   - `volumes` 左侧路径
5. 绿联云 App -> Docker -> 项目 -> 创建项目，粘贴 YAML 并部署。
6. 等 1-3 分钟后访问：
   - Miloco 面板：`http://<NAS-IP>:1810/`
   - OpenClaw 对话：`http://<NAS-IP>:18789/`

## 绿联云 NAS 案例

1. 文件管理器中新建：`Docker/miloco`。
2. 右键复制路径，替换 YAML 中 `<创建一个文件夹，右键复制路径，粘贴到这里>`。
3. Docker 项目名填 `miloco`。
4. 部署后先打开 Miloco 面板绑定小米账号，再打开 OpenClaw 对话页测试回复。

不要公开分享运行后的数据目录、API Key、授权信息或容器备份。
