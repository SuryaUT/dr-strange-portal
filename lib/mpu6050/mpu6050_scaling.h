#pragma once
#include <stdint.h>
#include "mpu6050_regs.h"

namespace mpu6050 {

struct RawSample {
    int16_t ax, ay, az;
    int16_t temp;
    int16_t gx, gy, gz;
};

struct Sample {
    float ax, ay, az;      // g
    float gx, gy, gz;      // degrees/second
    float temp_c;          // degrees Celsius
};

// Sensitivities for the ranges fixed in mpu6050_regs.h.
constexpr float ACCEL_LSB_PER_G   = 4096.0f;  // AFS_SEL = 2  (+/- 8 g)
constexpr float GYRO_LSB_PER_DPS  = 65.5f;    // FS_SEL  = 1  (+/- 500 dps)

// buf must point to BURST_READ_LEN bytes read from REG_ACCEL_XOUT_H.
RawSample parse_burst(const uint8_t* buf);

Sample to_physical(const RawSample& raw);

}  // namespace mpu6050
