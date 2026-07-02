from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from miloco.admin import performance_tuning as pt
from miloco.config import reset_settings
from miloco.middleware.exceptions import AgentWebhookException


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MILOCO_HOME", str(tmp_path))
    reset_settings()
    yield
    reset_settings()


def test_budget_uses_half_of_host_cpu_and_ram(monkeypatch):
    monkeypatch.setattr(pt.psutil, "cpu_count", lambda logical=True: 4)
    monkeypatch.setattr(
        pt.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=8 * 1024 * 1024 * 1024),
    )

    data = pt.build_performance_budget_payload(
        {"ts": 1, "cpu_pct": 250.0, "rss_mb": 5000.0}
    )

    assert data["cpu_total_pct"] == 400.0
    assert data["cpu_budget_pct"] == 200.0
    assert data["cpu_over_budget"] is True
    assert data["memory_budget_mb"] == 4096.0
    assert data["memory_over_budget"] is True


@pytest.mark.asyncio
async def test_diagnosis_input_contains_runtime_perf_scope_and_config(monkeypatch):
    monkeypatch.setattr(
        pt,
        "build_performance_budget_payload",
        lambda: {
            "cpu_pct": 90.0,
            "rss_mb": 1024.0,
            "host_total_memory_mb": 4096.0,
        },
    )
    monkeypatch.setattr(
        pt,
        "_collect_perf_metrics",
        lambda request: {
            "summary": {"p95_rtf_e2e": 1.6, "drop_rate": 0.2},
            "rtf_series": [{"rtf_e2e": 1.6}],
            "drop_series": [{"dropped": 2}],
            "stage_p95": {"omni_ms": {"p95": 3500}},
            "gate_pass_rate": [{"overall": 0.4}],
            "omni_error_series": [{"timeout": 1}],
        },
    )

    async def fake_runtime_scope():
        return {
            "available": True,
            "enabled_camera_count": 3,
            "connected_camera_count": 3,
            "perception_engine": {"running": True, "ready": True},
        }

    monkeypatch.setattr(pt, "_collect_runtime_scope", fake_runtime_scope)

    payload = await pt.build_diagnosis_input(SimpleNamespace(app=SimpleNamespace()))

    assert payload["resource"]["cpu_pct"] == 90.0
    assert payload["resource"]["host_total_memory_mb"] == 4096.0
    assert payload["performance"]["stage_p95"]["omni_ms"]["p95"] == 3500
    assert payload["performance"]["summary"]["drop_rate"] == 0.2
    assert payload["runtime_scope"]["enabled_camera_count"] == 3
    assert payload["runtime_scope"]["perception_engine"]["running"] is True
    assert "camera.frame_interval" in payload["config"]
    assert "perception.engine.input.period_sec" in payload["config"]
    assert "perception.engine.gate.hold_duration_sec" in payload["config"]
    assert payload["config_schema"]["perception.collect.window_size"]["max"] == 60
    assert payload["target"]["requires_backend_restart"] is True


def test_validate_agent_json_rejects_non_json():
    with pytest.raises(HTTPException) as exc:
        pt.validate_diagnosis_output("not json")
    assert exc.value.status_code == 502
    assert "non-JSON" in exc.value.detail


def test_validate_agent_json_sanitizes_invalid_recommendations():
    body = {
        "summary": "CPU bound",
        "bottlenecks": ["decode"],
        "recommended_preset": "low_power",
        "recommended_config": {
            "server.token": "leak",
            "perception.engine.input.omni_fps": 0,
            "perception.collect.window_size": 90,
            "perception.engine.input.period_sec": 30,
            "perception.engine.gate.hold_duration_sec": 0,
        },
        "expected_tradeoffs": ["less history"],
        "risk_level": "medium",
        "requires_backend_restart": True,
    }

    result = pt.validate_diagnosis_output(json.dumps(body))

    assert result["recommended_config"] == {
        "perception.engine.input.omni_fps": 1,
        "perception.collect.window_size": 60,
        "perception.engine.input.period_sec": 30,
        "perception.engine.gate.hold_duration_sec": 0.0,
    }
    assert "warnings" in result
    assert any("unsupported config path ignored" in item for item in result["warnings"])
    assert any("adjusted from 0 to minimum 1" in item for item in result["warnings"])
    assert any("adjusted from 90 to maximum 60" in item for item in result["warnings"])


def test_apply_still_rejects_unknown_config_path():
    with pytest.raises(HTTPException) as exc:
        pt.apply_performance_config({"server.token": "leak"})
    assert exc.value.status_code == 422
    assert "unsupported config path" in exc.value.detail


@pytest.mark.asyncio
async def test_agent_valid_json_is_parsed(monkeypatch):
    async def fake_build_diagnosis_input(request):
        return {"ok": True}

    monkeypatch.setattr(pt, "build_diagnosis_input", fake_build_diagnosis_input)

    async def fake_run_agent_turn(*args, **kwargs):
        return "run-1", "ok", 123.0

    async def fake_call_agent_webhook(action, payload, *, timeout=30.0):
        assert action == "get_trace"
        return {
            "status": "done",
            "outputText": json.dumps(
                {
                    "summary": "CPU bound",
                    "bottlenecks": ["decode"],
                    "recommended_preset": "low_power",
                    "recommended_config": {"perception.engine.input.fps": 2},
                    "expected_tradeoffs": ["lower visual smoothness"],
                    "risk_level": "low",
                    "requires_backend_restart": True,
                }
            ),
        }

    monkeypatch.setattr(pt, "run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr(pt, "call_agent_webhook", fake_call_agent_webhook)

    result = await pt.run_performance_diagnosis(SimpleNamespace(app=SimpleNamespace()))

    assert result["recommended_config"] == {"perception.engine.input.fps": 2}
    assert result["run_id"] == "run-1"
    assert result["webhook_rtt_ms"] == 123.0


@pytest.mark.asyncio
async def test_agent_unavailable_returns_clear_error(monkeypatch):
    async def fake_build_diagnosis_input(request):
        return {"ok": True}

    monkeypatch.setattr(pt, "build_diagnosis_input", fake_build_diagnosis_input)

    async def fake_run_agent_turn(*args, **kwargs):
        raise AgentWebhookException("cannot connect")

    monkeypatch.setattr(pt, "run_agent_turn", fake_run_agent_turn)

    with pytest.raises(HTTPException) as exc:
        await pt.run_performance_diagnosis(SimpleNamespace(app=SimpleNamespace()))
    assert exc.value.status_code == 503
    assert "OpenClaw Agent unavailable" in exc.value.detail


def test_apply_writes_config_and_schedules_restart(tmp_path, monkeypatch):
    scheduled = []
    monkeypatch.setattr(pt, "_restart_command", lambda: ("test", True))
    monkeypatch.setattr(
        pt,
        "schedule_backend_restart",
        lambda: scheduled.append(True) or {"scheduled": True, "command": "test"},
    )

    result = pt.apply_performance_config(
        {
            "camera.frame_interval": 1500,
            "perception.engine.input.fps": 2,
            "perf.enabled": True,
        }
    )

    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert data["camera"]["frame_interval"] == 1500
    assert data["perception"]["engine"]["input"]["fps"] == 2
    assert data["perf"]["enabled"] is True
    assert scheduled == [True]
    assert result["backend_restart_triggered"] is True


def test_apply_fails_before_write_when_restart_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(pt, "_restart_command", lambda: None)

    with pytest.raises(HTTPException) as exc:
        pt.apply_performance_config({"camera.frame_interval": 1500})

    assert exc.value.status_code == 503
    assert not (tmp_path / "config.json").exists()
