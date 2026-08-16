#pragma once
#include <stdint.h>

namespace mpu6050 {

// I2C
constexpr uint8_t I2C_ADDR       = 0x68;  // AD0 tied low
constexpr uint8_t WHO_AM_I_VALUE = 0x68;

// Registers
constexpr uint8_t REG_SMPLRT_DIV   = 0x19;
constexpr uint8_t REG_CONFIG       = 0x1A;
constexpr uint8_t REG_GYRO_CONFIG  = 0x1B;
constexpr uint8_t REG_ACCEL_CONFIG = 0x1C;
constexpr uint8_t REG_INT_PIN_CFG  = 0x37;
constexpr uint8_t REG_INT_ENABLE   = 0x38;
constexpr uint8_t REG_INT_STATUS   = 0x3A;
constexpr uint8_t REG_ACCEL_XOUT_H = 0x3B;
constexpr uint8_t REG_PWR_MGMT_1   = 0x6B;
constexpr uint8_t REG_WHO_AM_I     = 0x75;

// Configuration values
// Use the gyro X PLL as the clock source; more stable than the internal
// oscillator, and it clears the SLEEP bit.
constexpr uint8_t CFG_PWR_MGMT_1  = 0x01;
constexpr uint8_t CFG_SMPLRT_DIV  = 9;     // 1000 / (1 + 9) = 100 Hz
constexpr uint8_t CFG_DLPF        = 0x03;  // ~44 Hz accel / 42 Hz gyro
constexpr uint8_t CFG_GYRO_500DPS = 0x08;  // FS_SEL  = 1
constexpr uint8_t CFG_ACCEL_8G    = 0x10;  // AFS_SEL = 2

// One burst read covers accel (6) + temperature (2) + gyro (6).
constexpr int BURST_READ_LEN = 14;

}  // namespace mpu6050
