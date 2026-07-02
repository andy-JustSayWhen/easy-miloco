from miloco.perception.encoded_video import (
    EncodedVideoPacket,
    encoded_video_packet_contains_keyframe,
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


def test_detects_h264_annex_b_idr_keyframe():
    sps = b"\x00\x00\x00\x01\x67\x42\x00\x1f"
    pps = b"\x00\x00\x01\x68\xce\x06\xe2"
    idr = b"\x00\x00\x01\x65\x88\x84\x21"

    assert encoded_video_packet_contains_keyframe("h264", sps + pps + idr)


def test_rejects_h264_non_keyframe_packet():
    p_slice = b"\x00\x00\x01\x41\x9a\x22"

    assert not encoded_video_packet_contains_keyframe("h264", p_slice)


def test_detects_h264_length_prefixed_idr_keyframe():
    idr = b"\x65\x88\x84\x21"
    packet = len(idr).to_bytes(4, "big") + idr

    assert encoded_video_packet_contains_keyframe("h264", packet)


def test_detects_h265_annex_b_random_access_keyframe():
    vps = b"\x00\x00\x00\x01\x40\x01\x0c\x01"
    idr_w_radl = b"\x00\x00\x01\x26\x01\xaf"

    assert encoded_video_packet_contains_keyframe("h265", vps + idr_w_radl)


def test_rejects_h265_non_keyframe_packet():
    trail_r = b"\x00\x00\x01\x02\x01\xaf"

    assert not encoded_video_packet_contains_keyframe("h265", trail_r)


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

    mp4_bytes = remux_encoded_video_to_mp4(packets, fps=1)

    assert mp4_bytes is not None
    mp4_path = tmp_path / "remuxed.mp4"
    mp4_path.write_bytes(mp4_bytes)
    container = av.open(str(mp4_path))
    decoded = list(container.decode(video=0))
    assert len(decoded) == 4
    stream = container.streams.video[0]
    assert stream.duration is not None
    assert stream.time_base is not None
    duration_s = float(stream.duration * stream.time_base)
    assert 1.5 <= duration_s <= 2.5


def test_remux_encoded_video_to_mp4_rejects_non_keyframe_start():
    packets = [_pkt(1_000), _pkt(1_500)]

    assert remux_encoded_video_to_mp4(packets, fps=2) is None


def test_remux_encoded_video_to_mp4_skips_h265_until_omni_compatibility_is_known():
    packets = [
        _pkt(1_000, keyframe=True, codec="h265"),
        _pkt(1_500, codec="h265"),
    ]

    assert remux_encoded_video_to_mp4(packets, fps=2) is None


def test_remux_encoded_video_to_mp4_handles_duplicate_wall_ms(tmp_path):
    import av
    import numpy as np

    raw_path = tmp_path / "source-duplicate-wall.h264"
    out = av.open(str(raw_path), "w", format="h264")
    stream = out.add_stream("libx264", rate=4)
    stream.width = 64
    stream.height = 64
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "ultrafast", "tune": "zerolatency"}

    packets: list[EncodedVideoPacket] = []
    for idx in range(4):
        frame_data = np.zeros((64, 64, 3), dtype=np.uint8)
        frame_data[:, :, 1] = idx * 40
        frame = av.VideoFrame.from_ndarray(frame_data, format="bgr24")
        for packet in stream.encode(frame):
            packets.append(
                EncodedVideoPacket(
                    codec="h264",
                    data=bytes(packet),
                    stream_ts=idx * 250,
                    wall_ms=1_000,
                    sequence=len(packets),
                    is_keyframe=bool(packet.is_keyframe),
                )
            )
            out.mux(packet)
    for packet in stream.encode():
        packets.append(
            EncodedVideoPacket(
                codec="h264",
                data=bytes(packet),
                stream_ts=len(packets) * 250,
                wall_ms=1_000,
                sequence=len(packets),
                is_keyframe=bool(packet.is_keyframe),
            )
        )
        out.mux(packet)
    out.close()

    assert packets[0].is_keyframe

    mp4_bytes = remux_encoded_video_to_mp4(packets, fps=4)

    assert mp4_bytes is not None
    mp4_path = tmp_path / "duplicate-wall-remuxed.mp4"
    mp4_path.write_bytes(mp4_bytes)
    decoded = list(av.open(str(mp4_path)).decode(video=0))
    assert len(decoded) == 4
