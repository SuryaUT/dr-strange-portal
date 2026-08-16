#include <unity.h>
#include <string.h>
#include "stream_packet.h"

void setUp(void) {}
void tearDown(void) {}

void test_packet_layout_constants(void) {
    TEST_ASSERT_EQUAL_INT(6,  protocol::HEADER_LEN);
    TEST_ASSERT_EQUAL_INT(12, protocol::SAMPLE_LEN);
    TEST_ASSERT_EQUAL_INT(10, protocol::SAMPLES_PER_PACKET);
    // 6 + 10 * 12 = 126
    TEST_ASSERT_EQUAL_INT(126, protocol::MAX_PACKET_LEN);
}

void test_encode_single_sample(void) {
    mpu6050::RawSample s = {};
    s.ax = 1;  s.ay = -1;  s.az = 256;
    s.gx = 2;  s.gy = -2;  s.gz = 512;
    s.temp = 9999;  // must NOT appear in the packet

    uint8_t out[protocol::MAX_PACKET_LEN];
    const int n = protocol::encode_packet(0xAB, 0x11223344, &s, 1, out);

    TEST_ASSERT_EQUAL_INT(18, n);            // 6 header + 12 payload
    TEST_ASSERT_EQUAL_HEX8(0xAB, out[0]);    // seq
    TEST_ASSERT_EQUAL_HEX8(0x01, out[1]);    // n

    // t0_ms little-endian
    TEST_ASSERT_EQUAL_HEX8(0x44, out[2]);
    TEST_ASSERT_EQUAL_HEX8(0x33, out[3]);
    TEST_ASSERT_EQUAL_HEX8(0x22, out[4]);
    TEST_ASSERT_EQUAL_HEX8(0x11, out[5]);

    // ax = 1, ay = -1, az = 256, little-endian int16
    TEST_ASSERT_EQUAL_HEX8(0x01, out[6]);  TEST_ASSERT_EQUAL_HEX8(0x00, out[7]);
    TEST_ASSERT_EQUAL_HEX8(0xFF, out[8]);  TEST_ASSERT_EQUAL_HEX8(0xFF, out[9]);
    TEST_ASSERT_EQUAL_HEX8(0x00, out[10]); TEST_ASSERT_EQUAL_HEX8(0x01, out[11]);

    // gx = 2, gy = -2, gz = 512
    TEST_ASSERT_EQUAL_HEX8(0x02, out[12]); TEST_ASSERT_EQUAL_HEX8(0x00, out[13]);
    TEST_ASSERT_EQUAL_HEX8(0xFE, out[14]); TEST_ASSERT_EQUAL_HEX8(0xFF, out[15]);
    TEST_ASSERT_EQUAL_HEX8(0x00, out[16]); TEST_ASSERT_EQUAL_HEX8(0x02, out[17]);
}

void test_encode_full_packet_length(void) {
    mpu6050::RawSample s[protocol::SAMPLES_PER_PACKET] = {};
    uint8_t out[protocol::MAX_PACKET_LEN];
    const int n = protocol::encode_packet(
        0, 0, s, protocol::SAMPLES_PER_PACKET, out);
    TEST_ASSERT_EQUAL_INT(protocol::MAX_PACKET_LEN, n);
}

void test_encode_rejects_overlong_batch(void) {
    mpu6050::RawSample s[protocol::SAMPLES_PER_PACKET] = {};
    uint8_t out[protocol::MAX_PACKET_LEN];
    const int n = protocol::encode_packet(
        0, 0, s, protocol::SAMPLES_PER_PACKET + 1, out);
    TEST_ASSERT_EQUAL_INT(-1, n);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_packet_layout_constants);
    RUN_TEST(test_encode_single_sample);
    RUN_TEST(test_encode_full_packet_length);
    RUN_TEST(test_encode_rejects_overlong_batch);
    return UNITY_END();
}
