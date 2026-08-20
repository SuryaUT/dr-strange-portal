// Key ring firmware. A TTP223 capacitive touch pad on the ring arms and disarms
// the portal: the portal ring's circle gesture only counts while this one is
// armed. State goes out over BLE as a single byte, and to serial for debugging.
//
// The TTP223 runs in its default momentary mode: the output follows the pad, so
// the ring is armed while you are touching it and disarmed when you let go.
//
// KNOWN LIMITATION, and it is a hardware one. This chip re-baselines its own
// capacitance reference roughly every 7 seconds - measured on this ring, not
// taken from the datasheet. It detects *changes* in capacitance, so anything
// held longer than that becomes the new "untouched" zero and reads as released
// while you are still touching it. The practical effect is that a touch arms the
// key ring for about 7 seconds and then drops on its own.
//
// That is enough for the gesture, which takes about 1.2 seconds, so the demo
// works: touch the pad, draw the circle, done. But this ring cannot report
// sustained wear, and no amount of firmware can see through it - the baseline
// lives in the chip. Two ways out if it ever matters, neither taken here:
// bridging the solder pad marked A straps the chip into toggle mode, where the
// output latches on each touch and holds indefinitely (at the cost of no longer
// tracking whether the ring is actually on your finger); or replacing the TTP223
// with two bare contacts read as a resistance through skin, which measures
// presence directly and has no baseline to drift.
//
// Wiring (Seeed XIAO ESP32-C3):
//   TTP223 VCC -> D9   driven high by the firmware, not tied to 3V3
//   TTP223 IO  -> D10
//   TTP223 GND -> GND

#include <Arduino.h>
#include <NimBLEDevice.h>

namespace {

// Its own device name and service, separate from the portal ring's, so the
// laptop holds two independent connections and either can drop without
// disturbing the other. Mirrors DEVICE_NAME / STREAM_UUID on the portal ring;
// the host copies live in host/portal/stream_client.py.
constexpr char DEVICE_NAME[]  = "StrangeKey";
constexpr char SERVICE_UUID[] = "6e401001-b5a3-f393-e0a9-e50e24dcca9e";
constexpr char STATE_UUID[]   = "6e401003-b5a3-f393-e0a9-e50e24dcca9e";

// The sensor's supply is a GPIO because the original plan was to cycle it once a
// second, forcing the chip's re-calibration to a known moment. That plan was
// abandoned: re-calibrating while the pad is touched makes the touched state the
// new zero, so power cycling reports "not touched" permanently - it destroys the
// very signal it was meant to protect. The pin is simply held HIGH.
//
// D9 is GPIO9, which the chip samples at reset to pick its boot mode; low means
// serial-download mode instead of running firmware. Held high, that is a
// non-issue. Rewiring VCC to the 3V3 rail would free the pin up entirely.
constexpr int PIN_TOUCH_PWR = D9;
constexpr int PIN_TOUCH_OUT = D10;

// TTP223 breakouts ship active high: the output goes high on touch. The solder
// pads on the back can invert that, so flip this if your board is set that way.
constexpr bool ACTIVE_HIGH = true;

// The datasheet asks for roughly half a second after power-up before the output
// means anything - that is the chip sampling its untouched baseline. Touching
// the pad during this window teaches it the wrong baseline.
constexpr uint32_t CALIBRATION_MS = 500;

// Printed even when nothing changes, so a quiet serial monitor can be told
// apart from a wedged board.
constexpr uint32_t HEARTBEAT_MS = 2000;

bool g_armed = false;
uint32_t g_last_heartbeat_ms = 0;

NimBLECharacteristic* g_state = nullptr;
bool g_connected = false;

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* server) override {
        g_connected = true;
        Serial.println("laptop connected");
    }
    void onDisconnect(NimBLEServer* server) override {
        g_connected = false;
        Serial.println("laptop disconnected");
        NimBLEDevice::startAdvertising();
    }
};

// Reads the pad directly. True while a finger is on it, subject to the 7-second
// re-baseline described at the top of this file.
bool read_armed() {
    const bool level = digitalRead(PIN_TOUCH_OUT) == HIGH;
    return ACTIVE_HIGH ? level : !level;
}

// The stored value is always current, even with nobody connected, because the
// characteristic is readable as well as notifying. A laptop that connects after
// the ring was already armed reads the truth immediately instead of showing a
// disarmed portal until the next tap.
void publish_armed() {
    if (g_state == nullptr) return;
    uint8_t byte = g_armed ? 1 : 0;
    g_state->setValue(&byte, 1);
    if (g_connected) g_state->notify();
}

void init_ble() {
    NimBLEDevice::init(DEVICE_NAME);

    NimBLEServer* server = NimBLEDevice::createServer();
    server->setCallbacks(new ServerCallbacks());

    NimBLEService* service = server->createService(SERVICE_UUID);
    g_state = service->createCharacteristic(
        STATE_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
    service->start();

    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    adv->addServiceUUID(SERVICE_UUID);
    adv->setScanResponse(true);
    NimBLEDevice::startAdvertising();
}

// Timestamps stay in the output because they are how the 7-second re-baseline
// was measured in the first place, and how you would re-measure it on a new
// breakout: touch and hold, then read the gap to the unprompted DISARMED.
void report(const char* label) {
    Serial.printf("[%8lu ms] %s\n", static_cast<unsigned long>(millis()), label);
}

}  // namespace

void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 3000) { }

    // Write the level before switching the pin to an output. D9 is GPIO9, which
    // the chip samples at reset to choose its boot mode, so it should never be
    // driven low even briefly by our own startup.
    digitalWrite(PIN_TOUCH_PWR, HIGH);
    pinMode(PIN_TOUCH_PWR, OUTPUT);
    digitalWrite(PIN_TOUCH_PWR, HIGH);

    // The TTP223 drives its output push-pull and easily overpowers the internal
    // pulldown, so this costs nothing while the sensor is powered. It earns its
    // keep when the sensor is unplugged or unpowered: the pin reads a settled
    // OFF instead of floating noise.
    pinMode(PIN_TOUCH_OUT, INPUT_PULLDOWN);

    Serial.println("key ring: powering sensor on D9, reading touch on D10");
    delay(CALIBRATION_MS);

    // Read rather than assume. Normally nobody is touching the pad at boot and
    // this is false, but assuming that would publish a stale byte over BLE for
    // the first few milliseconds if a finger happened to be resting on it.
    g_armed = read_armed();
    g_last_heartbeat_ms = millis();

    init_ble();
    publish_armed();
    Serial.printf("advertising as %s\n", DEVICE_NAME);
    report(g_armed ? "READY, ARMED" : "READY, DISARMED");
}

void loop() {
    const bool now_armed = read_armed();
    if (now_armed != g_armed) {
        g_armed = now_armed;
        publish_armed();
        report(g_armed ? "ARMED" : "DISARMED");
    }

    const uint32_t now = millis();
    if (now - g_last_heartbeat_ms >= HEARTBEAT_MS) {
        g_last_heartbeat_ms = now;
        Serial.printf("[%8lu ms] ... %s   %s\n", static_cast<unsigned long>(now),
                      g_armed ? "ARMED" : "DISARMED",
                      g_connected ? "(laptop connected)" : "(advertising)");
    }

    delay(5);
}
