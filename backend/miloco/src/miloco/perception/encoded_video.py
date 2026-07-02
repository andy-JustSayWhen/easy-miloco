"""Encoded camera video helpers for low-CPU Omni upload.

The live perception path currently uploads Omni video by encoding selected
BGR frames back into H.264 MP4.  A lower-CPU path can reuse camera-provided
H.264/H.265 packets and remux them into MP4, but only if the packet slice
starts at a keyframe.  This module keeps that keyframe-boundary logic small
and independently testable before wiring it into the camera collector.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

import av

EncodedVideoCodec = Literal["h264", "h265"]

_H264_IDR_NAL_TYPE = 5
_H265_RANDOM_ACCESS_NAL_TYPES = frozenset(range(16, 22))
_MP4_TIME_BASE = Fraction(1, 1000)


@dataclass(frozen=True)
class EncodedVideoPacket:
    """A raw encoded camera video packet with host-aligned timing."""

    codec: EncodedVideoCodec
    data: bytes
    stream_ts: int
    wall_ms: int
    sequence: int = 0
    is_keyframe: bool = False


def _iter_annex_b_nal_headers(data: bytes) -> list[int]:
    """Return NAL header byte offsets from an Annex-B byte stream."""

    headers: list[int] = []
    pos = 0
    data_len = len(data)
    while pos + 3 <= data_len:
        start_len = 0
        if data[pos : pos + 3] == b"\x00\x00\x01":
            start_len = 3
        elif pos + 4 <= data_len and data[pos : pos + 4] == b"\x00\x00\x00\x01":
            start_len = 4
        if start_len:
            header_pos = pos + start_len
            if header_pos < data_len:
                headers.append(header_pos)
            pos = header_pos + 1
            continue
        pos += 1
    return headers


def _iter_length_prefixed_nal_headers(data: bytes) -> list[int]:
    """Return NAL header offsets from common 4-byte length-prefixed samples."""

    headers: list[int] = []
    pos = 0
    data_len = len(data)
    while pos + 5 <= data_len:
        nal_len = int.from_bytes(data[pos : pos + 4], "big")
        if nal_len <= 0 or pos + 4 + nal_len > data_len:
            return []
        headers.append(pos + 4)
        pos += 4 + nal_len
    return headers if pos == data_len else []


def _nal_header_offsets(data: bytes) -> list[int]:
    if not data:
        return []
    annex_b = _iter_annex_b_nal_headers(data)
    if annex_b:
        return annex_b
    length_prefixed = _iter_length_prefixed_nal_headers(data)
    if length_prefixed:
        return length_prefixed
    return [0]


def encoded_video_packet_contains_keyframe(
    codec: EncodedVideoCodec,
    data: bytes,
) -> bool:
    """Detect whether raw H.264/H.265 packet bytes contain a keyframe.

    The MiOT SDK does not reliably label I-frames for every camera model.  The
    raw packet payload still carries NAL headers, so inspect those headers as a
    fallback before deciding whether a slice is safe to remux for Omni upload.
    """

    for header_pos in _nal_header_offsets(data):
        if header_pos >= len(data):
            continue
        first = data[header_pos]
        if codec == "h264":
            if first & 0x1F == _H264_IDR_NAL_TYPE:
                return True
            continue

        if header_pos + 1 >= len(data):
            continue
        nal_type = (first >> 1) & 0x3F
        if nal_type in _H265_RANDOM_ACCESS_NAL_TYPES:
            return True
    return False


def select_keyframe_aligned_packets(
    packets: list[EncodedVideoPacket],
    *,
    start_ms: int,
    end_ms: int,
    max_preroll_ms: int = 2_000,
) -> list[EncodedVideoPacket]:
    """Return packets that can seed a remuxed clip for a perception window.

    A video decoder needs the nearest previous keyframe (I frame) before it
    can decode later predicted frames (P frames).  For an Omni upload clip
    covering ``[start_ms, end_ms)``, start at the latest keyframe between
    ``start_ms - max_preroll_ms`` and the first packet inside the window.

    Returns an empty list when no suitable keyframe exists or when the slice
    crosses codecs, so callers can safely fall back to BGR re-encoding.
    """

    if start_ms >= end_ms or not packets:
        return []

    ordered = sorted(packets, key=lambda p: (p.wall_ms, p.sequence))
    first_idx = next(
        (idx for idx, p in enumerate(ordered) if start_ms <= p.wall_ms < end_ms),
        None,
    )
    if first_idx is None:
        return []

    min_keyframe_ms = start_ms - max(0, max_preroll_ms)
    key_idx = None
    for idx in range(first_idx, -1, -1):
        packet = ordered[idx]
        if packet.wall_ms < min_keyframe_ms:
            break
        if packet.is_keyframe:
            key_idx = idx
            break
    if key_idx is None:
        return []

    codec = ordered[key_idx].codec
    selected: list[EncodedVideoPacket] = []
    for packet in ordered[key_idx:]:
        if packet.wall_ms >= end_ms:
            break
        if packet.codec != codec:
            return []
        selected.append(packet)

    return selected


def remux_encoded_video_to_mp4(
    packets: list[EncodedVideoPacket],
    *,
    fps: int,
) -> bytes | None:
    """Remux raw H.264/H.265 packets into an MP4 container without re-encoding.

    This is intentionally conservative.  It only accepts a single-codec slice
    that starts with a keyframe, writes the raw Annex-B stream to FFmpeg/PyAV,
    then stream-copies parsed packets into MP4 with timestamps derived from
    packet wall-clock deltas.  Any parser/muxer failure returns ``None`` so
    callers can fall back to the existing BGR -> H.264 encode path.
    """

    if fps <= 0 or not packets or not packets[0].is_keyframe:
        return None
    codec = packets[0].codec
    if any(p.codec != codec or not p.data for p in packets):
        return None

    input_format = "h264" if codec == "h264" else "hevc"
    raw_path = ""
    mp4_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{input_format}", delete=False) as raw:
            raw_path = raw.name
            for packet in packets:
                raw.write(packet.data)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as mp4:
            mp4_path = mp4.name

        in_container = av.open(raw_path, "r", format=input_format)
        out_container = av.open(mp4_path, "w")
        try:
            in_stream = in_container.streams.video[0]
            out_stream = out_container.add_stream_from_template(in_stream)
            start_ms = packets[0].wall_ms
            deltas = [
                max(1, packets[i + 1].wall_ms - packets[i].wall_ms)
                for i in range(len(packets) - 1)
                if packets[i + 1].wall_ms > packets[i].wall_ms
            ]
            fallback_duration_ms = (
                sorted(deltas)[len(deltas) // 2]
                if deltas
                else max(1, round(1000 / fps))
            )
            time_base = _MP4_TIME_BASE
            out_stream.time_base = time_base

            idx = 0
            for packet in in_container.demux(in_stream):
                if packet.size <= 0:
                    continue
                source_packet = packets[min(idx, len(packets) - 1)]
                next_packet = packets[idx + 1] if idx + 1 < len(packets) else None
                pts_ms = max(0, source_packet.wall_ms - start_ms)
                duration_ms = (
                    max(1, next_packet.wall_ms - source_packet.wall_ms)
                    if next_packet is not None
                    and next_packet.wall_ms > source_packet.wall_ms
                    else fallback_duration_ms
                )
                packet.stream = out_stream
                packet.pts = pts_ms
                packet.dts = pts_ms
                packet.duration = duration_ms
                packet.time_base = time_base
                out_container.mux(packet)
                idx += 1
            if idx == 0:
                return None
        finally:
            out_container.close()
            in_container.close()

        with open(mp4_path, "rb") as f:
            mp4_bytes = f.read()
        return mp4_bytes or None
    except Exception:
        return None
    finally:
        if raw_path and os.path.exists(raw_path):
            os.unlink(raw_path)
        if mp4_path and os.path.exists(mp4_path):
            os.unlink(mp4_path)
