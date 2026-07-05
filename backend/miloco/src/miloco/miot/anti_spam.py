# Copyright (C) 2025 Xiaomi Corporation
# This software may be used and distributed according to the terms of the Xiaomi Miloco License Agreement.

"""Small in-process anti-spam guard for MIoT side effects.

The OpenClaw side may retry or loop. This module keeps the final MIoT boundary
from repeating the same phone notification or speaker action in a short window.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from typing import Any

from miloco.miot.schema import DeviceControlRequest

_WHITESPACE = re.compile(r"\s+")
_notify_seen: dict[str, float] = {}
_action_seen: dict[str, float] = {}
_lock = threading.Lock()
_FALSE_ALARM_WORDS = ("误报", "虚惊", "误触发", "反光导致")
_RECOVERY_WORDS = ("已恢复", "恢复正常", "已修复", "自动修复", "已处理")
_NO_ACTION_WORDS = ("不用担心", "无需担心", "不用处理", "无需处理", "不需要处理")


def _normalize_text(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _digest(parts: list[Any]) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _should_suppress(store: dict[str, float], key: str, ttl_s: int) -> bool:
    if ttl_s <= 0:
        return False
    now = time.monotonic()
    expires_at = now + ttl_s
    with _lock:
        for seen_key, seen_expires_at in list(store.items()):
            if seen_expires_at <= now:
                store.pop(seen_key, None)
        if store.get(key, 0.0) > now:
            return True
        store[key] = expires_at
        return False


def should_suppress_notify(text: str, ttl_s: int) -> bool:
    """Return true when the same notification text was sent recently."""
    key = _digest(["notify", _normalize_text(text)])
    return _should_suppress(_notify_seen, key, ttl_s)


def is_status_only_message(text: str) -> bool:
    """Return true for non-actionable self-heal / false-alarm status text."""
    normalized = _normalize_text(text)
    has_no_action = any(word in normalized for word in _NO_ACTION_WORDS)
    if has_no_action and any(word in normalized for word in _FALSE_ALARM_WORDS):
        return True
    if has_no_action and any(word in normalized for word in _RECOVERY_WORDS):
        return True
    return False


def is_status_only_call_action(request: DeviceControlRequest) -> bool:
    """Return true when a call_action would speak/execute non-actionable text."""
    if request.type != "call_action":
        return False
    return any(is_status_only_message(p) for p in request.params or [] if isinstance(p, str))


def should_suppress_call_action(
    did: str, request: DeviceControlRequest, ttl_s: int
) -> bool:
    """Return true when the same device action was executed recently."""
    if request.type != "call_action":
        return False
    key = _digest(["call_action", did, request.iid, request.params or []])
    return _should_suppress(_action_seen, key, ttl_s)


def reset_anti_spam_state() -> None:
    """Clear process-local state for tests."""
    with _lock:
        _notify_seen.clear()
        _action_seen.clear()
