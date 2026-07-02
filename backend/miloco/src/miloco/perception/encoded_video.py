"""Encoded camera video helpers for low-CPU Omni upload.

The live perception path currently uploads Omni video by encoding selected
BGR frames back into H.264 MP4.  A lower-CPU path can reuse camera-provided
H.264/H.265 packets and remux them into MP4, but only if the packet slice
starts at a keyframe.  This module keeps that keyframe-boundary logic small
and independently testable before wiring it into the camera collector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EncodedVideoCodec = Literal["h264", "h265"]


@dataclass(frozen=True)
class EncodedVideoPacket:
    """A raw encoded camera video packet with host-aligned timing."""

    codec: EncodedVideoCodec
    data: bytes
    stream_ts: int
    wall_ms: int
    sequence: int = 0
    is_keyframe: bool = False


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
