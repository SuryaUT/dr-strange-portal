#include <Arduino.h>
#include <Wire.h>
#include <NimBLEDevice.h>
#include "mpu6050_regs.h"
#include "mpu6050_scaling.h"
#include "stream_packet.h"

namespace {

constexpr int PIN_SDA = D4;
constexpr int PIN_SCL = D5;

constexpr char SERVICE_UUID[] = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
constexpr char STREAM_UUID[]  = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";
constexpr uint32_t SAMPLE_INTERVAL_US = 10000;  // 100 Hz

NimBLECharacteristic* g_stream = nullptr;
bool g_connected = false;

mpu6050::RawSample g_batch[protocol::SAMPLES_PER_PACKET];
uint8_t  g_batch_len = 0;
uint8_t  g_seq       = 0;
uint32_t g_batch_t0  = 0;
uint32_t g_next_us   = 0;

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* server) override {
        g_connected = true;
        Serial.println("connected");
    }
    void onDisconnect(NimBLEServer* server) override {
        g_connected = false;
        Serial.println("disconnected");
        NimBLEDevice::startAdvertising();
    }
};

bool write_reg(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(mpu6050::I2C_ADDR);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

bool read_regs(uint8_t reg, uint8_t* out, size_t len) {
    Wire.beginTransmission(mpu6050::I2C_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(static_cast<int>(mpu6050::I2C_ADDR),
                         static_cast<int>(len)) != static_cast<int>(len)) {
        return false;
    }
    for (size_t i = 0; i < len; ++i) out[i] = Wire.read();
    return true;
}

bool init_sensor() {
    uint8_t who = 0;
    if (!read_regs(mpu6050::REG_WHO_AM_I, &who, 1)) return false;
    if (who != mpu6050::WHO_AM_I_VALUE) return false;
    return write_reg(mpu6050::REG_PWR_MGMT_1,   mpu6050::CFG_PWR_MGMT_1)
        && write_reg(mpu6050::REG_SMPLRT_DIV,   mpu6050::CFG_SMPLRT_DIV)
        && write_reg(mpu6050::REG_CONFIG,       mpu6050::CFG_DLPF)
        && write_reg(mpu6050::REG_GYRO_CONFIG,  mpu6050::CFG_GYRO_500DPS)
        && write_reg(mpu6050::REG_ACCEL_CONFIG, mpu6050::CFG_ACCEL_8G);
}

void init_ble() {
    NimBLEDevice::init("StrangeRing");
    NimBLEDevice::setMTU(247);

    NimBLEServer* server = NimBLEDevice::createServer();
    server->setCallbacks(new ServerCallbacks());

    NimBLEService* service = server->createService(SERVICE_UUID);
    g_stream = service->createCharacteristic(
        STREAM_UUID, NIMBLE_PROPERTY::NOTIFY);
    service->start();

    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    adv->addServiceUUID(SERVICE_UUID);
    adv->setScanResponse(true);
    NimBLEDevice::startAdvertising();
}

void flush_batch() {
    if (g_batch_len == 0) return;
    uint8_t out[protocol::MAX_PACKET_LEN];
    const int n = protocol::encode_packet(
        g_seq, g_batch_t0, g_batch, g_batch_len, out);
    if (n > 0 && g_connected && g_stream != nullptr) {
        g_stream->setValue(out, n);
        g_stream->notify();
    }
    ++g_seq;
    g_batch_len = 0;
}

}  // namespace

void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 3000) { }

    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(400000);

    if (!init_sensor()) {
        Serial.println("MPU-6050 init FAILED");
    } else {
        Serial.println("MPU-6050 ready");
    }

    init_ble();
    Serial.println("advertising as StrangeRing");
    g_next_us = micros();
}

void loop() {
    const uint32_t now = micros();
    if (static_cast<int32_t>(now - g_next_us) < 0) return;
    g_next_us += SAMPLE_INTERVAL_US;

    uint8_t buf[mpu6050::BURST_READ_LEN];
    if (!read_regs(mpu6050::REG_ACCEL_XOUT_H, buf, sizeof(buf))) return;

    if (g_batch_len == 0) g_batch_t0 = millis();
    const mpu6050::RawSample raw = mpu6050::parse_burst(buf);
    g_batch[g_batch_len++] = raw;

#ifdef SERIAL_IMU
    // Build with -DSERIAL_IMU (env:xiao_serial_test) to watch the sensor on the
    // serial monitor. Printed at 10 Hz because 100 Hz is unreadable and the
    // printing itself would start costing sample timing.
    static uint32_t last_print_ms = 0;
    if (millis() - last_print_ms >= 100) {
        last_print_ms = millis();
        const mpu6050::Sample s = mpu6050::to_physical(raw);
        Serial.printf("a %+6.2f %+6.2f %+6.2f g   g %+7.1f %+7.1f %+7.1f dps   %.1f C\n",
                      s.ax, s.ay, s.az, s.gx, s.gy, s.gz, s.temp_c);
    }
#endif

    if (g_batch_len >= protocol::SAMPLES_PER_PACKET) flush_batch();
}
