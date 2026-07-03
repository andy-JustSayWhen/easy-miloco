#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(os.environ.get("MILOCO_CONFIG_PATH", "/data/miloco/config.json"))
OBSERVABILITY_DB_PATH = Path(os.environ.get("MILOCO_OBSERVABILITY_DB_PATH", "/data/miloco/observability.db"))
SUPERVISOR_CONF = Path(os.environ.get("MILOCO_SUPERVISOR_CONF", "/data/miloco/supervisord.conf"))
MILOCO_PORT = int(os.environ.get("MILOCO_PORT", "1810"))
CLOCK_TICKS = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


DEFAULT_HIGH_VALUES: dict[str, Any] = {
    "camera.video_quality": "HIGH",
    "camera.frame_interval": 1000,
    "camera.max_cache_images": 6,
    "camera.enable_audio_perception": False,
    "camera.enable_hw_accel": True,
    "perception.collect.window_size": 4,
    "perception.collect.max_windows": 3,
    "perception.collect.full_action": "clear",
    "perception.engine.input.fps": 3,
    "perception.engine.input.omni_fps": 1,
    "perception.engine.input.period_sec": 4,
    "perception.engine.gate.hold_duration_sec": 0,
    "perception.engine.identity.tracking_service_mode": "deep_sort",
    "perception.engine.identity_engine.enabled": True,
    "perception.engine.identity_engine.deep_sort.mode": "fast",
    "perception.engine.identity_engine.deep_sort.human_reid_skip_windows": 4,
    "perception.engine.omni.allow_h265_remux": False,
    "perception.snapshot_max_disk_mb": 512,
}

LOW_POWER_VALUES: dict[str, Any] = {
    "camera.video_quality": "LOW",
    "camera.frame_interval": 5000,
    "camera.max_cache_images": 2,
    "camera.enable_audio_perception": False,
    "camera.enable_hw_accel": True,
    "perception.collect.window_size": 60,
    "perception.collect.max_windows": 1,
    "perception.collect.full_action": "clear",
    "perception.engine.input.fps": 1,
    "perception.engine.input.omni_fps": 1,
    "perception.engine.input.period_sec": 60,
    "perception.engine.gate.hold_duration_sec": 0,
    "perception.engine.identity.tracking_service_mode": "mock",
    "perception.engine.identity_engine.enabled": False,
    "perception.engine.identity_engine.deep_sort.mode": "fast",
    "perception.engine.identity_engine.deep_sort.human_reid_skip_windows": 20,
    "perception.engine.omni.allow_h265_remux": False,
    "perception.snapshot_max_disk_mb": 256,
}

SNAPSHOT_PATHS = tuple(DEFAULT_HIGH_VALUES.keys())
TRACE_STAGE_FIELDS = (
    "decode_ms",
    "collect_ms",
    "convert_ms",
    "gate_ms",
    "gate_video_ms",
    "gate_audio_ms",
    "identity_ms",
    "omni_ms",
    "cycle_total_ms",
    "window_duration_ms",
)
OMNI_VIDEO_SUFFIXES = (
    "remux_success",
    "remux_fallback",
    "reencode",
    "input_packets",
    "output_bytes",
    "h265_remux_skipped",
    "h265_empty_retry",
)


@dataclass
class ProcSnapshot:
    ts: float
    proc_ticks: int
    rss_mb: float


@dataclass
class Sample:
    ts: int
    cpu_pct: float
    rss_mb: float


def log(message: str) -> None:
    print(f"[perf-probe] {message}", flush=True)


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_path(config: dict[str, Any], dotted: str) -> Any:
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def set_path(config: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node: dict[str, Any] = config
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def config_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    return {path: get_path(config, path) for path in SNAPSHOT_PATHS}


def apply_values(values: dict[str, Any]) -> None:
    config = load_config()
    for path, value in values.items():
        set_path(config, path, value)
    save_config(config)


def restore_backup(backup_path: Path, health_timeout: int) -> None:
    shutil.copy2(backup_path, CONFIG_PATH)
    log("config restored from backup")
    restart_backend()
    wait_health(health_timeout)
    shutil.rmtree(backup_path.parent, ignore_errors=True)
    log("temporary backup removed")


def run_command(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def restart_backend() -> None:
    if SUPERVISOR_CONF.exists():
        cmd = ["supervisorctl", "-c", str(SUPERVISOR_CONF), "restart", "miloco-backend"]
    else:
        cmd = ["miloco-cli", "service", "restart"]
    result = run_command(cmd, timeout=90)
    if result.returncode != 0:
        raise RuntimeError(f"restart failed: {result.stderr.strip() or result.stdout.strip()}")
    log("backend restarted")


def wait_health(timeout_s: int) -> None:
    url = f"http://127.0.0.1:{MILOCO_PORT}/health"
    deadline = time.monotonic() + timeout_s
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    log("health ok")
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise TimeoutError(f"health did not recover within {timeout_s}s: {last_error}")


def find_miloco_pid() -> int | None:
    proc = run_command(["pgrep", "-f", "python -m miloco.main"], timeout=5)
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def read_proc_snapshot(pid: int) -> ProcSnapshot:
    stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    close_paren = stat.rfind(")")
    fields = stat[close_paren + 2 :].split()
    utime = int(fields[11])
    stime = int(fields[12])
    rss_pages = int(fields[21])
    rss_mb = rss_pages * PAGE_SIZE / 1024 / 1024
    return ProcSnapshot(ts=time.monotonic(), proc_ticks=utime + stime, rss_mb=rss_mb)


def host_memory_total_mb() -> float:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return float(line.split()[1]) / 1024
    return 0.0


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(len(ordered) * q) - 1))
    return ordered[idx]


def numeric_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"avg": 0.0, "p95": 0.0, "max": 0.0, "sample_size": 0}
    return {
        "avg": round(sum(values) / len(values), 1),
        "p95": round(percentile(values, 0.95), 1),
        "max": round(max(values), 1),
        "sample_size": len(values),
    }


def sum_timing_suffix(detail: dict[str, Any], suffix: str) -> float:
    marker = f"_{suffix}"
    total = 0.0
    for key, value in detail.items():
        if key == f"omni_video_{suffix}" or key.endswith(marker):
            if isinstance(value, (int, float)):
                total += float(value)
    return total


def read_trace_summary(window_minutes: int) -> dict[str, Any]:
    if window_minutes <= 0:
        return {"enabled": False}
    if not OBSERVABILITY_DB_PATH.exists():
        return {"enabled": True, "present": False, "error": "observability db not found"}

    try:
        conn = sqlite3.connect(f"file:{OBSERVABILITY_DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return {"enabled": True, "present": True, "error": f"open failed: {exc}"}

    try:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='traces'"
        ).fetchone()
        if table is None:
            return {"enabled": True, "present": True, "error": "traces table not found"}

        max_ts = conn.execute("SELECT max(timestamp) FROM traces").fetchone()[0]
        if max_ts is None:
            return {"enabled": True, "present": True, "row_count": 0}

        since = int(max_ts) - window_minutes * 60_000
        rows = conn.execute(
            "SELECT * FROM traces WHERE timestamp >= ? ORDER BY timestamp",
            (since,),
        ).fetchall()

        stage: dict[str, dict[str, Any]] = {}
        for field in TRACE_STAGE_FIELDS:
            vals = [float(row[field] or 0) for row in rows if row[field] is not None and float(row[field] or 0) > 0]
            stage[field] = numeric_stats(vals)

        video_samples: list[dict[str, Any]] = []
        for row in rows:
            raw = row["timing_detail"]
            if not raw:
                continue
            try:
                detail = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(detail, dict):
                continue
            sample = {suffix: sum_timing_suffix(detail, suffix) for suffix in OMNI_VIDEO_SUFFIXES}
            sample["raw_window_packets"] = float(detail.get("raw_encoded_video_window_packets", 0) or 0)
            sample["raw_keyframes"] = float(detail.get("raw_encoded_video_keyframes", 0) or 0)
            if any(value > 0 for value in sample.values()):
                sample["timestamp"] = row["timestamp"]
                sample["trace_id"] = row["trace_id"]
                video_samples.append(sample)

        output_bytes = [sample["output_bytes"] for sample in video_samples if sample["output_bytes"] > 0]
        remux_success = sum(sample["remux_success"] for sample in video_samples)
        remux_fallback = sum(sample["remux_fallback"] for sample in video_samples)
        total_attempts = remux_success + remux_fallback
        latest = video_samples[-1] if video_samples else None
        latest_video = None
        if latest:
            mode = "none"
            if latest["h265_empty_retry"] > 0:
                mode = "h265_empty_retry"
            elif latest["remux_success"] > 0 and latest["reencode"] <= 0:
                mode = "remux"
            elif latest["h265_remux_skipped"] > 0:
                mode = "h265_reencode"
            elif latest["reencode"] > 0:
                mode = "reencode"
            elif latest["remux_fallback"] > 0:
                mode = "fallback"
            latest_video = {
                "trace_id": latest["trace_id"],
                "timestamp": latest["timestamp"],
                "mode": mode,
                "input_packets": latest["input_packets"],
                "raw_window_packets": latest["raw_window_packets"],
                "raw_keyframes": latest["raw_keyframes"],
                "output_bytes": latest["output_bytes"],
                "h265_remux_skipped": latest["h265_remux_skipped"],
                "h265_empty_retry": latest["h265_empty_retry"],
            }

        return {
            "enabled": True,
            "present": True,
            "window_minutes": window_minutes,
            "since_ts": since,
            "until_ts": max_ts,
            "row_count": len(rows),
            "skipped_count": sum(1 for row in rows if row["skipped"]),
            "omni_error_count": sum(int(row["omni_error_count"] or 0) for row in rows),
            "dropped_windows_total": rows[-1]["dropped_windows_total"] if rows else None,
            "overflow_count_total": rows[-1]["overflow_count_total"] if rows else None,
            "stage": stage,
            "omni_video": {
                "sample_count": len(video_samples),
                "remux_success_count": round(remux_success, 1),
                "remux_fallback_count": round(remux_fallback, 1),
                "reencode_count": round(sum(sample["reencode"] for sample in video_samples), 1),
                "h265_remux_skipped_count": round(
                    sum(sample["h265_remux_skipped"] for sample in video_samples), 1
                ),
                "h265_empty_retry_count": round(
                    sum(sample["h265_empty_retry"] for sample in video_samples), 1
                ),
                "input_packets_total": round(sum(sample["input_packets"] for sample in video_samples), 1),
                "raw_window_packets_total": round(
                    sum(sample["raw_window_packets"] for sample in video_samples), 1
                ),
                "raw_keyframes_total": round(sum(sample["raw_keyframes"] for sample in video_samples), 1),
                "output_bytes": numeric_stats(output_bytes),
                "remux_success_rate": round(remux_success / total_attempts, 3)
                if total_attempts > 0
                else 0.0,
                "latest": latest_video,
            },
        }
    except sqlite3.Error as exc:
        return {"enabled": True, "present": True, "error": f"query failed: {exc}"}
    finally:
        conn.close()


def sample_process(duration_s: int, interval_s: int) -> list[Sample]:
    pid = find_miloco_pid()
    if pid is None:
        raise RuntimeError("miloco backend process not found")
    samples: list[Sample] = []
    previous = read_proc_snapshot(pid)
    log(f"sampling pid={pid} duration={duration_s}s interval={interval_s}s")
    end_time = time.monotonic() + duration_s
    while time.monotonic() < end_time:
        sleep_s = min(interval_s, max(0.1, end_time - time.monotonic()))
        time.sleep(sleep_s)
        current = read_proc_snapshot(pid)
        elapsed = max(current.ts - previous.ts, 0.001)
        cpu_pct = ((current.proc_ticks - previous.proc_ticks) / CLOCK_TICKS) / elapsed * 100
        samples.append(Sample(ts=int(time.time()), cpu_pct=cpu_pct, rss_mb=current.rss_mb))
        log(f"sample cpu={cpu_pct:.1f}% rss={current.rss_mb:.1f}MB")
        previous = current
    return samples


def summarize(samples: list[Sample]) -> dict[str, Any]:
    cpu_total_pct = (os.cpu_count() or 1) * 100.0
    cpu_budget_pct = cpu_total_pct * 0.5
    memory_total_mb = host_memory_total_mb()
    memory_budget_mb = memory_total_mb * 0.5
    peak_cpu = max((sample.cpu_pct for sample in samples), default=0.0)
    avg_cpu = sum((sample.cpu_pct for sample in samples), 0.0) / len(samples) if samples else 0.0
    peak_rss = max((sample.rss_mb for sample in samples), default=0.0)
    avg_rss = sum((sample.rss_mb for sample in samples), 0.0) / len(samples) if samples else 0.0
    return {
        "sample_count": len(samples),
        "cpu": {
            "peak_pct": round(peak_cpu, 1),
            "avg_pct": round(avg_cpu, 1),
            "budget_pct": round(cpu_budget_pct, 1),
            "over_budget": peak_cpu > cpu_budget_pct,
        },
        "memory": {
            "peak_rss_mb": round(peak_rss, 1),
            "avg_rss_mb": round(avg_rss, 1),
            "budget_mb": round(memory_budget_mb, 1),
            "over_budget": peak_rss > memory_budget_mb if memory_budget_mb else False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Miloco NAS runtime CPU/RAM probe.")
    parser.add_argument("--duration", type=int, default=120, help="Sampling duration in seconds.")
    parser.add_argument("--interval", type=int, default=5, help="Sampling interval in seconds.")
    parser.add_argument(
        "--profile",
        choices=("current", "default-high", "low-power"),
        default="current",
        help="Profile to test. current is read-only.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the selected non-current profile before sampling.")
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="Do not restore the original config after applying a profile.",
    )
    parser.add_argument("--health-timeout", type=int, default=90, help="Seconds to wait for /health after restart.")
    parser.add_argument(
        "--trace-window-minutes",
        type=int,
        default=10,
        help="Minutes of observability traces to summarize after sampling.",
    )
    parser.add_argument("--no-traces", action="store_true", help="Do not read observability.db trace summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration <= 0 or args.interval <= 0:
        raise SystemExit("duration and interval must be positive")
    if args.profile != "current" and not args.apply:
        raise SystemExit("non-current profiles require --apply")
    if not CONFIG_PATH.exists():
        raise SystemExit(f"config not found: {CONFIG_PATH}")

    profile_values = {
        "current": None,
        "default-high": DEFAULT_HIGH_VALUES,
        "low-power": LOW_POWER_VALUES,
    }[args.profile]
    backup_path: Path | None = None
    restore_needed = bool(profile_values and not args.no_restore)
    stop_requested = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    started_at = int(time.time())
    before_config = config_snapshot(load_config())
    restored = False
    try:
        if profile_values:
            backup_dir = Path(f"/tmp/easy-miloco-perf-probe-{started_at}")
            backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            backup_path = backup_dir / "config.backup.json"
            shutil.copy2(CONFIG_PATH, backup_path)
            log(f"config backup created: {backup_path}")
            apply_values(profile_values)
            log(f"profile applied: {args.profile}")
            restart_backend()
            wait_health(args.health_timeout)

        samples = sample_process(args.duration, args.interval)
        sampled_config = config_snapshot(load_config())
        trace_summary = None if args.no_traces else read_trace_summary(args.trace_window_minutes)
        if restore_needed and backup_path and backup_path.exists():
            restore_backup(backup_path, args.health_timeout)
            backup_path = None
            restored = True
        final_config = config_snapshot(load_config())
        summary = summarize(samples)
        summary.update(
            {
                "profile": args.profile,
                "duration_s": args.duration,
                "interval_s": args.interval,
                "config_before": before_config,
                "config_sampled": sampled_config,
                "config_final": final_config,
                "restored": restored,
                "trace_summary": trace_summary,
            }
        )
        print("SUMMARY_JSON=" + json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        return 0
    finally:
        if restore_needed and backup_path and backup_path.exists():
            try:
                restore_backup(backup_path, args.health_timeout)
            finally:
                backup_path = None
        if stop_requested:
            log("interrupted")


if __name__ == "__main__":
    raise SystemExit(main())
