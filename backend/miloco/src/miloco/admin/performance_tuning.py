from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import psutil
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from miloco.config import get_settings
from miloco.middleware.exceptions import AgentWebhookException
from miloco.node_monitor.router import get_resource_monitor
from miloco.observability.metrics_db import connect
from miloco.observability.stats import (
    drop_series,
    gate_pass_rate,
    omni_error_series,
    rtf_series,
    stage_percentiles,
    summary,
)
from miloco.utils.agent_client import call_agent_webhook, run_agent_turn
from miloco.utils.agent_config import update_shared_config

logger = logging.getLogger(__name__)

ConfigValue = str | int | float | bool


class PerformanceConfigApplyBody(BaseModel):
    values: dict[str, ConfigValue] = Field(default_factory=dict)


class PerformanceSafeModeBody(BaseModel):
    limit_realtime_cameras: bool = True


@dataclass(frozen=True)
class ConfigSpec:
    path: str
    type: Literal["integer", "number", "boolean", "string"]
    label: str
    description: str
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: tuple[ConfigValue, ...] | None = None
    impact: str = ""


CONFIG_SPECS: tuple[ConfigSpec, ...] = (
    ConfigSpec(
        "camera.frame_interval",
        "integer",
        "Camera frame interval",
        "Camera SDK frame interval in milliseconds.",
        500,
        5000,
        100,
        impact="Higher values reduce decode CPU and camera traffic.",
    ),
    ConfigSpec(
        "camera.max_cache_images",
        "integer",
        "Camera cache images",
        "Maximum decoded images kept per camera.",
        2,
        20,
        1,
        impact="Lower values reduce RSS at the cost of shorter history.",
    ),
    ConfigSpec(
        "camera.video_quality",
        "string",
        "Camera stream quality",
        "Default camera stream quality used when starting camera streams.",
        options=("LOW", "HIGH"),
        impact="LOW reduces camera bandwidth, decode CPU, and image buffer memory; HIGH keeps more visual detail.",
    ),
    ConfigSpec(
        "camera.enable_audio_perception",
        "boolean",
        "Camera audio perception",
        "Subscribe to decoded camera audio streams so audio can trigger perception and be uploaded to Omni.",
        impact=(
            "Disabling saves camera stream, audio decode, audio gate, and VAD CPU; "
            "video perception, identity, and visual Omni remain available."
        ),
    ),
    ConfigSpec(
        "camera.enable_hw_accel",
        "boolean",
        "Hardware video decode",
        "Try hardware video decoders for camera streams when the NAS exposes them.",
        impact="Keeps image quality unchanged; if hardware is unavailable Miloco falls back to software decoding.",
    ),
    ConfigSpec(
        "perception.collect.window_size",
        "integer",
        "Collect window size",
        "Perception collection window length in seconds.",
        2,
        60,
        1,
        impact="Larger windows reduce scheduling pressure and Omni frequency but increase latency.",
    ),
    ConfigSpec(
        "perception.collect.max_windows",
        "integer",
        "Collect max windows",
        "Maximum queued windows before the full_action policy runs.",
        1,
        10,
        1,
        impact="Lower values cap memory and backlog on low-end NAS devices.",
    ),
    ConfigSpec(
        "perception.collect.full_action",
        "string",
        "Window full action",
        "Backlog policy when collection windows are full.",
        options=("clear", "drop", "keep"),
        impact="clear/drop protect runtime resources; keep preserves data but risks backlog.",
    ),
    ConfigSpec(
        "perception.engine.input.fps",
        "integer",
        "Pipeline FPS",
        "Frame rate used by the perception pipeline and tracker.",
        1,
        8,
        1,
        impact="Lower values reduce decode, tracking, and identity CPU.",
    ),
    ConfigSpec(
        "perception.engine.input.omni_fps",
        "integer",
        "Omni FPS",
        "Video frame rate sent to Omni.",
        1,
        4,
        1,
        impact="Lower values reduce Omni payload and latency.",
    ),
    ConfigSpec(
        "perception.engine.input.period_sec",
        "integer",
        "Pipeline period",
        "Seconds between perception pipeline cycles.",
        4,
        60,
        1,
        impact="Higher values reduce steady CPU and Omni calls but make perception less real-time.",
    ),
    ConfigSpec(
        "perception.engine.gate.hold_duration_sec",
        "number",
        "Gate hold duration",
        "Seconds to keep visual analysis active after a gate pass.",
        0,
        360,
        1,
        impact="Lower values stop long video hold bursts; 0 is safest for low-end NAS.",
    ),
    ConfigSpec(
        "perception.engine.omni.allow_h265_remux",
        "boolean",
        "Experimental H.265 remux",
        "Allow H.265 camera packets to be remuxed directly for Omni uploads.",
        impact=(
            "Can avoid CPU-heavy re-encoding on H.265 cameras, but remains experimental "
            "because long H.265 windows previously produced empty Omni answers."
        ),
    ),
    ConfigSpec(
        "perception.engine.identity.tracking_service_mode",
        "string",
        "Tracking mode",
        "Identity tracking service mode.",
        options=("mock", "real", "deep_sort"),
        impact="mock is lightest; deep_sort preserves stronger continuity at higher CPU cost.",
    ),
    ConfigSpec(
        "perception.engine.identity_engine.enabled",
        "boolean",
        "Identity engine",
        "Enable or disable identity recognition engine.",
        impact="Disabling identity saves CPU/RSS but removes identity recognition.",
    ),
    ConfigSpec(
        "perception.engine.identity_engine.deep_sort.mode",
        "string",
        "DeepSORT mode",
        "DeepSORT execution mode.",
        options=("fast", "normal"),
        impact="fast skips some ReID work for static tracks.",
    ),
    ConfigSpec(
        "perception.engine.identity_engine.deep_sort.human_reid_skip_windows",
        "integer",
        "ReID skip windows",
        "Static human ReID is run once per N windows in fast mode.",
        1,
        20,
        1,
        impact="Higher values reduce ReID CPU with slower identity refresh.",
    ),
    ConfigSpec(
        "perception.snapshot_max_disk_mb",
        "integer",
        "Snapshot disk cap",
        "Maximum snapshot/clip disk usage in MB.",
        256,
        20000,
        128,
        impact="Lower values reduce disk pressure; old clips expire sooner.",
    ),
    ConfigSpec(
        "perf.enabled",
        "boolean",
        "Perf metrics",
        "Enable runtime performance metrics collection.",
        impact="Keeping this on is recommended while tuning; disabling saves a small amount of overhead.",
    ),
    ConfigSpec(
        "perf.retention.traces_days",
        "integer",
        "Trace retention days",
        "Retention for traces and trace devices.",
        1,
        30,
        1,
        impact="Lower retention reduces DB size and cleanup work.",
    ),
    ConfigSpec(
        "perf.retention.events_days",
        "integer",
        "Event retention days",
        "Retention for observability events.",
        1,
        30,
        1,
        impact="Lower retention reduces DB size.",
    ),
    ConfigSpec(
        "perf.retention.agent_runs_days",
        "integer",
        "Agent run retention days",
        "Retention for agent run metadata.",
        1,
        30,
        1,
        impact="Lower retention reduces DB size.",
    ),
    ConfigSpec(
        "perf.retention.trace_jsonl_days",
        "integer",
        "Agent trace JSONL retention days",
        "Retention for debug agent trace dumps.",
        1,
        30,
        1,
        impact="Lower retention reduces disk usage.",
    ),
    ConfigSpec(
        "perf.retention.omni_log_days",
        "integer",
        "Omni log retention days",
        "Retention for Omni interaction logs.",
        1,
        30,
        1,
        impact="Lower retention reduces disk usage.",
    ),
)
SPEC_BY_PATH = {spec.path: spec for spec in CONFIG_SPECS}

REQUIRED_DIAGNOSIS_KEYS = {
    "summary",
    "bottlenecks",
    "recommended_preset",
    "recommended_config",
    "expected_tradeoffs",
    "risk_level",
    "requires_backend_restart",
}

DEFAULT_MAX_ENABLED_CAMERAS = 4

LOW_POWER_SAFE_MODE_VALUES: dict[str, ConfigValue] = {
    "camera.frame_interval": 5000,
    "camera.max_cache_images": 2,
    "camera.video_quality": "LOW",
    "camera.enable_audio_perception": False,
    "camera.enable_hw_accel": True,
    "perception.collect.window_size": 60,
    "perception.collect.max_windows": 1,
    "perception.collect.full_action": "clear",
    "perception.engine.input.fps": 1,
    "perception.engine.input.omni_fps": 1,
    "perception.engine.input.period_sec": 60,
    "perception.engine.gate.hold_duration_sec": 0,
    "perception.engine.omni.allow_h265_remux": False,
    "perception.engine.identity.tracking_service_mode": "mock",
    "perception.engine.identity_engine.enabled": False,
    "perception.engine.identity_engine.deep_sort.mode": "fast",
    "perception.engine.identity_engine.deep_sort.human_reid_skip_windows": 20,
    "perception.snapshot_max_disk_mb": 256,
}


def _settings_dict() -> dict[str, Any]:
    settings = get_settings()
    if hasattr(settings, "model_dump"):
        return settings.model_dump(mode="json")
    return settings.dict()


def _get_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _env_var_for_path(path: str) -> str:
    return f"MILOCO_{path.replace('.', '__').upper()}"


def _env_override_for_path(path: str) -> dict[str, Any]:
    expected = _env_var_for_path(path)
    for key, value in os.environ.items():
        if key.upper() == expected:
            return {
                "active": True,
                "env_var": key,
                "value": value,
                "message": (
                    f"{key} is set and overrides config.json until the backend "
                    "is started without this environment variable."
                ),
            }
    return {"active": False, "env_var": expected, "value": None, "message": None}


def _set_path(data: dict[str, Any], path: str, value: ConfigValue) -> None:
    cur = data
    parts = path.split(".")
    for part in parts[:-1]:
        nxt = cur.setdefault(part, {})
        if not isinstance(nxt, dict):
            raise ValueError(f"cannot set nested value under non-object path: {part}")
        cur = nxt
    cur[parts[-1]] = value


def _coerce_value(spec: ConfigSpec, value: Any) -> ConfigValue:
    if spec.type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("must be a boolean")
        out: ConfigValue = value
    elif spec.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("must be an integer")
        out = value
    elif spec.type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("must be a number")
        out = float(value)
    else:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        out = value

    if spec.options is not None and out not in spec.options:
        raise ValueError(f"must be one of {list(spec.options)}")
    if isinstance(out, (int, float)) and not isinstance(out, bool):
        if spec.minimum is not None and out < spec.minimum:
            raise ValueError(f"must be >= {spec.minimum:g}")
        if spec.maximum is not None and out > spec.maximum:
            raise ValueError(f"must be <= {spec.maximum:g}")
    return out


def _validate_values(values: dict[str, Any]) -> dict[str, ConfigValue]:
    validated: dict[str, ConfigValue] = {}
    for path, value in values.items():
        spec = SPEC_BY_PATH.get(path)
        if spec is None:
            raise HTTPException(
                status_code=422, detail=f"unsupported config path: {path}"
            )
        try:
            validated[path] = _coerce_value(spec, value)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"{path}: {e}") from e
    return validated


def _sanitize_recommended_values(
    values: dict[str, Any],
) -> tuple[dict[str, ConfigValue], list[str]]:
    sanitized: dict[str, ConfigValue] = {}
    warnings: list[str] = []
    for path, value in values.items():
        spec = SPEC_BY_PATH.get(path)
        if spec is None:
            warnings.append(f"{path}: unsupported config path ignored")
            continue
        adjusted = value
        if (
            spec.type in {"integer", "number"}
            and not isinstance(value, bool)
            and isinstance(value, (int, float))
        ):
            if spec.minimum is not None and adjusted < spec.minimum:
                warnings.append(
                    f"{path}: adjusted from {value} to minimum {spec.minimum:g}"
                )
                adjusted = (
                    int(spec.minimum)
                    if spec.type == "integer"
                    else float(spec.minimum)
                )
            if spec.maximum is not None and adjusted > spec.maximum:
                warnings.append(
                    f"{path}: adjusted from {value} to maximum {spec.maximum:g}"
                )
                adjusted = (
                    int(spec.maximum)
                    if spec.type == "integer"
                    else float(spec.maximum)
                )
        try:
            sanitized[path] = _coerce_value(spec, adjusted)
        except ValueError as e:
            warnings.append(f"{path}: invalid value ignored ({e})")
    return sanitized, warnings


def build_performance_config_payload() -> dict[str, Any]:
    settings = _settings_dict()
    params = []
    for spec in CONFIG_SPECS:
        env_override = _env_override_for_path(spec.path)
        params.append(
            {
                "path": spec.path,
                "type": spec.type,
                "label": spec.label,
                "description": spec.description,
                "value": _get_path(settings, spec.path),
                "min": spec.minimum,
                "max": spec.maximum,
                "step": spec.step,
                "options": list(spec.options) if spec.options is not None else None,
                "impact": spec.impact,
                "requires_backend_restart": True,
                "env_override": env_override,
            }
        )
    return {"params": params, "requires_backend_restart": True}


def _resource_data() -> dict[str, Any]:
    rm = get_resource_monitor()
    if rm is not None:
        data = rm.get_data()
        if data:
            return data
    proc = psutil.Process()
    return {
        "ts": time.time(),
        "cpu_pct": proc.cpu_percent(interval=0),
        "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
    }


def build_performance_budget_payload(
    resource_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = resource_data or _resource_data()
    cpu_pct = float(data.get("cpu_pct") or 0.0)
    rss_mb = float(data.get("rss_mb") or 0.0)
    cpu_count = psutil.cpu_count(logical=True) or 1
    cpu_total_pct = float(cpu_count * 100)
    cpu_budget_pct = cpu_total_pct * 0.5
    host_total_memory_mb = psutil.virtual_memory().total / (1024 * 1024)
    memory_budget_mb = host_total_memory_mb * 0.5
    return {
        "ts": data.get("ts") or time.time(),
        "cpu_pct": cpu_pct,
        "cpu_total_pct": cpu_total_pct,
        "cpu_budget_pct": cpu_budget_pct,
        "cpu_ratio": cpu_pct / cpu_total_pct if cpu_total_pct else 0.0,
        "cpu_over_budget": cpu_pct > cpu_budget_pct,
        "rss_mb": rss_mb,
        "host_total_memory_mb": host_total_memory_mb,
        "memory_budget_mb": memory_budget_mb,
        "memory_ratio": rss_mb / host_total_memory_mb if host_total_memory_mb else 0.0,
        "memory_over_budget": rss_mb > memory_budget_mb,
    }


def _collect_perf_metrics(request: Request) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    since = now_ms - 60 * 60_000
    db_path = getattr(request.app.state, "obs_db_path", None)
    if not db_path:
        return {"window": {"since": since, "until": now_ms}, "available": False}
    conn = connect(db_path)
    try:
        return {
            "available": True,
            "summary": summary(conn, "1h", since, now_ms),
            "rtf_series": rtf_series(conn, "1m", since, now_ms)[-20:],
            "drop_series": drop_series(conn, "1m", since, now_ms)[-20:],
            "gate_pass_rate": gate_pass_rate(conn, "1m", since, now_ms)[-20:],
            "omni_error_series": omni_error_series(conn, "1m", since, now_ms)[-20:],
            "stage_p95": {
                key: {"p95": value.get("p95"), "sample_size": value.get("sample_size")}
                for key, value in stage_percentiles(conn, "1h", since, now_ms).items()
            },
        }
    except Exception as e:
        logger.warning("performance metrics collection failed: %s", e)
        return {
            "window": {"since": since, "until": now_ms},
            "available": False,
            "error": str(e),
        }
    finally:
        conn.close()


async def _collect_runtime_scope() -> dict[str, Any]:
    """Collect lightweight runtime scope data for diagnosis.

    This intentionally degrades to an unavailable block. Performance diagnosis
    must still respond when MIoT or perception services are partially down.
    """
    max_enabled_cameras = DEFAULT_MAX_ENABLED_CAMERAS
    try:
        from miloco.miot.filter import MAX_ENABLED_CAMERAS

        max_enabled_cameras = MAX_ENABLED_CAMERAS
    except Exception:
        pass
    data: dict[str, Any] = {
        "available": False,
        "max_enabled_cameras": max_enabled_cameras,
    }
    try:
        from miloco.manager import get_manager

        manager = get_manager()
        perception_service = getattr(manager, "perception_service", None)
        if perception_service is not None:
            status = perception_service.engine_status()
            engine = getattr(status, "engine", None)
            data["perception_engine"] = {
                "running": bool(getattr(engine, "running", False)),
                "ready": bool(getattr(engine, "ready", False)),
                "status": getattr(engine, "status", None),
            }
        miot_service = getattr(manager, "miot_service", None)
        if miot_service is not None:
            cameras = await miot_service.list_cameras_with_state()
            enabled = [cam for cam in cameras if cam.get("in_use")]
            connected = [cam for cam in cameras if cam.get("connected")]
            online = [cam for cam in cameras if cam.get("is_online")]
            data.update(
                {
                    "available": True,
                    "camera_count": len(cameras),
                    "enabled_camera_count": len(enabled),
                    "connected_camera_count": len(connected),
                    "online_camera_count": len(online),
                    "enabled_cameras": [
                        {
                            "did": cam.get("did"),
                            "name": cam.get("name"),
                            "room_name": cam.get("room_name"),
                            "connected": bool(cam.get("connected")),
                            "is_online": bool(cam.get("is_online")),
                        }
                        for cam in enabled[:max_enabled_cameras]
                    ],
                }
            )
    except Exception as e:
        logger.warning("runtime scope collection failed: %s", e)
        data["error"] = str(e)
    return data


async def build_diagnosis_input(request: Request) -> dict[str, Any]:
    return {
        "resource": build_performance_budget_payload(),
        "runtime_scope": await _collect_runtime_scope(),
        "performance": _collect_perf_metrics(request),
        "config": {
            item["path"]: item["value"]
            for item in build_performance_config_payload()["params"]
        },
        "config_schema": {
            item["path"]: {
                "type": item["type"],
                "min": item["min"],
                "max": item["max"],
                "options": item["options"],
                "impact": item["impact"],
            }
            for item in build_performance_config_payload()["params"]
        },
        "target": {
            "cpu": "Miloco process CPU below 50% of host total CPU capacity",
            "ram": "Miloco RSS below 50% of host total memory",
            "requires_backend_restart": True,
        },
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("diagnosis output must be a JSON object")
    return data


def validate_diagnosis_output(text: str) -> dict[str, Any]:
    try:
        data = _extract_json_object(text)
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"OpenClaw Agent returned non-JSON diagnosis: {e}"
        ) from e
    missing = sorted(REQUIRED_DIAGNOSIS_KEYS - set(data))
    if missing:
        raise HTTPException(
            status_code=502,
            detail=f"OpenClaw Agent diagnosis missing fields: {', '.join(missing)}",
        )
    if data.get("requires_backend_restart") is not True:
        raise HTTPException(
            status_code=502,
            detail="OpenClaw Agent diagnosis must set requires_backend_restart=true",
        )
    if not isinstance(data.get("recommended_config"), dict):
        raise HTTPException(
            status_code=502,
            detail="OpenClaw Agent recommended_config must be an object",
        )
    recommended_config, warnings = _sanitize_recommended_values(
        data["recommended_config"]
    )
    if not recommended_config and data["recommended_config"]:
        raise HTTPException(
            status_code=502,
            detail="OpenClaw Agent recommended_config had no usable values after validation",
        )
    data["recommended_config"] = recommended_config
    if warnings:
        existing = data.get("warnings")
        data["warnings"] = (existing if isinstance(existing, list) else []) + warnings
    for key in ("bottlenecks", "expected_tradeoffs"):
        if not isinstance(data.get(key), list):
            raise HTTPException(
                status_code=502, detail=f"OpenClaw Agent {key} must be an array"
            )
    return data


def _diagnosis_prompt(payload: dict[str, Any]) -> str:
    return (
        "You are diagnosing Miloco runtime performance for low-end NAS/Docker hosts.\n"
        "Return JSON only. Do not include Markdown fences or prose.\n"
        "Required schema: summary:string, bottlenecks:string[], recommended_preset:string, "
        "recommended_config:object, expected_tradeoffs:string[], risk_level:string, "
        "requires_backend_restart:true.\n"
        "Only use keys from the provided config object in recommended_config. "
        "Every recommended_config value must fit config_schema min/max/options. "
        "For low-end NAS, prefer period_sec 30-60, window_size 30-60, hold_duration_sec 0-30, "
        "input.fps 1, omni_fps 1, identity_engine.enabled false, and tracking_service_mode mock "
        "when CPU is far over budget. If runtime_scope.enabled_camera_count is greater than 1 "
        "and CPU is still over budget, explicitly mention reducing realtime cameras to 1 or "
        "pausing realtime perception in bottlenecks/expected_tradeoffs. "
        "Target: keep Miloco under 50% host CPU capacity and 50% host memory while preserving "
        "camera perception, identity recognition, and Omni where possible.\n\n"
        f"INPUT_JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


async def _poll_agent_output(run_id: str) -> str:
    for _ in range(12):
        data = await call_agent_webhook("get_trace", {"runId": run_id}, timeout=10.0)
        if isinstance(data, dict) and data.get("status") == "done":
            output = data.get("outputText")
            if isinstance(output, str) and output.strip():
                return output
            raise HTTPException(
                status_code=502,
                detail="OpenClaw Agent finished without outputText; update the OpenClaw plugin trace hook",
            )
        if isinstance(data, dict) and data.get("status") == "unknown":
            raise HTTPException(
                status_code=502,
                detail="OpenClaw Agent trace expired before diagnosis was collected",
            )
        await asyncio.sleep(1)
    raise HTTPException(
        status_code=504, detail="Timed out waiting for OpenClaw Agent diagnosis output"
    )


async def run_performance_diagnosis(request: Request) -> dict[str, Any]:
    payload = await build_diagnosis_input(request)
    trace_id = f"perf-diagnose-{uuid.uuid4().hex}"
    try:
        run_id, status, rtt_ms = await run_agent_turn(
            _diagnosis_prompt(payload),
            session_key="agent:main:miloco-performance",
            lane="miloco-performance",
            trace_id=trace_id,
            wait_timeout_ms=120_000,
        )
    except AgentWebhookException as e:
        raise HTTPException(
            status_code=503, detail=f"OpenClaw Agent unavailable: {e}"
        ) from e
    if not run_id:
        raise HTTPException(
            status_code=502, detail="OpenClaw Agent did not return runId"
        )
    if status != "ok":
        raise HTTPException(
            status_code=502, detail=f"OpenClaw Agent diagnosis failed: status={status}"
        )
    text = await _poll_agent_output(run_id)
    diagnosis = validate_diagnosis_output(text)
    diagnosis["run_id"] = run_id
    diagnosis["trace_id"] = trace_id
    diagnosis["webhook_rtt_ms"] = rtt_ms
    return diagnosis


def _restart_command() -> tuple[list[str] | str, bool] | None:
    configured = os.environ.get("MILOCO_BACKEND_RESTART_COMMAND")
    if configured:
        return configured, True
    exe = shutil.which("miloco-cli")
    if exe:
        return [exe, "service", "restart"], False
    return None


def schedule_backend_restart(delay_s: float = 0.75) -> dict[str, Any]:
    command = _restart_command()
    if command is None:
        raise HTTPException(
            status_code=503,
            detail="Backend restart command unavailable; set MILOCO_BACKEND_RESTART_COMMAND or install miloco-cli",
        )

    cmd, shell = command

    def _run() -> None:
        time.sleep(delay_s)
        try:
            subprocess.Popen(
                cmd,
                shell=shell,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            logger.exception("failed to trigger backend restart")

    threading.Thread(
        target=_run, name="miloco-performance-restart", daemon=True
    ).start()
    return {
        "scheduled": True,
        "command": cmd if isinstance(cmd, str) else " ".join(cmd),
    }


def apply_performance_config(values: dict[str, Any]) -> dict[str, Any]:
    validated = _validate_values(values)
    locked = [
        f"{path} ({_env_override_for_path(path)['env_var']})"
        for path in validated
        if _env_override_for_path(path)["active"]
    ]
    if locked:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot apply config paths while environment variables override "
                f"them: {', '.join(locked)}"
            ),
        )
    if _restart_command() is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Backend restart command unavailable; set "
                "MILOCO_BACKEND_RESTART_COMMAND or install miloco-cli"
            ),
        )
    nested: dict[str, Any] = {}
    for path, value in validated.items():
        _set_path(nested, path, value)
    update_shared_config(**nested)
    restart = schedule_backend_restart()
    return {
        "applied": validated,
        "backend_restart_required": True,
        "backend_restart_triggered": True,
        "restart": restart,
    }


async def _limit_enabled_cameras_to_one() -> dict[str, Any]:
    try:
        from miloco.manager import get_manager

        manager = get_manager()
        miot_service = getattr(manager, "miot_service", None)
        if miot_service is None:
            return {"ok": False, "reason": "miot_service_unavailable"}
        cameras = await miot_service.list_cameras_with_state()
        enabled = [cam for cam in cameras if cam.get("in_use")]
        if len(enabled) <= 1:
            return {
                "ok": True,
                "changed": False,
                "enabled_camera_count": len(enabled),
                "disabled_count": 0,
            }
        keep = (
            next((cam for cam in enabled if cam.get("connected")), None)
            or next((cam for cam in enabled if cam.get("is_online")), None)
            or enabled[0]
        )
        keep_did = keep.get("did")
        disable_dids = [cam.get("did") for cam in enabled if cam.get("did") != keep_did]
        disable_dids = [did for did in disable_dids if isinstance(did, str) and did]
        if disable_dids:
            await miot_service.toggle_camera(
                [{"did": did, "in_use": False} for did in disable_dids]
            )
        return {
            "ok": True,
            "changed": bool(disable_dids),
            "enabled_camera_count": len(enabled),
            "disabled_count": len(disable_dids),
            "kept_camera": {
                "did": keep_did,
                "name": keep.get("name"),
                "room_name": keep.get("room_name"),
            },
        }
    except Exception as e:
        logger.warning("safe mode camera limiting failed: %s", e)
        return {"ok": False, "reason": str(e)}


async def apply_performance_safe_mode(
    *, limit_realtime_cameras: bool = True
) -> dict[str, Any]:
    if _restart_command() is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Backend restart command unavailable; set "
                "MILOCO_BACKEND_RESTART_COMMAND or install miloco-cli"
            ),
        )
    camera_action = (
        await _limit_enabled_cameras_to_one()
        if limit_realtime_cameras
        else {"ok": True, "skipped": True}
    )
    validated = _validate_values(LOW_POWER_SAFE_MODE_VALUES)
    nested: dict[str, Any] = {}
    for path, value in validated.items():
        _set_path(nested, path, value)
    update_shared_config(**nested)
    restart = schedule_backend_restart()
    return {
        "preset": "nas_safe_mode",
        "applied": validated,
        "camera_action": camera_action,
        "backend_restart_required": True,
        "backend_restart_triggered": True,
        "restart": restart,
    }
