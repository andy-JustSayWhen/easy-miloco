from __future__ import annotations

from types import SimpleNamespace

from miloco.perception.inference import ort_utils


def test_default_num_threads_adapts_to_low_core_hosts(monkeypatch):
    monkeypatch.delenv("MILOCO_ORT_NUM_THREADS", raising=False)

    monkeypatch.setattr(ort_utils.os, "cpu_count", lambda: 4)
    assert ort_utils._default_num_threads() == 2

    monkeypatch.setattr(ort_utils.os, "cpu_count", lambda: 2)
    assert ort_utils._default_num_threads() == 1


def test_default_num_threads_env_override(monkeypatch):
    monkeypatch.setenv("MILOCO_ORT_NUM_THREADS", "6")
    monkeypatch.setattr(ort_utils.os, "cpu_count", lambda: 4)

    assert ort_utils._default_num_threads() == 6


def test_make_session_uses_single_inter_op_thread(monkeypatch):
    captured = {}

    class _FakeOptions:
        def __init__(self):
            self.intra_op_num_threads = None
            self.inter_op_num_threads = None
            self.config_entries = {}

        def add_session_config_entry(self, key, value):
            self.config_entries[key] = value

    def _fake_session(model_path, sess_options, providers):
        captured["model_path"] = model_path
        captured["sess_options"] = sess_options
        captured["providers"] = providers
        return SimpleNamespace()

    monkeypatch.setattr(ort_utils.ort, "SessionOptions", _FakeOptions)
    monkeypatch.setattr(ort_utils.ort, "InferenceSession", _fake_session)
    monkeypatch.setattr(ort_utils.ort, "get_available_providers", lambda: ["CPUExecutionProvider"])
    monkeypatch.setattr(ort_utils.ort, "__version__", "1.25.0")
    monkeypatch.delenv("MILOCO_ORT_NUM_THREADS", raising=False)
    monkeypatch.setattr(ort_utils.os, "cpu_count", lambda: 4)

    ort_utils.make_session("/models/det.onnx")

    opts = captured["sess_options"]
    assert opts.intra_op_num_threads == 2
    assert opts.inter_op_num_threads == 1
    assert captured["providers"] == ["CPUExecutionProvider"]
