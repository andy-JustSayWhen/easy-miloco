"""Tests for camera LAN IP override merging."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from miloco.config import reset_settings
from miloco.miot.client import MiotProxy


def test_camera_lan_override_merges_unique_ip_hit_with_different_did(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MILOCO_HOME", str(tmp_path))
    (tmp_path / "camera_lan_overrides.json").write_text(
        json.dumps({"cloud-did": "192.168.31.56"}),
        encoding="utf-8",
    )
    reset_settings()
    try:
        lan_client = SimpleNamespace(
            ping_async=lambda target_ip: None,
            get_devices_async=lambda: {
                "lan-did": SimpleNamespace(online=True, ip="192.168.31.56")
            },
        )

        async def _ping_async(*, target_ip: str):
            assert target_ip == "192.168.31.56"

        async def _get_devices_async():
            return {
                "lan-did": SimpleNamespace(online=True, ip="192.168.31.56")
            }

        lan_client.ping_async = _ping_async
        lan_client.get_devices_async = _get_devices_async
        proxy = MiotProxy.__new__(MiotProxy)
        proxy._miot_client = SimpleNamespace(_lan_client=lan_client)
        cameras = {
            "cloud-did": SimpleNamespace(
                did="cloud-did",
                online=True,
                lan_online=False,
                local_ip=None,
            )
        }

        asyncio.run(proxy._prime_camera_lan_overrides(cameras))

        assert cameras["cloud-did"].lan_online is True
        assert cameras["cloud-did"].local_ip == "192.168.31.56"
    finally:
        reset_settings()


def test_camera_lan_override_rejects_ip_belonging_to_another_known_camera(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MILOCO_HOME", str(tmp_path))
    (tmp_path / "camera_lan_overrides.json").write_text(
        json.dumps({"cloud-did": "192.168.31.56"}),
        encoding="utf-8",
    )
    reset_settings()
    try:
        async def _ping_async(*, target_ip: str):
            return None

        async def _get_devices_async():
            return {
                "other-camera-did": SimpleNamespace(
                    online=True, ip="192.168.31.56"
                )
            }

        lan_client = SimpleNamespace(
            ping_async=_ping_async,
            get_devices_async=_get_devices_async,
        )
        proxy = MiotProxy.__new__(MiotProxy)
        proxy._miot_client = SimpleNamespace(_lan_client=lan_client)
        cameras = {
            "cloud-did": SimpleNamespace(
                did="cloud-did",
                online=True,
                lan_online=False,
                local_ip=None,
            ),
            "other-camera-did": SimpleNamespace(
                did="other-camera-did",
                online=True,
                lan_online=True,
                local_ip="192.168.31.56",
            ),
        }

        asyncio.run(proxy._prime_camera_lan_overrides(cameras))

        assert cameras["cloud-did"].lan_online is False
        assert cameras["cloud-did"].local_ip is None
    finally:
        reset_settings()
