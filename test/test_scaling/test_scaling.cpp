#include <unity.h>
#include "mpu6050_scaling.h"

void setUp(void) {}
void tearDown(void) {}

void test_parse_burst_is_big_endian(void) {
    // ax = 0x0102, ay = 0xFFFE (-2), az = 0x1000,
    // temp = 0x0000, gx = 0x00FF, gy = 0x8000, gz = 0x0001
    const uint8_t buf[14] = {
        0x01, 0x02, 0xFF, 0xFE, 0x10, 0x00,
        0x00, 0x00,
        0x00, 0xFF, 0x80, 0x00, 0x00, 0x01
    };
    const mpu6050::RawSample r = mpu6050::parse_burst(buf);
    TEST_ASSERT_EQUAL_INT16(0x0102, r.ax);
    TEST_ASSERT_EQUAL_INT16(-2,     r.ay);
    TEST_ASSERT_EQUAL_INT16(0x1000, r.az);
    TEST_ASSERT_EQUAL_INT16(255,    r.gx);
    TEST_ASSERT_EQUAL_INT16(-32768, r.gy);
    TEST_ASSERT_EQUAL_INT16(1,      r.gz);
}

void test_accel_scaling_at_8g(void) {
    // At AFS_SEL = 2 the sensitivity is 4096 LSB/g.
    mpu6050::RawSample r = {};
    r.ax = 4096;   // +1 g
    r.ay = -2048;  // -0.5 g
    r.az = 0;
    const mpu6050::Sample s = mpu6050::to_physical(r);
    TEST_ASSERT_FLOAT_WITHIN(0.001f,  1.0f, s.ax);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, -0.5f, s.ay);
    TEST_ASSERT_FLOAT_WITHIN(0.001f,  0.0f, s.az);
}

void test_gyro_scaling_at_500dps(void) {
    // At FS_SEL = 1 the sensitivity is 65.5 LSB/(deg/s).
    mpu6050::RawSample r = {};
    r.gx = 6550;   // +100 deg/s
    r.gy = -655;   // -10 deg/s
    const mpu6050::Sample s = mpu6050::to_physical(r);
    TEST_ASSERT_FLOAT_WITHIN(0.01f,  100.0f, s.gx);
    TEST_ASSERT_FLOAT_WITHIN(0.01f,  -10.0f, s.gy);
}

void test_temperature_conversion(void) {
    // Datasheet: degrees C = raw / 340 + 36.53
    mpu6050::RawSample r = {};
    r.temp = 0;
    const mpu6050::Sample s = mpu6050::to_physical(r);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 36.53f, s.temp_c);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_parse_burst_is_big_endian);
    RUN_TEST(test_accel_scaling_at_8g);
    RUN_TEST(test_gyro_scaling_at_500dps);
    RUN_TEST(test_temperature_conversion);
    return UNITY_END();
}
