from miloco.perception.encoded_video import (
    EncodedVideoPacket,
    select_keyframe_aligned_packets,
)


def _pkt(
    wall_ms: int,
    *,
    keyframe: bool = False,
    sequence: int | None = None,
    codec: str = "h264",
) -> EncodedVideoPacket:
    return EncodedVideoPacket(
        codec=codec,  # type: ignore[arg-type]
        data=f"pkt-{wall_ms}".encode(),
        stream_ts=wall_ms,
        wall_ms=wall_ms,
        sequence=wall_ms if sequence is None else sequence,
        is_keyframe=keyframe,
    )


def test_select_starts_at_latest_keyframe_before_window():
    packets = [
        _pkt(900, keyframe=True),
        _pkt(1_000),
        _pkt(1_500, keyframe=True),
        _pkt(2_000),
        _pkt(2_500),
        _pkt(3_000),
    ]

    selected = select_keyframe_aligned_packets(
        packets,
        start_ms=2_000,
        end_ms=3_000,
        max_preroll_ms=1_000,
    )

    assert [p.wall_ms for p in selected] == [1_500, 2_000, 2_500]


def test_select_returns_empty_when_no_keyframe_preroll():
    packets = [
        _pkt(900, keyframe=True),
        _pkt(1_500),
        _pkt(2_000),
        _pkt(2_500),
    ]

    selected = select_keyframe_aligned_packets(
        packets,
        start_ms=2_000,
        end_ms=3_000,
        max_preroll_ms=500,
    )

    assert selected == []


def test_select_returns_empty_when_slice_crosses_codec():
    packets = [
        _pkt(1_500, keyframe=True, codec="h264"),
        _pkt(2_000, codec="h264"),
        _pkt(2_500, codec="h265"),
    ]

    selected = select_keyframe_aligned_packets(
        packets,
        start_ms=2_000,
        end_ms=3_000,
    )

    assert selected == []


def test_select_orders_by_wall_time_then_sequence():
    packets = [
        _pkt(2_000, sequence=2),
        _pkt(1_500, keyframe=True),
        _pkt(2_000, sequence=1),
    ]

    selected = select_keyframe_aligned_packets(
        packets,
        start_ms=2_000,
        end_ms=2_500,
    )

    assert [p.sequence for p in selected] == [1_500, 1, 2]
