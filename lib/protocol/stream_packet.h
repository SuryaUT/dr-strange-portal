#pragma once
#include <stdint.h>
#include "mpu6050_scaling.h"

namespace protocol {

constexpr int SAMPLES_PER_PACKET = 10;
constexpr int HEADER_LEN         = 6;   // seq(1) + n(1) + t0_ms(4)
constexpr int SAMPLE_LEN         = 12;  // 6 x int16
constexpr int MAX_PACKET_LEN     = HEADER_LEN + SAMPLES_PER_PACKET * SAMPLE_LEN;

// Encodes a batch into `out`, which must hold MAX_PACKET_LEN bytes.
// All multi-byte fields are little-endian. Temperature is not transmitted.
// Returns bytes written, or -1 if n > SAMPLES_PER_PACKET.
int encode_packet(uint8_t seq,
                  uint32_t t0_ms,
                  const mpu6050::RawSample* samples,
                  uint8_t n,
                  uint8_t* out);

}  // namespace protocol
