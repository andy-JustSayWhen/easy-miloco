#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-miloco}"
SERVICE_NAME="${MILOCO_SERVICE_NAME:-miloco}"
DATA_DIR="$SCRIPT_DIR/data"
BACKUP_DIR="$SCRIPT_DIR/backups"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
HWACCEL_COMPOSE_FILE="$SCRIPT_DIR/compose.hwaccel.yaml"
DOCKER_CMD=()
DEFAULT_IMAGE="docker.io/andywu114/easy-miloco-nas:v0.5"

log() {
  printf '[easy-miloco-nas] %s\n' "$*"
}

die() {
  printf '[easy-miloco-nas][FAIL] %s\n' "$*" >&2
  exit 1
}

init_docker_cmd() {
  if [ "${#DOCKER_CMD[@]}" -gt 0 ]; then
    return
  fi

  if [ -n "${EASY_MILOCO_DOCKER:-}" ]; then
    # shellcheck disable=SC2206
    DOCKER_CMD=($EASY_MILOCO_DOCKER)
    return
  fi

  command -v docker >/dev/null 2>&1 || die "docker not found"

  if docker ps >/dev/null 2>&1; then
    DOCKER_CMD=(docker)
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    if sudo -n docker ps >/dev/null 2>&1; then
      DOCKER_CMD=(sudo -n docker)
    else
      DOCKER_CMD=(sudo docker)
    fi
  else
    die "Current user cannot access Docker daemon. Add the user to the docker group or run with sudo."
  fi
}

compose() {
  init_docker_cmd
  local extra_args=()
  local has_file_arg=0
  local arg
  for arg in "$@"; do
    case "$arg" in
      -f|--file)
        has_file_arg=1
        break
        ;;
    esac
  done
  if [ "${1:-}" != "version" ] && [ "$has_file_arg" -eq 0 ] && should_enable_hwaccel_compose; then
    extra_args=(-f compose.yaml -f "$HWACCEL_COMPOSE_FILE")
  fi

  if "${DOCKER_CMD[@]}" compose version >/dev/null 2>&1; then
    "${DOCKER_CMD[@]}" compose -p "$PROJECT_NAME" "${extra_args[@]}" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -p "$PROJECT_NAME" "${extra_args[@]}" "$@"
  else
    die "Docker Compose not found. Install Docker/Container Manager first."
  fi
}

ensure_env() {
  if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    log "Created .env from .env.example"
  fi
}

nas_ip_hint() {
  if command -v ip >/dev/null 2>&1; then
    ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}'
  elif command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | awk '{print $1}'
  fi
}

env_value() {
  local key="$1"
  [ -f "$ENV_FILE" ] || return 1
  awk -F= -v k="$key" '
    $0 !~ /^[[:space:]]*#/ && $1 == k {
      sub(/^[^=]*=/, "")
      gsub(/^[[:space:]]+|[[:space:]]+$/, "")
      print
      exit
    }
  ' "$ENV_FILE"
}

env_flag() {
  local key="$1"
  local default="${2:-0}"
  local value="${!key:-}"
  if [ -z "$value" ]; then
    value="$(env_value "$key" 2>/dev/null || printf '%s' "$default")"
  fi
  case "$value" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

env_value_or_default() {
  local key="$1"
  local default="$2"
  local value="${!key:-}"
  if [ -z "$value" ]; then
    value="$(env_value "$key" 2>/dev/null || true)"
  fi
  printf '%s' "${value:-$default}"
}

should_enable_hwaccel_compose() {
  local mode
  mode="$(env_value_or_default EASY_MILOCO_HWACCEL auto)"
  case "$mode" in
    1|true|TRUE|yes|YES|on|ON|force|FORCE)
      [ -f "$HWACCEL_COMPOSE_FILE" ] || die "compose.hwaccel.yaml missing"
      return 0
      ;;
    0|false|FALSE|no|NO|off|OFF|none|NONE)
      return 1
      ;;
    auto|AUTO|"")
      [ -e /dev/dri ] && [ -f "$HWACCEL_COMPOSE_FILE" ]
      return
      ;;
    *)
      die "Invalid EASY_MILOCO_HWACCEL=$mode. Use auto, 1, or 0."
      ;;
  esac
}

image_ref() {
  local img="${EASY_MILOCO_IMAGE:-}"
  if [ -z "$img" ]; then
    img="$(env_value EASY_MILOCO_IMAGE 2>/dev/null || true)"
  fi
  printf '%s' "${img:-$DEFAULT_IMAGE}"
}

image_exists() {
  init_docker_cmd
  "${DOCKER_CMD[@]}" image inspect "$1" >/dev/null 2>&1
}

print_urls() {
  local host="${NAS_HOST:-$(nas_ip_hint)}"
  [ -n "$host" ] || host="<NAS-IP>"
  local miloco_port="${MILOCO_PORT:-1810}"
  local openclaw_port="${OPENCLAW_PORT:-18789}"

  miloco_port="$(env_value MILOCO_PORT || printf '%s' "$miloco_port")"
  openclaw_port="$(env_value OPENCLAW_PORT || printf '%s' "$openclaw_port")"

  local miloco_url="http://${host}:${miloco_port}/"
  local openclaw_url="http://${host}:${openclaw_port}/"
  local openclaw_direct_url=""
  openclaw_direct_url="$(
    compose exec -T "$SERVICE_NAME" bash -lc 'python3 - "$OPENCLAW_PORT" "$1" <<'"'"'PY'"'"'
import json
import sys
from pathlib import Path
from urllib.parse import quote

port = int(sys.argv[1] or "18789")
host = sys.argv[2] or "127.0.0.1"
path = Path.home() / ".openclaw" / "openclaw.json"
token = ""
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
    auth = data.get("gateway", {}).get("auth", {})
    if auth.get("mode") == "token":
        token = auth.get("token") or ""

url = f"http://{host}:{port}/chat?session=main&easy_miloco_token=1"
if token:
    url += "#token=" + quote(token, safe="")
print(url)
PY' _ "$host" 2>/dev/null || true
  )"
  [ -n "$openclaw_direct_url" ] || openclaw_direct_url="http://${host}:${openclaw_port}/chat?session=main"

  cat <<EOF
【快速使用】
1. Miloco 面板
   用途：查看 Miloco 状态、设备、摄像头和配置。
   地址：$miloco_url

2. OpenClaw 对话页
   用途：日常使用 Miloco，自然语言聊天即可。
   快速访问：$openclaw_url
   直达地址：$openclaw_direct_url

3. 日志
   命令：./manage.sh logs

4. 控制服务
   启动：./manage.sh start
   重启：./manage.sh restart
   停止：./manage.sh stop
   验收：./manage.sh validate
EOF
}

preflight() {
  command -v docker >/dev/null 2>&1 || die "docker not found"
  init_docker_cmd
  compose version >/dev/null

  local arch
  arch="$(uname -m 2>/dev/null || true)"
  case "$arch" in
    x86_64|amd64|aarch64|arm64) ;;
    *) die "unsupported CPU arch: ${arch:-unknown}. Need x86_64/amd64/aarch64/arm64." ;;
  esac

  [ -f "$SCRIPT_DIR/compose.yaml" ] || die "compose.yaml missing"
  [ -f "$SCRIPT_DIR/Dockerfile" ] || die "Dockerfile missing"
  [ -f "$SCRIPT_DIR/entrypoint.sh" ] || die "entrypoint.sh missing"
  log "preflight ok: arch=$arch"
}

backup() {
  mkdir -p "$BACKUP_DIR"
  if [ ! -d "$DATA_DIR" ]; then
    log "No data directory yet; skip backup."
    return
  fi
  local ts out
  ts="$(date +%Y%m%d-%H%M%S)"
  out="$BACKUP_DIR/easy-miloco-nas-data-$ts.tar.gz"
  tar -czf "$out" -C "$SCRIPT_DIR" data
  log "Backup created: $out"
}

start() {
  preflight
  ensure_env
  local img
  img="$(image_ref)"

  if env_flag EASY_MILOCO_BUILD 0; then
    log "Building image on this NAS: $img"
    if should_enable_hwaccel_compose; then
      compose -f compose.yaml -f "$HWACCEL_COMPOSE_FILE" -f compose.build.yaml up -d --build
    else
      compose -f compose.yaml -f compose.build.yaml up -d --build
    fi
  else
    if env_flag EASY_MILOCO_SKIP_PULL 0; then
      log "Skipping image pull; using local image if present: $img"
    elif image_exists "$img"; then
      compose pull "$SERVICE_NAME" || log "Image pull failed; using existing local image: $img"
    else
      log "Pulling NAS image: $img"
      compose pull "$SERVICE_NAME" || die "Image pull failed. Check NAS network or set EASY_MILOCO_IMAGE to a reachable mirror."
    fi
    compose up -d
  fi
  print_urls
}

restart() {
  ensure_env
  compose restart "$SERVICE_NAME"
  print_urls
}

stop() {
  compose down
}

status() {
  compose ps
  compose exec -T "$SERVICE_NAME" bash -lc 'set +e; export PATH="$HOME/.openclaw/bin:$HOME/.local/bin:/root/.local/bin:$PATH"; printf "\n== Miloco ==\n"; miloco-cli service status 2>&1 || true; printf "\n== OpenClaw ==\n"; curl -fsS "http://127.0.0.1:${OPENCLAW_PORT:-18789}/health" 2>&1 || true; printf "\n"; ss -ltnp | grep -E ":(1810|${OPENCLAW_PORT:-18789}|${OPENCLAW_INTERNAL_PORT:-18790})" || true'
}

logs() {
  compose logs -f "$SERVICE_NAME"
}

validate() {
  compose exec -T "$SERVICE_NAME" bash -lc 'set +e; export PATH="$HOME/.openclaw/bin:$HOME/.local/bin:/root/.local/bin:$PATH"; pass=0; fail=0; printf "== easy-miloco NAS Docker validation ==\n"; if curl -fsS -m 5 "http://127.0.0.1:${MILOCO_PORT:-1810}/health" >/tmp/easy-miloco-health.json 2>/dev/null; then printf "[PASS] miloco.health %s\n" "$(cat /tmp/easy-miloco-health.json)"; pass=$((pass+1)); else printf "[FAIL] miloco.health\n"; fail=$((fail+1)); fi; if curl -fsS -m 5 "http://127.0.0.1:${OPENCLAW_PORT:-18789}/health" >/tmp/easy-openclaw-health.json 2>/dev/null; then printf "[PASS] openclaw.proxy %s\n" "$(cat /tmp/easy-openclaw-health.json)"; pass=$((pass+1)); else printf "[FAIL] openclaw.proxy\n"; fail=$((fail+1)); fi; code="$(curl -sSL -o /dev/null -w "%{http_code}" -m 5 "http://127.0.0.1:${OPENCLAW_PORT:-18789}/chat?session=main" 2>/dev/null || true)"; if [ "$code" = 200 ]; then printf "[PASS] openclaw.chat HTTP %s\n" "$code"; pass=$((pass+1)); else printf "[FAIL] openclaw.chat HTTP %s\n" "${code:-none}"; fail=$((fail+1)); fi; if [ -s "${MILOCO_HOME:-/data/miloco}/models/det_4C.onnx" ] && [ -s "${MILOCO_HOME:-/data/miloco}/models/human_body_reid_v2.onnx" ]; then printf "[PASS] miloco.models %s files in %s\n" "$(find "${MILOCO_HOME:-/data/miloco}/models" -maxdepth 1 -type f | wc -l | tr -d " ")" "${MILOCO_HOME:-/data/miloco}/models"; pass=$((pass+1)); else printf "[FAIL] miloco.models required perception models missing\n"; fail=$((fail+1)); fi; [ "$fail" -eq 0 ] && printf "BASIC_READY=yes\n" || printf "BASIC_READY=no\n"; printf "PASS_COUNT=%s\nFAIL_COUNT=%s\n" "$pass" "$fail"; exit "$fail"'
}

perf_probe() {
  compose exec -T "$SERVICE_NAME" easy-miloco-perf-probe "$@"
}

update() {
  preflight
  ensure_env
  backup
  if env_flag EASY_MILOCO_BUILD 0; then
    if should_enable_hwaccel_compose; then
      compose -f compose.yaml -f "$HWACCEL_COMPOSE_FILE" -f compose.build.yaml up -d --build
    else
      compose -f compose.yaml -f compose.build.yaml up -d --build
    fi
  else
    local img
    img="$(image_ref)"
    compose pull "$SERVICE_NAME" || die "Image pull failed. Check NAS network or set EASY_MILOCO_IMAGE to a reachable mirror."
    compose up -d
  fi
  print_urls
}

uninstall() {
  compose down
  if [ "${1:-}" = "--delete-data" ]; then
    backup
    rm -rf "$DATA_DIR"
    log "Data deleted: $DATA_DIR"
  else
    log "Container removed. Data kept at: $DATA_DIR"
  fi
}

usage() {
  cat <<'EOF'
Usage:
  ./manage.sh start          预检并启动 NAS Docker 部署，默认拉取在线镜像
  ./manage.sh urls           显示 Miloco / OpenClaw 访问地址
  ./manage.sh status         查看容器、Miloco、OpenClaw 状态
  ./manage.sh logs           跟随安装和运行日志
  ./manage.sh validate       运行基础/满血验收
  ./manage.sh perf-probe     只读采样 Miloco 运行期 CPU/RAM
  ./manage.sh restart        重启服务
  ./manage.sh stop           停止并移除容器，保留 data/
  ./manage.sh update         备份 data/ 后更新/重建容器
  ./manage.sh backup         备份 data/
  ./manage.sh uninstall      移除容器，保留 data/
  ./manage.sh uninstall --delete-data
EOF
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  preflight) preflight "$@" ;;
  start|up) start "$@" ;;
  urls|open) print_urls "$@" ;;
  status|ps) status "$@" ;;
  logs|log) logs "$@" ;;
  validate|check) validate "$@" ;;
  perf-probe|perf) perf_probe "$@" ;;
  restart) restart "$@" ;;
  stop|down) stop "$@" ;;
  update) update "$@" ;;
  backup) backup "$@" ;;
  uninstall|remove) uninstall "$@" ;;
  help|-h|--help) usage ;;
  *) usage; die "unknown command: $cmd" ;;
esac
