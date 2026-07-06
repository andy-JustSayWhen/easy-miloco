"""External camera stream bridge for cameras unsupported by the native SDK."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import av

from miloco.config import get_settings

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

DecodedVideoCallback = Callable[
    [str, "NDArray[np.uint8]", int, int, int, int],
    Awaitable[None],
]

logger = logging.getLogger(__name__)

_EXTERNAL_REG_ID_BASE = 100_000_000


def _unix_ms() -> int:
    return int(time.time() * 1000)


def get_external_stream_url(camera_id: str) -> str | None:
    """Return configured external stream URL for a camera did."""
    try:
        streams = get_settings().camera.external_streams or {}
    except Exception:
        return None
    url = streams.get(camera_id)
    if not isinstance(url, str):
        return None
    url = url.strip()
    return url or None


def has_external_stream(camera_id: str) -> bool:
    return get_external_stream_url(camera_id) is not None


@dataclass
class _ExternalStreamState:
    camera_id: str
    channel: int
    url: str
    loop: asyncio.AbstractEventLoop
    callbacks: dict[int, DecodedVideoCallback] = field(default_factory=dict)
    stop_event: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task | None = None


class ExternalCameraStreamManager:
    """Decode configured RTSP/HTTP streams and fan out BGR frames."""

    def __init__(self) -> None:
        self._states: dict[str, _ExternalStreamState] = {}
        self._reg_to_tag: dict[int, str] = {}
        self._next_reg_id = _EXTERNAL_REG_ID_BASE
        self._lock = asyncio.Lock()

    @staticmethod
    def is_external_reg_id(reg_id: int) -> bool:
        return reg_id >= _EXTERNAL_REG_ID_BASE

    async def start_decoded_video_stream(
        self,
        camera_id: str,
        channel: int,
        callback: DecodedVideoCallback,
    ) -> int:
        url = get_external_stream_url(camera_id)
        if not url:
            return -1
        tag = self._tag(camera_id, channel)
        async with self._lock:
            state = self._states.get(tag)
            if state is None:
                state = _ExternalStreamState(
                    camera_id=camera_id,
                    channel=channel,
                    url=url,
                    loop=asyncio.get_running_loop(),
                )
                self._states[tag] = state
                state.task = asyncio.create_task(self._run(state), name=f"external-camera-{tag}")
            reg_id = self._next_reg_id
            self._next_reg_id += 1
            state.callbacks[reg_id] = callback
            self._reg_to_tag[reg_id] = tag
            logger.info(
                "External camera stream registered: %s url=%s reg_id=%d",
                tag,
                self._redact_url(url),
                reg_id,
            )
            return reg_id

    async def stop_decoded_video_stream(self, reg_id: int) -> bool:
        tag = self._reg_to_tag.pop(reg_id, None)
        if tag is None:
            return False
        async with self._lock:
            state = self._states.get(tag)
            if state is None:
                return True
            state.callbacks.pop(reg_id, None)
            if state.callbacks:
                return True
            state.stop_event.set()
            task = state.task
            if task is not None:
                task.cancel()
            self._states.pop(tag, None)
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("External camera stream stopped: %s reg_id=%d", tag, reg_id)
        return True

    async def _run(self, state: _ExternalStreamState) -> None:
        while not state.stop_event.is_set():
            try:
                await asyncio.to_thread(self._decode_loop, state)
            except asyncio.CancelledError:
                state.stop_event.set()
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "External camera stream failed: %s url=%s error=%s",
                    self._tag(state.camera_id, state.channel),
                    self._redact_url(state.url),
                    e,
                )
            if state.stop_event.is_set():
                return
            await asyncio.sleep(self._reconnect_seconds())

    def _decode_loop(self, state: _ExternalStreamState) -> None:
        options = self._av_open_options(state.url)
        container = av.open(state.url, mode="r", options=options)
        try:
            stream = next(s for s in container.streams if s.type == "video")
            stream.thread_type = "AUTO"
            min_interval_ms = self._frame_interval_ms()
            last_emit_ms = 0
            for frame in container.decode(stream):
                if state.stop_event.is_set():
                    break
                now_ms = _unix_ms()
                if now_ms - last_emit_ms < min_interval_ms:
                    continue
                bgr = frame.to_ndarray(format="bgr24")
                callbacks = list(state.callbacks.values())
                for callback in callbacks:
                    future = asyncio.run_coroutine_threadsafe(
                        callback(
                            state.camera_id,
                            bgr,
                            now_ms,
                            state.channel,
                            now_ms,
                            now_ms,
                        ),
                        state.loop,
                    )
                    future.add_done_callback(self._log_callback_error)
                last_emit_ms = now_ms
        finally:
            container.close()

    @staticmethod
    def _tag(camera_id: str, channel: int) -> str:
        return f"{camera_id}.{channel}"

    @staticmethod
    def _log_callback_error(future: asyncio.Future) -> None:
        try:
            future.result()
        except Exception as e:  # noqa: BLE001
            logger.warning("External camera callback failed: %s", e)

    @staticmethod
    def _redact_url(url: str) -> str:
        if "@" not in url:
            return url
        scheme, rest = url.split("://", 1) if "://" in url else ("", url)
        host = rest.rsplit("@", 1)[-1]
        return f"{scheme}://***@{host}" if scheme else f"***@{host}"

    @staticmethod
    def _frame_interval_ms() -> int:
        try:
            return max(200, int(get_settings().camera.external_stream_frame_interval))
        except Exception:
            return 1000

    @staticmethod
    def _reconnect_seconds() -> int:
        try:
            return max(1, int(get_settings().camera.external_stream_reconnect_seconds))
        except Exception:
            return 5

    @staticmethod
    def _av_open_options(url: str) -> dict[str, str]:
        if url.lower().startswith("rtsp://"):
            return {
                "rtsp_transport": "tcp",
                "stimeout": "5000000",
                "timeout": "5000000",
            }
        return {}


external_camera_stream_manager = ExternalCameraStreamManager()
