#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(os.environ.get("MILOCO_CONFIG_PATH", "/data/miloco/config.json"))
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
