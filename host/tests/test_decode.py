import struct

import pytest

from portal.decode import (
    ACCEL_LSB_PER_G,
    GYRO_LSB_PER_DPS,
    HEADER_LEN,
    SAMPLE_LEN,
    SAMPLES_PER_PACKET,
    decode_packet,
)


# Byte-for-byte the same fixture as test_encode_single_sample in
# test/test_packet/test_packet.cpp. If the firmware format changes
# without this changing too, this test fails.
SINGLE_SAMPLE_PACKET = bytes([
    0xAB,                                # seq
    0x01,                                # n
    0x44, 0x33, 0x22, 0x11,              # t0_ms = 0x11223344
    0x01, 0x00, 0xFF, 0xFF, 0x00, 0x01,  # ax=1, ay=-1, az=256
    0x02, 0x00, 0xFE, 0xFF, 0x00, 0x02,  # gx=2, gy=-2, gz=512
])


def test_layout_constants_match_firmware():
    assert HEADER_LEN == 6
    assert SAMPLE_LEN == 12
    assert SAMPLES_PER_PACKET == 10


def test_decode_header():
    pkt = decode_packet(SINGLE_SAMPLE_PACKET)
    assert pkt.seq == 0xAB
    assert pkt.t0_ms == 0x11223344
    assert len(pkt.samples) == 1


def test_decode_converts_to_physical_units():
    pkt = decode_packet(SINGLE_SAMPLE_PACKET)
    ax, ay, az, gx, gy, gz = pkt.samples[0]
    assert ax == pytest.approx(1 / ACCEL_LSB_PER_G)
    assert ay == pytest.approx(-1 / ACCEL_LSB_PER_G)
    assert az == pytest.approx(256 / ACCEL_LSB_PER_G)
    assert gx == pytest.approx(2 / GYRO_LSB_PER_DPS)
    assert gy == pytest.approx(-2 / GYRO_LSB_PER_DPS)
    assert gz == pytest.approx(512 / GYRO_LSB_PER_DPS)


def test_decode_full_packet():
    header = struct.pack("<BBI", 7, SAMPLES_PER_PACKET, 1000)
    body = b"".join(
        struct.pack("<6h", i, i, i, i, i, i)
        for i in range(SAMPLES_PER_PACKET)
    )
    pkt = decode_packet(header + body)
    assert pkt.seq == 7
    assert len(pkt.samples) == SAMPLES_PER_PACKET


def test_decode_rejects_truncated_header():
    with pytest.raises(ValueError):
        decode_packet(b"\x00\x01\x02")


def test_decode_rejects_length_mismatch():
    # Claims 5 samples but supplies none.
    with pytest.raises(ValueError):
        decode_packet(struct.pack("<BBI", 0, 5, 0))
