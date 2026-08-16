"""Decoder for the Phase 1 IMU stream packet.

Wire format, all multi-byte fields little-endian:

    [seq:u8][n:u8][t0_ms:u32][ax,ay,az,gx,gy,gz : 6 x int16] x n

This mirrors lib/protocol/stream_packet.cpp. The two must stay in step;
tests/test_decode.py shares its byte fixtures with the C++ unit tests.
"""

import struct
from dataclasses import dataclass

SAMPLES_PER_PACKET = 10
HEADER_LEN = 6
SAMPLE_LEN = 12

# Must match lib/mpu6050/mpu6050_scaling.h.
ACCEL_LSB_PER_G = 4096.0   # AFS_SEL = 2  (+/- 8 g)
GYRO_LSB_PER_DPS = 65.5    # FS_SEL  = 1  (+/- 500 dps)

_HEADER = struct.Struct("<BBI")
_SAMPLE = struct.Struct("<6h")


@dataclass
class Packet:
    """One decoded batch. Samples are (ax, ay, az) in g, (gx, gy, gz) in deg/s."""

    seq: int
    t0_ms: int
    samples: list[tuple[float, float, float, float, float, float]]


def decode_packet(data: bytes) -> Packet:
    if len(data) < HEADER_LEN:
        raise ValueError(
            f"packet too short for header: {len(data)} < {HEADER_LEN}"
        )

    seq, n, t0_ms = _HEADER.unpack_from(data, 0)

    if n > SAMPLES_PER_PACKET:
        raise ValueError(f"claimed {n} samples, maximum is {SAMPLES_PER_PACKET}")

    expected = HEADER_LEN + n * SAMPLE_LEN
    if len(data) != expected:
        raise ValueError(
            f"length mismatch: got {len(data)} bytes, expected {expected} "
            f"for {n} samples"
        )

    samples = []
    for i in range(n):
        ax, ay, az, gx, gy, gz = _SAMPLE.unpack_from(
            data, HEADER_LEN + i * SAMPLE_LEN
        )
        samples.append((
            ax / ACCEL_LSB_PER_G,
            ay / ACCEL_LSB_PER_G,
            az / ACCEL_LSB_PER_G,
            gx / GYRO_LSB_PER_DPS,
            gy / GYRO_LSB_PER_DPS,
            gz / GYRO_LSB_PER_DPS,
        ))

    return Packet(seq=seq, t0_ms=t0_ms, samples=samples)
