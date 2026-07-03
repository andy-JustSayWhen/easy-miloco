from __future__ import annotations

from types import SimpleNamespace

from miloco.utils import bootstrap


def test_default_native_threads_adapts_to_low_core_hosts(monkeypatch):
    monkeypatch.delenv("MILOCO_OPENCV_NUM_THREADS", raising=False)

    monkeypatch.setattr(bootstrap.os, "cpu_count", lambda: 4)
    assert bootstrap._default_native_threads() == 1

    monkeypatch.setattr(bootstrap.os, "cpu_count", lambda: 6)
    assert bootstrap._default_native_threads() == 2


def test_native_threads_env_override(monkeypatch):
    monkeypatch.setenv("MILOCO_OPENCV_NUM_THREADS", "3")
    monkeypatch.setattr(bootstrap.os, "cpu_count", lambda: 4)

    assert bootstrap._default_native_threads() == 3


def test_configure_native_thread_limits_sets_opencv_threads(monkeypatch):
    calls: list[int] = []
    fake_cv2 = SimpleNamespace(setNumThreads=lambda value: calls.append(value))

    monkeypatch.setenv("MILOCO_OPENCV_NUM_THREADS", "2")
    monkeypatch.setitem(__import__("sys").modules, "cv2", fake_cv2)

    bootstrap._configure_native_thread_limits()

    assert calls == [2]


def test_cpu_affinity_budget_defaults_to_half_available(monkeypatch):
    monkeypatch.delenv("MILOCO_CPU_AFFINITY_CORES", raising=False)

    assert bootstrap._resolve_cpu_affinity_budget(4) == 2
    assert bootstrap._resolve_cpu_affinity_budget(1) is None


def test_cpu_affinity_budget_env_override(monkeypatch):
    monkeypatch.setenv("MILOCO_CPU_AFFINITY_CORES", "3")
    assert bootstrap._resolve_cpu_affinity_budget(8) == 3

    monkeypatch.setenv("MILOCO_CPU_AFFINITY_CORES", "off")
    assert bootstrap._resolve_cpu_affinity_budget(8) is None


def test_configure_cpu_affinity_budget_limits_server_process(monkeypatch):
    calls = []

    monkeypatch.delenv("MILOCO_CPU_AFFINITY_CORES", raising=False)
    monkeypatch.setattr(bootstrap.os, "sched_getaffinity", lambda _pid: {0, 1, 2, 3}, raising=False)
    monkeypatch.setattr(bootstrap.os, "sched_setaffinity", lambda pid, cpus: calls.append((pid, cpus)), raising=False)

    bootstrap._configure_cpu_affinity_budget("server")

    assert calls == [(0, {0, 1})]


def test_configure_cpu_affinity_budget_skips_cli(monkeypatch):
    calls = []

    monkeypatch.setattr(bootstrap.os, "sched_getaffinity", lambda _pid: {0, 1, 2, 3}, raising=False)
    monkeypatch.setattr(bootstrap.os, "sched_setaffinity", lambda pid, cpus: calls.append((pid, cpus)), raising=False)

    bootstrap._configure_cpu_affinity_budget("cli")

    assert calls == []
