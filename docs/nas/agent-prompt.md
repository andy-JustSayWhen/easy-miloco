# NAS Agent 一句话部署提示词

把下面整段复制给 Agent。适用前提：Agent 可以 SSH 到 NAS，且 NAS 已安装 Docker / Container Manager。

```text
你现在接管这台 NAS 的 easy-miloco Docker 部署。先读取总入口：

https://raw.githubusercontent.com/andy-JustSayWhen/easy-miloco/main/docs/install-guide.md

确认目标是 NAS/Linux 后，先按 NAS 硬门槛检查系统、CPU 架构、Docker/Compose、局域网可达性，再进入 NAS Agent Docker 子指南执行。

硬性规则：
1. NAS 默认走 Docker Compose host network，优先保证摄像头感知可用；不要为了 NAS 面板快速访问改成 bridge/ports，绿联 NAS 上该模式会导致摄像头视频流收不到帧。
2. 进入 nas/docker 后统一使用 ./manage.sh，不要手写零散 docker compose 命令。
3. 启动前运行 ./manage.sh preflight。
4. 如果我提供账号授权、API Key、Base URL、Model，写入 nas/docker/.env；不要把 .env、data/、backups/、日志提交到 git。
5. 启动用 ./manage.sh start，查看日志用 ./manage.sh logs。
6. 验收用 ./manage.sh status、./manage.sh validate、./manage.sh urls。
7. BASIC_READY=yes 只能说明基础服务可用；FULL_READY=yes 必须同时满足账号绑定、模型配置、OpenClaw 插件、设备/摄像头状态。
8. 如果 FULL_READY=no，明确列出缺口，不能说全部完成。
9. 更新或卸载前先 ./manage.sh backup。
10. 不要重复启动多个容器或多个安装流程。

交付格式：
- Miloco URL
- OpenClaw URL
- BASIC_READY / FULL_READY
- 缺口
- 日志入口
- 控制入口
```
