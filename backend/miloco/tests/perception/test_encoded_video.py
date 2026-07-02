from miloco.perception.encoded_video import (
    EncodedVideoPacket,
    remux_encoded_video_to_mp4,
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


def test_remux_encoded_video_to_mp4_streamcopies_h264_packets(tmp_path):
    import av
    import numpy as np

    raw_path = tmp_path / "source.h264"
    out = av.open(str(raw_path), "w", format="h264")
    stream = out.add_stream("libx264", rate=2)
    stream.width = 64
    stream.height = 64
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "ultrafast", "tune": "zerolatency"}

    packets: list[EncodedVideoPacket] = []
    for idx in range(4):
        frame_data = np.zeros((64, 64, 3), dtype=np.uint8)
        frame_data[:, :, 0] = idx * 40
        frame = av.VideoFrame.from_ndarray(frame_data, format="bgr24")
        for packet in stream.encode(frame):
            packets.append(
                EncodedVideoPacket(
                    codec="h264",
                    data=bytes(packet),
                    stream_ts=idx * 500,
                    wall_ms=idx * 500,
                    sequence=idx,
                    is_keyframe=bool(packet.is_keyframe),
                )
            )
            out.mux(packet)
    for packet in stream.encode():
        packets.append(
            EncodedVideoPacket(
                codec="h264",
                data=bytes(packet),
                stream_ts=len(packets) * 500,
                wall_ms=len(packets) * 500,
                sequence=len(packets),
                is_keyframe=bool(packet.is_keyframe),
            )
        )
        out.mux(packet)
    out.close()

    assert packets[0].is_keyframe

    mp4_bytes = remux_encoded_video_to_mp4(packets, fps=2)

    assert mp4_bytes is not None
    mp4_path = tmp_path / "remuxed.mp4"
    mp4_path.write_bytes(mp4_bytes)
    decoded = list(av.open(str(mp4_path)).decode(video=0))
    assert len(decoded) == 4


def test_remux_encoded_video_to_mp4_rejects_non_keyframe_start():
    packets = [_pkt(1_000), _pkt(1_500)]

    assert remux_encoded_video_to_mp4(packets, fps=2) is None
