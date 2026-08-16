#include <unity.h>
#include "mpu6050_regs.h"

void setUp(void) {}
void tearDown(void) {}

void test_i2c_address_and_identity(void) {
    TEST_ASSERT_EQUAL_HEX8(0x68, mpu6050::I2C_ADDR);
    TEST_ASSERT_EQUAL_HEX8(0x75, mpu6050::REG_WHO_AM_I);
    TEST_ASSERT_EQUAL_HEX8(0x68, mpu6050::WHO_AM_I_VALUE);
}

void test_sample_rate_divider_gives_100hz(void) {
    // With the DLPF enabled the gyro output rate is 1 kHz, and
    // sample_rate = 1000 / (1 + SMPLRT_DIV). We want 100 Hz.
    const int rate = 1000 / (1 + mpu6050::CFG_SMPLRT_DIV);
    TEST_ASSERT_EQUAL_INT(100, rate);
}

void test_range_configuration_bits(void) {
    // FS_SEL / AFS_SEL live in bits 4:3 of their config registers.
    TEST_ASSERT_EQUAL_HEX8(0x08, mpu6050::CFG_GYRO_500DPS);  // FS_SEL = 1
    TEST_ASSERT_EQUAL_HEX8(0x10, mpu6050::CFG_ACCEL_8G);     // AFS_SEL = 2
}

void test_burst_read_length(void) {
    // accel 6 bytes + temperature 2 + gyro 6
    TEST_ASSERT_EQUAL_INT(14, mpu6050::BURST_READ_LEN);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_i2c_address_and_identity);
    RUN_TEST(test_sample_rate_divider_gives_100hz);
    RUN_TEST(test_range_configuration_bits);
    RUN_TEST(test_burst_read_length);
    return UNITY_END();
}
