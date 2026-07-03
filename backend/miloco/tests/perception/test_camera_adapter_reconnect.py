"""相机 manager 自愈测试：登录/LAN 竞态下的连接重试 + 按需补建。

覆盖 bug「登录瞬间相机 LAN 未就绪 → manager 没建成 → 永久不拉流」的两条修复：
- connect_device：两路流都没订上（manager 缺失）时不保留 device，避免假象 + 阻塞重试。
- sync_devices：scope 应连数 > 已连数时先 refresh_cameras 补建 manager。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from miloco.config import reset_settings
from miloco.perception.collect.camera_adapter import (
    _FIRST_FRAME_FAILURE_COOLDOWN_MS,
    _LAN_HINT_FIRST_FRAME_FAILURES_BEFORE_COOLDOWN,
    CameraDeviceAdapter,
    _CameraDeviceState,
)
from miloco.perception.types import PerceptionDevice


def _source(did: str = "cam1") -> PerceptionDevice:
    return PerceptionDevice(
        did=did, name=did, device_type="camera", room_id="r", room_name="r", online=True
    )


class TestConnectDeviceManagerMissing:
    """manager 缺失时 start_*_stream 返回 -1，device 不应留在 _devices。"""

    def test_both_streams_fail_device_dropped(self):
        proxy = MagicMock()
        proxy.start_camera_decode_video_stream = AsyncMock(return_value=-1)
        proxy.start_camera_decode_audio_stream = AsyncMock(return_value=-1)
        adapter = CameraDeviceAdapter(miot_proxy=proxy)

        asyncio.run(adapter.connect_device("cam1", source=_source()))

        assert "cam1" not in adapter._devices
        proxy.start_camera_decode_audio_stream.assert_not_awaited()

    def test_video_ok_device_kept(self):
        # 至少一路订上 = manager 存在，保留 pending device；
        # 但 connected/active_sources 必须等第一帧到达后才成立。
        proxy = MagicMock()
        proxy.start_camera_decode_video_stream = AsyncMock(return_value=0)
        proxy.start_camera_decode_audio_stream = AsyncMock(return_value=-1)
        adapter = CameraDeviceAdapter(miot_proxy=proxy)

        asyncio.run(adapter.connect_device("cam1", source=_source()))

        assert "cam1" in adapter._devices
        assert "cam1" not in adapter.get_connected_devices()
        assert adapter._devices["cam1"].decoded_audio_reg_id == -1
        proxy.start_camera_decode_audio_stream.assert_not_awaited()

    def test_audio_subscription_enabled_by_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MILOCO_HOME", str(tmp_path))
        (tmp_path / "config.json").write_text(
            '{"camera":{"enable_audio_perception":true}}',
            encoding="utf-8",
        )
        reset_settings()
        try:
            proxy = MagicMock()
            proxy.start_camera_decode_video_stream = AsyncMock(return_value=0)
            proxy.start_camera_decode_audio_stream = AsyncMock(return_value=5)
            adapter = CameraDeviceAdapter(miot_proxy=proxy)

            asyncio.run(adapter.connect_device("cam1", source=_source()))

            assert adapter._devices["cam1"].decoded_audio_reg_id == 5
            proxy.start_camera_decode_audio_stream.assert_awaited_once()
        finally:
            reset_settings()

    def test_no_first_frame_device_dropped_after_timeout(self, monkeypatch):
        proxy = MagicMock()
        proxy.start_camera_decode_video_stream = AsyncMock(return_value=7)
        proxy.start_camera_decode_audio_stream = AsyncMock(return_value=-1)
        proxy.stop_camera_decode_video_stream = AsyncMock()
        proxy.rebuild_camera_stream_manager = AsyncMock(return_value=True)
        adapter = CameraDeviceAdapter(miot_proxy=proxy)
        clock = [100_000]
        monkeypatch.setattr(
            "miloco.perception.collect.camera_adapter._monotonic_ms",
            lambda: clock[0],
        )

        asyncio.run(adapter.connect_device("cam1", source=_source()))
        assert "cam1" in adapter._devices

        clock[0] = 160_000
        asyncio.run(adapter._drop_unhealthy_devices())

        assert "cam1" not in adapter._devices
        assert adapter._last_connect_fail_ms["cam1"] == 160_000
        assert (
            adapter._first_frame_cooldown_until_ms["cam1"]
            == 160_000 + _FIRST_FRAME_FAILURE_COOLDOWN_MS
        )
        proxy.stop_camera_decode_video_stream.assert_awaited_once_with("cam1", 0, 7)
        proxy.rebuild_camera_stream_manager.assert_not_awaited()

    def test_first_frame_cooldown_blocks_connect(self, monkeypatch):
        proxy = MagicMock()
        proxy.start_camera_decode_video_stream = AsyncMock(return_value=7)
        proxy.start_camera_decode_audio_stream = AsyncMock(return_value=-1)
        adapter = CameraDeviceAdapter(miot_proxy=proxy)
        adapter._first_frame_cooldown_until_ms["cam1"] = 200_000
        monkeypatch.setattr(
            "miloco.perception.collect.camera_adapter._monotonic_ms",
            lambda: 100_000,
        )

        asyncio.run(adapter.connect_device("cam1", source=_source()))

        assert "cam1" not in adapter._devices
        proxy.start_camera_decode_video_stream.assert_not_awaited()

    def test_no_first_frame_with_lan_hint_rebuilds(self, monkeypatch):
        proxy = MagicMock()
        proxy.stop_camera_decode_video_stream = AsyncMock()
        proxy.rebuild_camera_stream_manager = AsyncMock(return_value=True)
        proxy.get_cached_camera = MagicMock(
            return_value=SimpleNamespace(lan_online=True, local_ip="192.168.31.248")
        )
        adapter = CameraDeviceAdapter(miot_proxy=proxy)
        state = _CameraDeviceState(did="cam1")
        state.decoded_video_reg_id = 9
        state.connected_at_ms = 100_000
        adapter._devices["cam1"] = state
        monkeypatch.setattr(
            "miloco.perception.collect.camera_adapter._monotonic_ms",
            lambda: 160_000,
        )

        asyncio.run(adapter._drop_unhealthy_devices())

        assert "cam1" not in adapter._devices
        assert "cam1" not in adapter._first_frame_cooldown_until_ms
        assert adapter._first_frame_failure_counts["cam1"] == 1
        proxy.stop_camera_decode_video_stream.assert_awaited_once_with("cam1", 0, 9)
        proxy.rebuild_camera_stream_manager.assert_awaited_once_with("cam1")

    def test_repeated_no_first_frame_with_lan_hint_cools_down(self, monkeypatch):
        proxy = MagicMock()
        proxy.stop_camera_decode_video_stream = AsyncMock()
        proxy.rebuild_camera_stream_manager = AsyncMock(return_value=True)
        proxy.get_cached_camera = MagicMock(
            return_value=SimpleNamespace(lan_online=True, local_ip="192.168.31.248")
        )
        adapter = CameraDeviceAdapter(miot_proxy=proxy)
        adapter._first_frame_failure_counts["cam1"] = (
            _LAN_HINT_FIRST_FRAME_FAILURES_BEFORE_COOLDOWN - 1
        )
        state = _CameraDeviceState(did="cam1")
        state.decoded_video_reg_id = 9
        state.connected_at_ms = 100_000
        adapter._devices["cam1"] = state
        monkeypatch.setattr(
            "miloco.perception.collect.camera_adapter._monotonic_ms",
            lambda: 160_000,
        )

        asyncio.run(adapter._drop_unhealthy_devices())

        assert "cam1" not in adapter._devices
        assert (
            adapter._first_frame_cooldown_until_ms["cam1"]
            == 160_000 + _FIRST_FRAME_FAILURE_COOLDOWN_MS
        )
        proxy.stop_camera_decode_video_stream.assert_awaited_once_with("cam1", 0, 9)
        proxy.rebuild_camera_stream_manager.assert_not_awaited()

    def test_no_first_frame_device_kept_before_timeout(self, monkeypatch):
        proxy = MagicMock()
        proxy.start_camera_decode_video_stream = AsyncMock(return_value=7)
        proxy.start_camera_decode_audio_stream = AsyncMock(return_value=-1)
        proxy.stop_camera_decode_video_stream = AsyncMock()
        proxy.rebuild_camera_stream_manager = AsyncMock(return_value=True)
        adapter = CameraDeviceAdapter(miot_proxy=proxy)
        clock = [100_000]
        monkeypatch.setattr(
            "miloco.perception.collect.camera_adapter._monotonic_ms",
            lambda: clock[0],
        )

        asyncio.run(adapter.connect_device("cam1", source=_source()))
        clock[0] = 159_999
        asyncio.run(adapter._drop_unhealthy_devices())

        assert "cam1" in adapter._devices
        proxy.stop_camera_decode_video_stream.assert_not_awaited()
        proxy.rebuild_camera_stream_manager.assert_not_awaited()

    def test_stale_video_device_dropped(self, monkeypatch):
        proxy = MagicMock()
        proxy.stop_camera_decode_video_stream = AsyncMock()
        proxy.rebuild_camera_stream_manager = AsyncMock(return_value=True)
        adapter = CameraDeviceAdapter(miot_proxy=proxy)
        state = _CameraDeviceState(did="cam1")
        state.decoded_video_reg_id = 9
        state.connected_at_ms = 50_000
        state.last_video_frame_ms = 100_000
        state.video_frame_count = 3
        adapter._devices["cam1"] = state
        monkeypatch.setattr(
            "miloco.perception.collect.camera_adapter._monotonic_ms",
            lambda: 130_000,
        )

        asyncio.run(adapter._drop_unhealthy_devices())

        assert "cam1" not in adapter._devices
        assert adapter._last_connect_fail_ms["cam1"] == 130_000
        proxy.stop_camera_decode_video_stream.assert_awaited_once_with("cam1", 0, 9)
        proxy.rebuild_camera_stream_manager.assert_awaited_once_with("cam1")


class TestSyncDevicesOnDemandRefresh:
    """sync_devices 按需补建：应连 > 已连才触发 refresh_cameras。"""

    def _adapter_with_mocked_connect(self, monkeypatch, proxy):
        adapter = CameraDeviceAdapter(miot_proxy=proxy)
        # 隔离基类的实际连接/断开，只验证 refresh 触发与否。
        monkeypatch.setattr(adapter, "connect_device", AsyncMock())
        monkeypatch.setattr(adapter, "disconnect_device", AsyncMock())
        return adapter

    def test_refresh_when_expected_gt_connected(self, monkeypatch):
        proxy = MagicMock()
        proxy.is_authenticated = True
        proxy.refresh_cameras = AsyncMock()
        adapter = self._adapter_with_mocked_connect(monkeypatch, proxy)
        # _devices 空（卡死态：reg_id<0 已被剔除），discover 出 1 台 → 应连 1 > 已连 0
        monkeypatch.setattr(
            adapter, "discover_devices", AsyncMock(return_value={"cam1": _source()})
        )

        asyncio.run(adapter.sync_devices())

        proxy.refresh_cameras.assert_awaited_once()

    def test_no_refresh_when_all_connected(self, monkeypatch):
        proxy = MagicMock()
        proxy.is_authenticated = True
        proxy.refresh_cameras = AsyncMock()
        proxy.get_cached_camera = MagicMock(return_value=None)
        adapter = self._adapter_with_mocked_connect(monkeypatch, proxy)
        adapter._devices["cam1"] = _CameraDeviceState(did="cam1")  # 已连 1 台
        monkeypatch.setattr(
            adapter, "discover_devices", AsyncMock(return_value={"cam1": _source()})
        )

        asyncio.run(adapter.sync_devices())

        proxy.refresh_cameras.assert_not_awaited()

    def test_no_refresh_when_unauthenticated(self, monkeypatch):
        proxy = MagicMock()
        proxy.is_authenticated = False
        proxy.refresh_cameras = AsyncMock()
        adapter = self._adapter_with_mocked_connect(monkeypatch, proxy)
        monkeypatch.setattr(adapter, "discover_devices", AsyncMock(return_value={}))

        asyncio.run(adapter.sync_devices())

        proxy.refresh_cameras.assert_not_awaited()

    def test_throttle_skips_rapid_refresh(self, monkeypatch):
        # 无设备态 sync 1s 一轮，节流让 refresh_cameras 最多每 10s 一次。
        proxy = MagicMock()
        proxy.is_authenticated = True
        proxy.refresh_cameras = AsyncMock()
        adapter = self._adapter_with_mocked_connect(monkeypatch, proxy)
        monkeypatch.setattr(
            adapter, "discover_devices", AsyncMock(return_value={"cam1": _source()})
        )
        clock = [100_000]
        monkeypatch.setattr(
            "miloco.perception.collect.camera_adapter._monotonic_ms", lambda: clock[0]
        )

        asyncio.run(adapter.sync_devices())  # 首次：触发
        clock[0] = 105_000  # +5s < 10s
        asyncio.run(adapter.sync_devices())  # 节流：跳过
        assert proxy.refresh_cameras.await_count == 1
        clock[0] = 116_000  # 距上次 +11s >= 10s
        asyncio.run(adapter.sync_devices())  # 再次触发
        assert proxy.refresh_cameras.await_count == 2
