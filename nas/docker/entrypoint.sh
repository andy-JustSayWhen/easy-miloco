#!/usr/bin/env bash
set -Eeuo pipefail

export HOME="${HOME:-/data}"
export MILOCO_HOME="${MILOCO_HOME:-/data/miloco}"
export MILOCO_PORT="${MILOCO_PORT:-1810}"
export OPENCLAW_PORT="${OPENCLAW_PORT:-18789}"
export OPENCLAW_INTERNAL_PORT="${OPENCLAW_INTERNAL_PORT:-$((OPENCLAW_PORT + 1))}"
export OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-$OPENCLAW_INTERNAL_PORT}"
export OPENCLAW_BIND="${OPENCLAW_BIND:-auto}"
export OPENCLAW_AUTH="${OPENCLAW_AUTH:-token}"
export OPENCLAW_CHAT_API="${OPENCLAW_CHAT_API:-}"
export OPENCLAW_CHAT_MAX_TOKENS="${OPENCLAW_CHAT_MAX_TOKENS:-2048}"
export OPENCLAW_CHAT_TIMEOUT_SECONDS="${OPENCLAW_CHAT_TIMEOUT_SECONDS:-180}"
export OPENCLAW_CHAT_CONTEXT_WINDOW="${OPENCLAW_CHAT_CONTEXT_WINDOW:-262144}"
export MILOCO_SERVER__HOST="${MILOCO_SERVER__HOST:-0.0.0.0}"
export MILOCO_SERVER__PORT="${MILOCO_SERVER__PORT:-$MILOCO_PORT}"
export MILOCO_SERVER__URL="${MILOCO_SERVER__URL:-http://127.0.0.1:${MILOCO_PORT}}"
export MILOCO_AGENT__WEBHOOK_URL="${MILOCO_AGENT__WEBHOOK_URL:-http://127.0.0.1:${OPENCLAW_PORT}/miloco/webhook}"
export XDG_DATA_HOME="${EASY_MILOCO_XDG_DATA_HOME:-$HOME/.local/share}"
export XDG_CACHE_HOME="${EASY_MILOCO_XDG_CACHE_HOME:-$HOME/.cache}"
export XDG_BIN_HOME="${EASY_MILOCO_XDG_BIN_HOME:-$HOME/.local/bin}"
export UV_TOOL_DIR="${EASY_MILOCO_UV_TOOL_DIR:-$XDG_DATA_HOME/uv/tools}"
export UV_TOOL_BIN_DIR="${EASY_MILOCO_UV_TOOL_BIN_DIR:-$XDG_BIN_HOME}"
export UV_CACHE_DIR="${EASY_MILOCO_UV_CACHE_DIR:-$XDG_CACHE_HOME/uv}"
export PATH="$HOME/.openclaw/bin:$HOME/.local/bin:/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

STATE_DIR="${EASY_MILOCO_STATE_DIR:-/data/.easy-miloco}"
RUNTIME_DIR="${EASY_MILOCO_RUNTIME_DIR:-/data/runtime}"
INSTALL_SH="${EASY_MILOCO_INSTALL_SH:-$RUNTIME_DIR/install.sh}"
INSTALL_URL="${MILOCO_INSTALL_URL:-}"
RELEASE_API="${MILOCO_RELEASE_API:-https://api.github.com/repos/andy-JustSayWhen/easy-miloco/releases/latest}"
RELEASE_ZIP_URL="${MILOCO_RELEASE_ZIP_URL:-}"
VALIDATE_URL="${MILOCO_VALIDATE_URL:-https://raw.githubusercontent.com/andy-JustSayWhen/easy-miloco/main/docs/scripts/wsl-miloco-validate.sh}"
VALIDATE_SH="${EASY_MILOCO_VALIDATE_SH:-/data/wsl-miloco-validate.sh}"
BUNDLED_RUNTIME_DIR="${EASY_MILOCO_BUNDLED_RUNTIME_DIR:-/opt/easy-miloco/runtime}"
BUNDLED_VALIDATE_SH="${EASY_MILOCO_BUNDLED_VALIDATE_SH:-/opt/easy-miloco/wsl-miloco-validate.sh}"

log() {
  printf '[easy-miloco-nas] %s\n' "$*"
}

warn() {
  printf '[easy-miloco-nas][WARN] %s\n' "$*" >&2
}

stop_services() {
  set +e
  miloco-cli service stop >/dev/null 2>&1 || true
}

trap 'stop_services; exit 0' INT TERM

need_download() {
  [ "${MILOCO_FORCE_DOWNLOAD:-0}" = "1" ] && return 0
  [ ! -s "$INSTALL_SH" ] && return 0
  [ ! -s "$VALIDATE_SH" ] && return 0
  return 1
}

has_bundled_runtime() {
  [ -s "$BUNDLED_RUNTIME_DIR/install.sh" ] \
    && [ -s "$BUNDLED_RUNTIME_DIR/manifest.json" ] \
    && find "$BUNDLED_RUNTIME_DIR" -maxdepth 1 -type f -name "miloco-linux-*.tar.gz" | grep -q .
}

sync_bundled_models() {
  local src="$BUNDLED_RUNTIME_DIR/models"
  local dst="$MILOCO_HOME/models"
  if [ ! -d "$src" ]; then
    warn "Bundled perception models are missing from image; Miloco panel may report model files missing."
    return
  fi

  mkdir -p "$dst"
  cp -f "$src"/* "$dst"/
  for name in det_4C.onnx human_body_reid_v2.onnx; do
    if [ ! -s "$dst/$name" ]; then
      warn "Required perception model is still missing after sync: $dst/$name"
      return
    fi
  done
  log "Perception models synced to $dst ($(find "$dst" -maxdepth 1 -type f | wc -l | tr -d ' ') files)"
}

seed_bundled_runtime() {
  if ! has_bundled_runtime; then
    return
  fi

  mkdir -p "$RUNTIME_DIR" "$STATE_DIR" "$MILOCO_HOME"
  if [ "${MILOCO_FORCE_INSTALL:-0}" = "1" ] || [ ! -s "$INSTALL_SH" ] || [ ! -s "$RUNTIME_DIR/manifest.json" ] || ! find "$RUNTIME_DIR" -maxdepth 1 -type f -name "miloco-linux-*.tar.gz" | grep -q .; then
    log "Using bundled Miloco runtime payload"
    rm -rf "$RUNTIME_DIR"
    mkdir -p "$RUNTIME_DIR"
    cp -a "$BUNDLED_RUNTIME_DIR"/. "$RUNTIME_DIR"/
    chmod +x "$INSTALL_SH" 2>/dev/null || true
  fi

  if [ -s "$BUNDLED_VALIDATE_SH" ] && { [ "${MILOCO_FORCE_INSTALL:-0}" = "1" ] || [ ! -s "$VALIDATE_SH" ]; }; then
    cp "$BUNDLED_VALIDATE_SH" "$VALIDATE_SH"
    chmod +x "$VALIDATE_SH" 2>/dev/null || true
  fi
}

download_runtime_files() {
  mkdir -p "$(dirname "$INSTALL_SH")" "$STATE_DIR" "$MILOCO_HOME" "$RUNTIME_DIR"
  seed_bundled_runtime
  if need_download; then
    if has_bundled_runtime && [ -z "$INSTALL_URL" ] && [ -z "$RELEASE_ZIP_URL" ]; then
      warn "Bundled payload was present but runtime files are incomplete; falling back to online download."
    fi
    if [ -n "$INSTALL_URL" ]; then
      log "Downloading Miloco installer"
      curl -fL --retry 3 --connect-timeout 20 -o "$INSTALL_SH" "$INSTALL_URL"
    else
      download_release_payload
    fi
    chmod +x "$INSTALL_SH"

    log "Downloading validation script"
    curl -fL --retry 3 --connect-timeout 20 -o "$VALIDATE_SH" "$VALIDATE_URL"
    chmod +x "$VALIDATE_SH"
  fi
}

download_release_payload() {
  local zip_url="$RELEASE_ZIP_URL"
  local zip_path="$STATE_DIR/release.zip"

  if [ -z "$zip_url" ]; then
    zip_url="$(select_release_zip_url || true)"
  fi
  if [ -z "$zip_url" ]; then
    cat >&2 <<'EOF'
[easy-miloco-nas][FAIL] No usable release zip found.
Set MILOCO_RELEASE_ZIP_URL to a NAS release zip that contains payload/install.sh
and the matching linux runtime bundle for this CPU architecture.
EOF
    exit 1
  fi

  log "Downloading release payload: $zip_url"
  curl -fL --retry 3 --connect-timeout 20 -o "$zip_path" "$zip_url"
  rm -rf "$RUNTIME_DIR"
  mkdir -p "$RUNTIME_DIR"
  python3 - "$zip_path" "$RUNTIME_DIR" <<'PY'
import shutil
import sys
import zipfile
from pathlib import Path

zip_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
copied = 0

with zipfile.ZipFile(zip_path) as zf:
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        parts = [p for p in name.split("/") if p]
        rel = None
        if "payload" in parts:
            idx = parts.index("payload")
            rel_parts = parts[idx + 1 :]
            if rel_parts:
                rel = Path(*rel_parts)
        elif parts[-1] in {"install.sh", "install.py", "manifest.json"} or parts[-1].startswith("miloco-"):
            rel = Path(parts[-1])
        if rel is None:
            continue
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        copied += 1

if not (out_dir / "install.sh").is_file():
    raise SystemExit("release zip does not contain payload/install.sh")
if not (out_dir / "manifest.json").is_file():
    raise SystemExit("release zip does not contain payload/manifest.json")
print(f"extracted {copied} payload file(s) to {out_dir}")
PY
}

prime_payload_cache() {
  local bundle version cache
  bundle="$(find "$RUNTIME_DIR" -maxdepth 1 -type f -name "miloco-linux-*.tar.gz" | head -n 1 || true)"
  if [ -z "$bundle" ]; then
    warn "No local Miloco runtime bundle found in $RUNTIME_DIR; installer may download it."
    return
  fi

  version="$(
    python3 - "$RUNTIME_DIR/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(1)
print(json.loads(path.read_text(encoding="utf-8-sig")).get("version", "0.0.0"))
PY
  )"
  if [ -z "$version" ]; then
    warn "Cannot read payload manifest version; installer may download runtime bundle."
    return
  fi

  cache="$MILOCO_HOME/.install-cache/$version"
  log "Priming local Miloco runtime cache: $cache"
  rm -rf "$cache"
  mkdir -p "$cache"
  tar -xzf "$bundle" -C "$cache"
}

select_release_zip_url() {
  python3 - "$RELEASE_API" <<'PY'
import json
import platform
import sys
import urllib.request

api = sys.argv[1]
arch = platform.machine().lower()
with urllib.request.urlopen(api, timeout=20) as resp:
    data = json.load(resp)

assets = data.get("assets", [])
items = [
    (a.get("name") or "", a.get("browser_download_url") or "")
    for a in assets
]
items = [(name, url) for name, url in items if name.endswith(".zip") and url]

for name, url in items:
    low = name.lower()
    if "nas" in low:
        print(url)
        raise SystemExit(0)

if arch in {"x86_64", "amd64"}:
    for name, url in items:
        if "windows" in name.lower():
            print(url)
            raise SystemExit(0)

raise SystemExit(1)
PY
}

normalize_env() {
  if [ -z "${OMNI_API_KEY:-}" ] && [ -n "${MIMO_API_KEY:-}" ]; then
    export OMNI_API_KEY="$MIMO_API_KEY"
  fi
  export OMNI_MODEL="${OMNI_MODEL:-xiaomi/mimo-v2.5}"
}

is_placeholder_value() {
  case "${1:-}" in
    ""|"填你的 API Key"|"填你的 MiMo API Key"|"YOUR_API_KEY"|"your-api-key"|"sk-xxxxx")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

run_agent_prepare_once() {
  if [ -f "$STATE_DIR/agent-prepare.done" ] && [ "${MILOCO_FORCE_INSTALL:-0}" != "1" ]; then
    if command -v miloco-cli >/dev/null 2>&1; then
      return
    fi
    warn "agent prepare marker exists but miloco-cli is missing; rerunning prepare for this container."
  fi

  log "Running agent prepare"
  bash "$INSTALL_SH" --agent-prepare --lang zh
  date -Is >"$STATE_DIR/agent-prepare.done"
}

configure_miloco_model_config() {
  local label="${OMNI_LABEL:-${OMNI_MODEL:-} @ ${OMNI_BASE_URL:-}}"

  if [ -z "${OMNI_API_KEY:-}${OMNI_BASE_URL:-}" ]; then
    log "No Miloco Omni model env supplied; keeping existing persisted Miloco model config if present."
    return
  fi

  if is_placeholder_value "${OMNI_API_KEY:-}" || [ -z "${OMNI_BASE_URL:-}" ] || [ -z "${OMNI_MODEL:-}" ]; then
    warn "Miloco Omni model env is incomplete; set OMNI_API_KEY, OMNI_BASE_URL and OMNI_MODEL."
    return
  fi

  log "Writing Miloco Omni model config"
  miloco-cli config set \
    model.omni.model "$OMNI_MODEL" \
    model.omni.base_url "$OMNI_BASE_URL" \
    model.omni.api_key "$OMNI_API_KEY" \
    --no-restart >/dev/null 2>&1 || warn "miloco-cli config set failed; writing Miloco model config directly."

  OMNI_LABEL="$label" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ.get("MILOCO_HOME", "~/.openclaw/miloco")).expanduser() / "config.json"
try:
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
except (json.JSONDecodeError, OSError):
    data = {}
if not isinstance(data, dict):
    data = {}

model = data.setdefault("model", {})
if not isinstance(model, dict):
    model = {}
    data["model"] = model

entry = {
    "label": os.environ["OMNI_LABEL"],
    "model": os.environ["OMNI_MODEL"],
    "base_url": os.environ["OMNI_BASE_URL"],
    "api_key": os.environ["OMNI_API_KEY"],
}
model["omni"] = entry

profiles = model.get("omni_profiles")
if not isinstance(profiles, list):
    profiles = []
for idx, item in enumerate(profiles):
    if isinstance(item, dict) and item.get("label") == entry["label"]:
        profiles[idx] = entry
        break
else:
    profiles.append(entry)
model["omni_profiles"] = profiles

path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.replace(path)
print(f"[OK] Miloco Omni model config written: {entry['label']}")
PY
}

run_agent_finish_if_ready() {
  if [ -f "$STATE_DIR/agent-finish.done" ] && [ "${MILOCO_FORCE_INSTALL:-0}" != "1" ]; then
    return
  fi

  if [ -z "${MILOCO_ACCOUNT_AUTH:-}" ]; then
    log "No account auth env supplied; skip Xiaomi account binding. Miloco model config is handled separately."
    return
  fi

  if is_placeholder_value "${OMNI_API_KEY:-}" || [ -z "${OMNI_BASE_URL:-}" ] || [ -z "${OMNI_MODEL:-}" ]; then
    warn "Account auth was supplied, but Omni model env is incomplete; skip agent finish until OMNI_API_KEY, OMNI_BASE_URL and OMNI_MODEL are set."
    return
  fi

  log "Running agent finish"
  bash "$INSTALL_SH" \
    --agent-finish \
    --lang zh \
    --account-auth "$MILOCO_ACCOUNT_AUTH" \
    --omni-api-key "$OMNI_API_KEY" \
    --omni-base-url "$OMNI_BASE_URL" \
    --omni-model "$OMNI_MODEL"
  date -Is >"$STATE_DIR/agent-finish.done"
}

configure_runtime_ports() {
  if command -v miloco-cli >/dev/null 2>&1; then
    miloco-cli config set server.url "$MILOCO_SERVER__URL" --no-restart >/dev/null 2>&1 || true
    miloco-cli config set agent.webhook_url "$MILOCO_AGENT__WEBHOOK_URL" --no-restart >/dev/null 2>&1 || true
  fi
}

find_openclaw_plugin_tgz() {
  find "$RUNTIME_DIR" "$MILOCO_HOME/.install-cache" -type f -name "miloco-openclaw-plugin-*.tgz" 2>/dev/null | head -n 1
}

install_openclaw_plugin() {
  local tgz
  tgz="$(find_openclaw_plugin_tgz || true)"
  if [ -z "$tgz" ]; then
    warn "No bundled miloco-openclaw-plugin tgz found; /miloco/webhook will be unavailable."
    return
  fi

  log "Installing OpenClaw Miloco plugin"
  if ! openclaw plugins install --force "$tgz" >/tmp/easy-miloco-openclaw-plugin-install.log 2>&1; then
    warn "OpenClaw plugin install failed; see /tmp/easy-miloco-openclaw-plugin-install.log"
    tail -n 80 /tmp/easy-miloco-openclaw-plugin-install.log 2>/dev/null || true
    return
  fi

  openclaw config set 'plugins.entries["miloco-openclaw-plugin"].enabled' true >/tmp/easy-miloco-openclaw-plugin-enable.log 2>&1 \
    || warn "Failed to enable miloco-openclaw-plugin."
  openclaw config set 'plugins.entries["miloco-openclaw-plugin"].hooks.allowConversationAccess' true >>/tmp/easy-miloco-openclaw-plugin-enable.log 2>&1 \
    || warn "Failed to enable miloco-openclaw-plugin conversation access."
}

nas_host_hint() {
  if [ -n "${NAS_HOST:-}" ]; then
    printf '%s' "$NAS_HOST"
    return
  fi
  if command -v ip >/dev/null 2>&1; then
    ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}'
  elif command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | awk '{print $1}'
  fi
}

configure_openclaw_gateway() {
  python3 - "$OPENCLAW_BIND" "$OPENCLAW_AUTH" "$OPENCLAW_INTERNAL_PORT" "$(nas_host_hint)" <<'PY'
import json
import secrets
import sys
from pathlib import Path

bind, auth, port, host = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4].strip()
path = Path.home() / ".openclaw" / "openclaw.json"
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

gateway = data.setdefault("gateway", {})
gateway["mode"] = "local"
gateway["bind"] = bind
gateway["port"] = port
auth_config = gateway.setdefault("auth", {})
auth_config["mode"] = auth
if auth == "token" and not auth_config.get("token"):
    auth_config["token"] = secrets.token_hex(24)

control_ui = gateway.setdefault("controlUi", {})
control_ui["allowInsecureAuth"] = True
control_ui["dangerouslyDisableDeviceAuth"] = True
control_ui["dangerouslyAllowHostHeaderOriginFallback"] = True

origins = set(control_ui.get("allowedOrigins") or [])
origins.update({
    f"http://localhost:{port}",
    f"http://127.0.0.1:{port}",
})
if host:
    origins.add(f"http://{host}:{port}")
control_ui["allowedOrigins"] = sorted(origins)

path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

configure_openclaw_chat_model() {
  local provider="${OPENCLAW_CHAT_PROVIDER:-}"
  local model="${OPENCLAW_CHAT_MODEL:-}"
  local base_url="${OPENCLAW_CHAT_BASE_URL:-}"
  local api_key="${OPENCLAW_CHAT_API_KEY:-}"
  local api="${OPENCLAW_CHAT_API:-}"
  local explicit_chat_env="${OPENCLAW_CHAT_PROVIDER:-}${OPENCLAW_CHAT_MODEL:-}${OPENCLAW_CHAT_BASE_URL:-}${OPENCLAW_CHAT_API_KEY:-}${OPENCLAW_CHAT_API:-}"

  if [ -z "$explicit_chat_env" ]; then
    log "No OpenClaw chat model env supplied; keeping existing OpenClaw agent model config if present."
    return
  fi

  if is_placeholder_value "$api_key" || [ -z "$model" ] || [ -z "$base_url" ]; then
    warn "OpenClaw chat model env is incomplete; set OPENCLAW_CHAT_MODEL, OPENCLAW_CHAT_BASE_URL and OPENCLAW_CHAT_API_KEY. OPENCLAW_CHAT_PROVIDER and OPENCLAW_CHAT_API are optional."
    return
  fi

  python3 - "$provider" "$model" "$base_url" "$api_key" "$api" "$OPENCLAW_CHAT_MAX_TOKENS" "$OPENCLAW_CHAT_TIMEOUT_SECONDS" "$OPENCLAW_CHAT_CONTEXT_WINDOW" <<'PY'
import json
import re
import sys
from urllib.parse import urlparse
from pathlib import Path

provider_arg = sys.argv[1].strip()
model_arg = sys.argv[2].strip()
base_url = sys.argv[3].strip()
api_key = sys.argv[4].strip()
api_arg = sys.argv[5].strip()
max_tokens = int(sys.argv[6])
timeout_seconds = int(sys.argv[7])
context_window = int(sys.argv[8])

def split_model(value: str) -> tuple[str, str]:
    value = (value or "").strip()
    if "/" not in value:
        return "", value
    prefix, rest = value.split("/", 1)
    return prefix.strip(), rest.strip()

def normalize_provider(value: str, base_url: str, model_id: str) -> str:
    low = (value or "").strip().lower().replace("_", "-")
    if low in {"mimo", "xiaomi-mimo", "xiaomi-tokenplan", "xiaomi-token-plan"}:
        return "xiaomi-token-plan" if "token-plan" in f"{base_url} {model_id}".lower() else "xiaomi"
    if low in {"deepseek-api", "deepseek-chat"}:
        return "deepseek"
    if low in {"sense", "sensetime", "sensenova", "sense-nova"}:
        return "sensenova"
    if low:
        return low
    return ""

def normalize_api(value: str) -> str:
    low = (value or "").strip().lower().replace("_", "-")
    aliases = {
        "openai": "openai-completions",
        "openai-chat": "openai-completions",
        "chat-completions": "openai-completions",
        "openai-completions": "openai-completions",
        "anthropic": "anthropic-messages",
        "claude": "anthropic-messages",
        "anthropic-messages": "anthropic-messages",
        "responses": "openai-responses",
        "openai-responses": "openai-responses",
    }
    return aliases.get(low, low)

def infer_provider(explicit: str, model_prefix: str, base_url: str, model_id: str) -> str:
    text = f"{base_url} {model_prefix} {model_id}".lower()
    url_text = (base_url or "").lower()
    explicit = normalize_provider(explicit, base_url, model_id)
    prefix = normalize_provider(model_prefix, base_url, model_id)
    if explicit:
        if explicit == "xiaomi" and "token-plan" in text:
            return "xiaomi-token-plan"
        return explicit
    if "xiaomimimo" in url_text or "token-plan" in url_text:
        return "xiaomi-token-plan" if "token-plan" in url_text else "xiaomi"
    if "sensenova" in url_text or "sensetime" in url_text:
        return "sensenova"
    if "minimaxi" in url_text or "minimax" in url_text:
        return "minimax"
    if "deepseek" in url_text:
        return "deepseek"
    if prefix:
        if prefix == "xiaomi" and "token-plan" in text:
            return "xiaomi-token-plan"
        return prefix
    if "xiaomimimo" in text or model_id.startswith(("mimo-", "mimo_")):
        return "xiaomi-token-plan" if "token-plan" in text else "xiaomi"
    if "deepseek" in text:
        return "deepseek"
    if "minimaxi" in text or "minimax" in text:
        return "minimax"
    if "sensenova" in text or "sensetime" in text:
        return "sensenova"
    if "moonshot" in text or "kimi" in text:
        return "moonshot"
    if "dashscope" in text or "qwen" in text or "aliyuncs" in text:
        return "qwen"
    host = urlparse(base_url).hostname or "openai-compatible"
    safe = re.sub(r"[^a-z0-9-]+", "-", host.lower()).strip("-")
    return safe or "openai-compatible"

def infer_api(explicit: str, provider_id: str, base_url: str) -> str:
    api = normalize_api(explicit)
    if api:
        return api
    parsed = urlparse(base_url)
    text = f"{provider_id} {parsed.netloc} {parsed.path}".lower()
    if provider_id == "sensenova":
        return "openai-completions"
    if "anthropic" in text:
        return "anthropic-messages"
    if provider_id == "minimax" and "minimax" in text:
        return "anthropic-messages"
    return "openai-completions"

model_prefix, model_id = split_model(model_arg)
provider_id = infer_provider(provider_arg, model_prefix, base_url, model_id)
api = infer_api(api_arg, provider_id, base_url)

chat_ref = f"{provider_id}/{model_id}"
home = Path.home()
openclaw_config = home / ".openclaw" / "openclaw.json"
agent_models = home / ".openclaw" / "agents" / "main" / "agent" / "models.json"

def load_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

def as_dict(parent, key):
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value

def provider_payload():
    return {
        "baseUrl": base_url,
        "apiKey": api_key,
        "api": api,
        "timeoutSeconds": timeout_seconds,
        "contextWindow": context_window,
        "contextTokens": context_window,
        "models": [
            {
                "id": model_id,
                "name": model_id,
                "input": ["text"],
                "contextWindow": context_window,
                "contextTokens": context_window,
                "maxTokens": max_tokens,
            }
        ],
    }

data = load_json(openclaw_config)
defaults = as_dict(as_dict(data, "agents"), "defaults")
as_dict(defaults, "model")["primary"] = chat_ref
agent_row = as_dict(as_dict(defaults, "models"), chat_ref)
as_dict(agent_row, "params")["maxTokens"] = max_tokens

models = as_dict(data, "models")
models["mode"] = "merge"
as_dict(models, "providers")[provider_id] = provider_payload()

openclaw_config.parent.mkdir(parents=True, exist_ok=True)
openclaw_config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

agent_data = load_json(agent_models)
agent_data.setdefault("providers", {})[provider_id] = provider_payload()
agent_models.parent.mkdir(parents=True, exist_ok=True)
agent_models.write_text(json.dumps(agent_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(f"[OK] OpenClaw chat model configured: primary={chat_ref}")
PY
}

openclaw_dashboard_url() {
  python3 - "$OPENCLAW_PORT" "$(nas_host_hint)" <<'PY'
import json
import sys
from pathlib import Path
from urllib.parse import quote

port, host = int(sys.argv[1]), sys.argv[2].strip() or "127.0.0.1"
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
PY
}

public_host_hint() {
  if [ -n "${NAS_HOST:-}" ]; then
    printf '%s' "$NAS_HOST"
  else
    printf '<NAS-IP>'
  fi
}

openclaw_token() {
  python3 - <<'PY'
import json
from pathlib import Path

path = Path.home() / ".openclaw" / "openclaw.json"
if not path.exists():
    raise SystemExit(0)
data = json.loads(path.read_text(encoding="utf-8"))
auth = data.get("gateway", {}).get("auth", {})
if auth.get("mode") == "token":
    print(auth.get("token") or "")
PY
}

start_openclaw_proxy() {
  local token proxy_file
  token="$(openclaw_token)"
  proxy_file="/tmp/easy-miloco-openclaw-proxy.js"
  cat >"$proxy_file" <<'JS'
const http = require("http");
const net = require("net");

const publicPort = Number(process.env.OPENCLAW_PUBLIC_PORT || "18789");
const targetPort = Number(process.env.OPENCLAW_INTERNAL_PORT || "18790");
const targetHost = "127.0.0.1";
const token = process.env.OPENCLAW_PROXY_TOKEN || "";

function respondStarting(req, res, message) {
  const isHealth = req.url === "/health" || req.url.startsWith("/health?");
  if (isHealth) {
    res.writeHead(503, {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    });
    res.end(JSON.stringify({ ok: false, status: "starting", message }));
    return;
  }

  const body = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="refresh" content="8" />
  <title>OpenClaw 正在启动</title>
  <style>
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #111827; color: #f9fafb; }
    main { min-height: 100vh; display: grid; place-items: center; padding: 24px; box-sizing: border-box; }
    section { width: min(520px, 100%); border: 1px solid #374151; border-radius: 8px; padding: 24px; background: #1f2937; }
    h1 { margin: 0 0 12px; font-size: 22px; line-height: 1.3; }
    p { margin: 8px 0; color: #d1d5db; line-height: 1.7; }
    code { color: #bfdbfe; }
  </style>
</head>
<body>
  <main>
    <section>
      <h1>OpenClaw 正在启动</h1>
      <p>Docker 项目已经开始运行，OpenClaw 网关还在初始化。页面会自动刷新。</p>
      <p>首次部署或刚重建项目时通常需要再等 <code>1-2 分钟</code>。如果一直停在这里，请查看 Docker 日志。</p>
    </section>
  </main>
</body>
</html>`;
  res.writeHead(503, {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(body);
}

function proxyHeaders(headers) {
  const out = { ...headers };
  out.host = `${targetHost}:${targetPort}`;
  if (out.origin) out.origin = `http://${targetHost}:${targetPort}`;
  if (out.referer) out.referer = String(out.referer).replace(`:${publicPort}`, `:${targetPort}`);
  return out;
}

function tokenRedirectUrl(req) {
  if (!token) return "";
  const host = req.headers.host || `127.0.0.1:${publicPort}`;
  const parsed = new URL(req.url || "/", `http://${host}`);
  const path = parsed.pathname || "/";
  const isRoot = path === "/";
  const isChat = path === "/chat" || path === "/chat/";
  if (!isRoot && !isChat) return "";
  if (parsed.searchParams.get("easy_miloco_token") === "1") return "";
  if (isRoot) {
    parsed.pathname = "/chat";
    if (!parsed.searchParams.get("session")) parsed.searchParams.set("session", "main");
  }
  parsed.searchParams.set("easy_miloco_token", "1");
  parsed.hash = `token=${encodeURIComponent(token)}`;
  return parsed.toString();
}

const server = http.createServer((req, res) => {
  const location = tokenRedirectUrl(req);
  if (location) {
    res.writeHead(302, { Location: location, "Cache-Control": "no-store" });
    res.end();
    return;
  }

  const upstream = http.request(
    {
      hostname: targetHost,
      port: targetPort,
      method: req.method,
      path: req.url,
      headers: proxyHeaders(req.headers),
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
      upstreamRes.pipe(res);
    },
  );
  upstream.on("error", (err) => {
    respondStarting(req, res, `OpenClaw gateway is starting: ${err.message}`);
  });
  req.pipe(upstream);
});

server.on("upgrade", (req, socket, head) => {
  const upstream = net.connect(targetPort, targetHost, () => {
    upstream.write(`${req.method} ${req.url} HTTP/${req.httpVersion}\r\n`);
    const headers = proxyHeaders(req.headers);
    for (const [key, value] of Object.entries(headers)) {
      if (Array.isArray(value)) {
        for (const row of value) upstream.write(`${key}: ${row}\r\n`);
      } else if (value !== undefined) {
        upstream.write(`${key}: ${value}\r\n`);
      }
    }
    upstream.write("\r\n");
    if (head && head.length) upstream.write(head);
    socket.pipe(upstream);
    upstream.pipe(socket);
  });
  upstream.on("error", () => socket.destroy());
  socket.on("error", () => upstream.destroy());
});

server.listen(publicPort, "0.0.0.0", () => {
  console.log(`OpenClaw proxy listening on 0.0.0.0:${publicPort}, upstream ${targetHost}:${targetPort}`);
});
JS
  nohup env \
    OPENCLAW_PUBLIC_PORT="$OPENCLAW_PORT" \
    OPENCLAW_INTERNAL_PORT="$OPENCLAW_INTERNAL_PORT" \
    OPENCLAW_PROXY_TOKEN="$token" \
    node "$proxy_file" >/tmp/easy-miloco-openclaw-proxy.log 2>&1 &
}

prepare_openclaw_public_proxy() {
  log "Preparing OpenClaw public proxy"
  configure_openclaw_chat_model
  configure_openclaw_gateway
  start_openclaw_proxy
}

ensure_openclaw_gateway() {
  local probe
  for _ in $(seq 1 60); do
    probe="$(curl -fsS -m 2 "http://127.0.0.1:${OPENCLAW_PORT}/health" 2>/dev/null || true)"
    if [ -n "$probe" ]; then
      log "OpenClaw gateway is healthy"
      return 0
    fi
    sleep 1
  done

  warn "OpenClaw gateway did not become healthy; continuing so logs stay available."
  tail -n 80 /tmp/easy-miloco-openclaw-run.log 2>/dev/null || true
  tail -n 80 /tmp/easy-miloco-openclaw-proxy.log 2>/dev/null || true
  return 0
}

start_runtime() {
  log "Starting Miloco service"
  ensure_miloco_service

  log "Starting OpenClaw gateway"
  nohup openclaw gateway \
    --dev \
    --force \
    --bind "$OPENCLAW_BIND" \
    --auth "$OPENCLAW_AUTH" \
    --port "$OPENCLAW_INTERNAL_PORT" \
    run >/tmp/easy-miloco-openclaw-run.log 2>&1 &
  ensure_openclaw_gateway
}

ensure_miloco_service() {
  local attempt probe
  for attempt in 1 2 3; do
    miloco-cli service start >/tmp/easy-miloco-service-start.log 2>&1 \
      || miloco-cli service restart >/tmp/easy-miloco-service-restart.log 2>&1 \
      || true

    for _ in $(seq 1 30); do
      probe="$(curl -fsS -m 2 "http://127.0.0.1:${MILOCO_PORT}/health" 2>/dev/null || true)"
      if [ -n "$probe" ]; then
        log "Miloco service is healthy"
        return 0
      fi
      sleep 1
    done

    warn "Miloco service did not become healthy on attempt $attempt; retrying."
    miloco-cli service restart >/tmp/easy-miloco-service-retry.log 2>&1 || true
  done

  warn "Miloco service is not healthy after retries; continuing so logs stay available."
  return 0
}

validate_runtime() {
  local pass=0 warn_count=0 fail=0 http_code openclaw_token webhook_body
  printf '== easy-miloco NAS Docker validation ==\n'

  if curl -fsS -m 5 "http://127.0.0.1:${MILOCO_PORT}/health" >/tmp/easy-miloco-health.json 2>/dev/null; then
    printf '[PASS] miloco.health %s\n' "$(cat /tmp/easy-miloco-health.json)"
    pass=$((pass + 1))
  else
    printf '[FAIL] miloco.health\n'
    fail=$((fail + 1))
  fi

  if curl -fsS -m 5 "http://127.0.0.1:${OPENCLAW_PORT}/health" >/tmp/easy-openclaw-health.json 2>/dev/null; then
    printf '[PASS] openclaw.proxy %s\n' "$(cat /tmp/easy-openclaw-health.json)"
    pass=$((pass + 1))
  else
    printf '[FAIL] openclaw.proxy\n'
    fail=$((fail + 1))
  fi

  http_code="$(curl -sSL -o /dev/null -w '%{http_code}' -m 5 "http://127.0.0.1:${OPENCLAW_PORT}/chat?session=main" 2>/dev/null || true)"
  if [ "$http_code" = "200" ]; then
    printf '[PASS] openclaw.chat HTTP %s\n' "$http_code"
    pass=$((pass + 1))
  else
    printf '[FAIL] openclaw.chat HTTP %s\n' "${http_code:-none}"
    fail=$((fail + 1))
  fi

  openclaw_token="$(openclaw_token)"
  webhook_body="$(curl -sS -m 5 -X POST \
    -H "Authorization: Bearer ${openclaw_token}" \
    -H "Content-Type: application/json" \
    -d '{"action":"__probe__","payload":{}}' \
    "http://127.0.0.1:${OPENCLAW_PORT}/miloco/webhook" 2>/dev/null || true)"
  if printf '%s' "$webhook_body" | grep -q "Action '__probe__' not found"; then
    printf '[PASS] openclaw.miloco_webhook registered\n'
    pass=$((pass + 1))
  else
    printf '[FAIL] openclaw.miloco_webhook %s\n' "${webhook_body:-no response}"
    fail=$((fail + 1))
  fi

  if [ -s "$MILOCO_HOME/models/det_4C.onnx" ] && [ -s "$MILOCO_HOME/models/human_body_reid_v2.onnx" ]; then
    printf '[PASS] miloco.models %s files in %s\n' "$(find "$MILOCO_HOME/models" -maxdepth 1 -type f | wc -l | tr -d ' ')" "$MILOCO_HOME/models"
    pass=$((pass + 1))
  else
    printf '[FAIL] miloco.models required perception models missing in %s\n' "$MILOCO_HOME/models"
    fail=$((fail + 1))
  fi

  if [ -n "${OPENCLAW_CHAT_PROVIDER:-}" ] || [ -n "${OPENCLAW_CHAT_MODEL:-}" ] || [ -n "${OPENCLAW_CHAT_BASE_URL:-}" ] || [ -n "${OPENCLAW_CHAT_API_KEY:-}" ] || [ -n "${OPENCLAW_CHAT_API:-}" ]; then
    if is_placeholder_value "${OPENCLAW_CHAT_API_KEY:-}"; then
      printf '[FAIL] openclaw.chat_model OPENCLAW_CHAT_API_KEY is missing or placeholder\n'
      fail=$((fail + 1))
    elif python3 - "${OPENCLAW_CHAT_PROVIDER:-}" "${OPENCLAW_CHAT_MODEL:-}" "${OPENCLAW_CHAT_BASE_URL:-}" "${OPENCLAW_CHAT_API:-}" <<'PY'
import json
import re
import sys
from urllib.parse import urlparse
from pathlib import Path

provider_arg = sys.argv[1].strip()
model_arg = sys.argv[2].strip()
base_url = sys.argv[3].strip()
api_arg = sys.argv[4].strip()

def split_model(value):
    if "/" not in value:
        return "", value
    prefix, rest = value.split("/", 1)
    return prefix.strip(), rest.strip()

def normalize_provider(value, base_url, model):
    low = (value or "").strip().lower().replace("_", "-")
    if low in {"mimo", "xiaomi-mimo", "xiaomi-tokenplan", "xiaomi-token-plan"}:
        return "xiaomi-token-plan" if "token-plan" in f"{base_url} {model}".lower() else "xiaomi"
    if low in {"deepseek-api", "deepseek-chat"}:
        return "deepseek"
    if low in {"sense", "sensetime", "sensenova", "sense-nova"}:
        return "sensenova"
    return low

def normalize_api(value):
    low = (value or "").strip().lower().replace("_", "-")
    aliases = {
        "openai": "openai-completions",
        "openai-chat": "openai-completions",
        "chat-completions": "openai-completions",
        "openai-completions": "openai-completions",
        "anthropic": "anthropic-messages",
        "claude": "anthropic-messages",
        "anthropic-messages": "anthropic-messages",
        "responses": "openai-responses",
        "openai-responses": "openai-responses",
    }
    return aliases.get(low, low)

def infer_provider(explicit, prefix, base_url, model):
    text = f"{base_url} {prefix} {model}".lower()
    url_text = (base_url or "").lower()
    explicit = normalize_provider(explicit, base_url, model)
    prefix = normalize_provider(prefix, base_url, model)
    if explicit:
        return "xiaomi-token-plan" if explicit == "xiaomi" and "token-plan" in text else explicit
    if "xiaomimimo" in url_text or "token-plan" in url_text:
        return "xiaomi-token-plan" if "token-plan" in url_text else "xiaomi"
    if "sensenova" in url_text or "sensetime" in url_text:
        return "sensenova"
    if "minimaxi" in url_text or "minimax" in url_text:
        return "minimax"
    if "deepseek" in url_text:
        return "deepseek"
    if prefix:
        return "xiaomi-token-plan" if prefix == "xiaomi" and "token-plan" in text else prefix
    if "xiaomimimo" in text or model.startswith(("mimo-", "mimo_")):
        return "xiaomi-token-plan" if "token-plan" in text else "xiaomi"
    if "deepseek" in text:
        return "deepseek"
    if "minimaxi" in text or "minimax" in text:
        return "minimax"
    if "sensenova" in text or "sensetime" in text:
        return "sensenova"
    if "moonshot" in text or "kimi" in text:
        return "moonshot"
    if "dashscope" in text or "qwen" in text or "aliyuncs" in text:
        return "qwen"
    host = urlparse(base_url).hostname or "openai-compatible"
    return re.sub(r"[^a-z0-9-]+", "-", host.lower()).strip("-") or "openai-compatible"

def infer_api(explicit, provider, base_url):
    api = normalize_api(explicit)
    if api:
        return api
    parsed = urlparse(base_url)
    text = f"{provider} {parsed.netloc} {parsed.path}".lower()
    if provider == "sensenova":
        return "openai-completions"
    if "anthropic" in text:
        return "anthropic-messages"
    if provider == "minimax" and "minimax" in text:
        return "anthropic-messages"
    return "openai-completions"

prefix, model = split_model(model_arg)
provider = infer_provider(provider_arg, prefix, base_url, model)
api = infer_api(api_arg, provider, base_url)
expected = f"{provider}/{model}"

cfg = Path.home() / ".openclaw" / "openclaw.json"
agent = Path.home() / ".openclaw" / "agents" / "main" / "agent" / "models.json"
data = json.loads(cfg.read_text(encoding="utf-8"))
agent_data = json.loads(agent.read_text(encoding="utf-8"))
primary = data.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")
provider_data = data.get("models", {}).get("providers", {}).get(provider)
agent_provider = agent_data.get("providers", {}).get(provider)
if primary != expected:
    raise SystemExit(f"primary={primary!r}, expected={expected!r}")
if not isinstance(provider_data, dict) or not provider_data.get("apiKey") or not provider_data.get("baseUrl"):
    raise SystemExit("global provider missing apiKey/baseUrl")
if not isinstance(agent_provider, dict) or not agent_provider.get("apiKey") or not agent_provider.get("baseUrl"):
    raise SystemExit("agent provider missing apiKey/baseUrl")
if provider_data.get("api") != api or agent_provider.get("api") != api:
    raise SystemExit("provider api mismatch")
rows = provider_data.get("models") or []
if not any(isinstance(row, dict) and row.get("id") == model for row in rows):
    raise SystemExit("model row missing")
print(expected)
PY
    then
      printf '[PASS] openclaw.chat_model configured\n'
      pass=$((pass + 1))
    else
      printf '[FAIL] openclaw.chat_model config missing or invalid\n'
      fail=$((fail + 1))
    fi
  else
    printf '[WARN] openclaw.chat_model OPENCLAW_CHAT_* not supplied\n'
    warn_count=$((warn_count + 1))
  fi

  if [ "$fail" -eq 0 ]; then
    printf 'BASIC_READY=yes\n'
  else
    printf 'BASIC_READY=no\n'
  fi
  printf 'PASS_COUNT=%s\nWARN_COUNT=%s\nFAIL_COUNT=%s\n' "$pass" "$warn_count" "$fail"
}

print_usage() {
  local public_host
  public_host="$(public_host_hint)"
  cat <<EOF

== easy-miloco NAS Docker ==
Miloco 面板:   http://${public_host}:${MILOCO_PORT}/
OpenClaw 对话: http://${public_host}:${OPENCLAW_PORT}/  （自动带网关令牌）
配置目录:      ${MILOCO_HOME}
持久数据:      /data
运行载荷:      ${RUNTIME_DIR}
OpenClaw bind: ${OPENCLAW_BIND}
OpenClaw 内部: http://127.0.0.1:${OPENCLAW_INTERNAL_PORT}/

如果日志里显示 <NAS-IP>，请在浏览器里替换成 NAS 的局域网 IP。
如需写入账号/模型环境变量，补齐 .env 后执行: ./manage.sh restart
常用入口: ./manage.sh urls | ./manage.sh status | ./manage.sh logs

EOF
}

keep_alive() {
  log "Container is ready; following logs."
  while true; do
    sleep 3600 &
    wait $!
  done
}

link_root_state_dir() {
  local name target root_path
  [ "$HOME" = "/root" ] && return
  mkdir -p /root

  for name in .local .cache; do
    target="$HOME/$name"
    root_path="/root/$name"
    mkdir -p "$target"

    if [ -L "$root_path" ]; then
      [ "$(readlink "$root_path")" = "$target" ] && continue
      rm -f "$root_path"
    elif [ -d "$root_path" ]; then
      cp -a "$root_path"/. "$target"/ 2>/dev/null || true
      rm -rf "$root_path"
    elif [ -e "$root_path" ]; then
      rm -rf "$root_path"
    fi

    ln -s "$target" "$root_path"
  done
}

main() {
  mkdir -p "$STATE_DIR" "$MILOCO_HOME" "$HOME/.local/bin" "$HOME/.openclaw"
  link_root_state_dir
  normalize_env
  download_runtime_files
  prime_payload_cache
  sync_bundled_models
  install_openclaw_plugin
  prepare_openclaw_public_proxy
  run_agent_prepare_once
  configure_miloco_model_config
  run_agent_finish_if_ready
  configure_runtime_ports
  start_runtime
  validate_runtime
  print_usage
  keep_alive
}

main "$@"
