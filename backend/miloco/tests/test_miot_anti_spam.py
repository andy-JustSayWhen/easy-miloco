# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.

from miloco.miot.anti_spam import (
    is_status_only_call_action,
    is_status_only_message,
    reset_anti_spam_state,
    should_suppress_call_action,
    should_suppress_notify,
)
from miloco.miot.schema import DeviceControlRequest


def setup_function():
    reset_anti_spam_state()


def test_notify_dedupe_suppresses_same_text_within_ttl(monkeypatch):
    now = 100.0
    monkeypatch.setattr("miloco.miot.anti_spam.time.monotonic", lambda: now)

    assert should_suppress_notify("刚才客厅 水浸误报", ttl_s=60) is False
    assert should_suppress_notify("刚才客厅   水浸误报", ttl_s=60) is True


def test_notify_dedupe_allows_after_ttl(monkeypatch):
    now = 100.0
    monkeypatch.setattr("miloco.miot.anti_spam.time.monotonic", lambda: now)
    assert should_suppress_notify("hello", ttl_s=5) is False

    now = 106.0
    assert should_suppress_notify("hello", ttl_s=5) is False


def test_notify_dedupe_can_be_disabled():
    assert should_suppress_notify("hello", ttl_s=0) is False
    assert should_suppress_notify("hello", ttl_s=0) is False


def test_status_only_false_alarm_message_is_blocked():
    assert (
        is_status_only_message(
            "刚才客厅的水浸卫士误报了一次，应该是客厅地面的瓷砖反光导致的，不用担心。"
        )
        is True
    )


def test_status_only_recovery_message_is_blocked():
    assert is_status_only_message("摄像头连接异常已自动修复，无需处理。") is True


def test_real_alert_message_is_not_blocked():
    assert is_status_only_message("客厅检测到水浸，请立即检查。") is False


def test_call_action_dedupe_suppresses_same_device_action(monkeypatch):
    now = 100.0
    monkeypatch.setattr("miloco.miot.anti_spam.time.monotonic", lambda: now)
    req = DeviceControlRequest(
        type="call_action",
        iid="action.3.1",
        params=["刚才客厅的水浸卫士误报了一次", False],
    )

    assert should_suppress_call_action("speaker-1", req, ttl_s=60) is False
    assert should_suppress_call_action("speaker-1", req, ttl_s=60) is True


def test_call_action_dedupe_does_not_touch_property_updates():
    req = DeviceControlRequest(type="set_property", iid="prop.2.1", value=True)

    assert should_suppress_call_action("lamp-1", req, ttl_s=60) is False
    assert should_suppress_call_action("lamp-1", req, ttl_s=60) is False


def test_status_only_call_action_is_blocked():
    req = DeviceControlRequest(
        type="call_action",
        iid="action.3.1",
        params=["水浸卫士误报了一次，不用担心。", False],
    )

    assert is_status_only_call_action(req) is True
