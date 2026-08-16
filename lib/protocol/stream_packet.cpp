#include "stream_packet.h"

namespace protocol {

static inline void put_u16le(uint8_t* p, int16_t v) {
    const uint16_t u = static_cast<uint16_t>(v);
    p[0] = static_cast<uint8_t>(u & 0xFF);
    p[1] = static_cast<uint8_t>((u >> 8) & 0xFF);
}

int encode_packet(uint8_t seq,
                  uint32_t t0_ms,
                  const mpu6050::RawSample* samples,
                  uint8_t n,
                  uint8_t* out) {
    if (n > SAMPLES_PER_PACKET) return -1;

    out[0] = seq;
    out[1] = n;
    out[2] = static_cast<uint8_t>(t0_ms & 0xFF);
    out[3] = static_cast<uint8_t>((t0_ms >> 8) & 0xFF);
    out[4] = static_cast<uint8_t>((t0_ms >> 16) & 0xFF);
    out[5] = static_cast<uint8_t>((t0_ms >> 24) & 0xFF);

    uint8_t* p = out + HEADER_LEN;
    for (uint8_t i = 0; i < n; ++i) {
        put_u16le(p + 0,  samples[i].ax);
        put_u16le(p + 2,  samples[i].ay);
        put_u16le(p + 4,  samples[i].az);
        put_u16le(p + 6,  samples[i].gx);
        put_u16le(p + 8,  samples[i].gy);
        put_u16le(p + 10, samples[i].gz);
        p += SAMPLE_LEN;
    }
    return HEADER_LEN + n * SAMPLE_LEN;
}

}  // namespace protocol
