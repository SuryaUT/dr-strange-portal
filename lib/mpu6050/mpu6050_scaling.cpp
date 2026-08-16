#include "mpu6050_scaling.h"

namespace mpu6050 {

static inline int16_t be16(const uint8_t* p) {
    return static_cast<int16_t>((static_cast<uint16_t>(p[0]) << 8) |
                                 static_cast<uint16_t>(p[1]));
}

RawSample parse_burst(const uint8_t* buf) {
    RawSample r;
    r.ax   = be16(buf + 0);
    r.ay   = be16(buf + 2);
    r.az   = be16(buf + 4);
    r.temp = be16(buf + 6);
    r.gx   = be16(buf + 8);
    r.gy   = be16(buf + 10);
    r.gz   = be16(buf + 12);
    return r;
}

Sample to_physical(const RawSample& raw) {
    Sample s;
    s.ax = raw.ax / ACCEL_LSB_PER_G;
    s.ay = raw.ay / ACCEL_LSB_PER_G;
    s.az = raw.az / ACCEL_LSB_PER_G;
    s.gx = raw.gx / GYRO_LSB_PER_DPS;
    s.gy = raw.gy / GYRO_LSB_PER_DPS;
    s.gz = raw.gz / GYRO_LSB_PER_DPS;
    s.temp_c = raw.temp / 340.0f + 36.53f;
    return s;
}

}  // namespace mpu6050
