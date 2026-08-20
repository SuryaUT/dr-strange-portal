"""Drive the portal live from the ring over BLE.

    python -m portal.live                      # live portal state
    python -m portal.live --csv session.csv    # and record the raw stream
    python -m portal.live --debug              # show the gate internals
    python -m portal.live --no-key             # without the key ring

Prints what the portal should be doing, right now, from real gestures:
clockwise opens it, counter-clockwise closes it, and it holds state when your
hand stops. The key ring on the other hand must be armed or nothing moves. This is the same Detector and PortalState the offline simulation
uses -- `test_detector_is_causal_and_streaming` pins the streaming path to be
sample-identical to the batch one, so what you see here is what the recorded
captures produce.
"""
import argparse
import asyncio
import csv
import sys
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner

from portal.decode import decode_packet
from portal.detect import Detector, DetectorConfig
from portal.simulate import CLOSED, OPEN, PortalConfig, PortalState
from portal.stream_client import (CSV_HEADER, DEVICE_NAME, SAMPLE_PERIOD_MS,
                                  STREAM_UUID, StreamStats)

SAMPLE_RATE_HZ = 1000.0 / SAMPLE_PERIOD_MS


def bar(openness: float, width: int = 28) -> str:
    filled = int(round(openness * width))
    return "#" * filled + "-" * (width - filled)


async def run(csv_path: str | None, debug: bool, use_key: bool) -> int:
    # The key ring runs on its own thread and its own connection, exactly as it
    # does under the renderer, so this tool shows the same gating the projector
    # will. Without it this display would happily report portals the renderer
    # refuses to draw.
    key = None
    if use_key:
        from portal.ring import KeySource
        key = KeySource().start()
        print(f"scanning for {key.device_name} (the key ring)...")

    print(f"scanning for {DEVICE_NAME}...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=15.0)
    if device is None:
        print(f"error: no device named {DEVICE_NAME} found", file=sys.stderr)
        print("check the ring is powered and advertising", file=sys.stderr)
        return 1
    print(f"found {device.address}, connecting...")

    det = Detector(SAMPLE_RATE_HZ, DetectorConfig())
    portal = PortalState(SAMPLE_RATE_HZ, PortalConfig())
    stats = StreamStats()

    csv_file = None
    writer = None
    if csv_path:
        csv_file = open(csv_path, "w", newline="")
        writer = csv.writer(csv_file)
        writer.writerow(CSV_HEADER)
        print(f"recording to {csv_path}")

    state = {"last": CLOSED, "t0": time.monotonic(), "since": time.monotonic()}

    def on_notify(_sender, data: bytearray) -> None:
        try:
            pkt = decode_packet(bytes(data))
        except ValueError as exc:
            print(f"\nmalformed packet: {exc}", file=sys.stderr)
            return

        stats.note(pkt.seq, len(pkt.samples))
        host_time = time.monotonic()

        # Sampled once per packet: one consistent answer for the whole batch
        # beats a gate that could flip partway through it.
        armed = True if key is None else key.armed

        frame = None
        for i, s in enumerate(pkt.samples):
            ax, ay, az, gx, gy, gz = s
            frame = det.push((ax, ay, az))      # gyro deliberately unused
            now, openness = portal.push(frame, armed=armed)

            if now != state["last"] and now in (OPEN, CLOSED):
                held = host_time - state["since"]
                print(f"\r{' ' * 96}\r"
                      f"[{host_time - state['t0']:7.2f}s]  PORTAL {now}"
                      f"   (was {state['last']} for {held:.1f}s)", flush=True)
                state["last"] = now
                state["since"] = host_time

            if writer is not None:
                writer.writerow([
                    f"{host_time:.4f}",
                    pkt.t0_ms + i * SAMPLE_PERIOD_MS,
                    pkt.seq,
                    *(f"{v:.4f}" for v in s),
                ])

        if frame is None:
            return

        # One display update per packet (~10 Hz); per-sample would flicker.
        sense = {1: "ccw", -1: "cw ", 0: "   "}[frame.direction]
        gate = "" if key is None else ("KEY " if armed else "----")
        line = (f"\r{gate}{portal.latched:<6} [{bar(portal.openness)}] "
                f"{portal.openness * 100:3.0f}%  {sense}")
        if debug:
            line += (f"  circ {frame.circularity:4.2f} "
                     f"stab {frame.stability:4.2f} "
                     f"r {frame.radius_m:4.2f}m "
                     f"{frame.freq_hz:4.2f}Hz "
                     f"{'GATE' if frame.gate_open else '....'}")
        line += f"  {stats.rate_hz:5.1f}Hz drop {stats.dropped}"
        print(line, end="", flush=True)

    try:
        async with BleakClient(device) as client:
            await client.start_notify(STREAM_UUID, on_notify)
            print("live. circle counter-clockwise to open, clockwise to close.")
            print("press Ctrl-C to stop.\n")
            while client.is_connected:
                await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if key is not None:
            key.stop()
        if csv_file is not None:
            csv_file.close()
        print()
        print(f"packets {stats.packets}  samples {stats.samples}  "
              f"dropped {stats.dropped}  mean rate {stats.rate_hz:.1f} Hz")
        if stats.dropped > stats.samples * 0.02:
            print("WARNING: heavy packet loss. Gaps look like stillness to the "
                  "detector, so gestures will be missed.", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv", help="also record the raw stream to this file")
    ap.add_argument("--debug", action="store_true",
                    help="show circularity, stability, radius and gate state")
    ap.add_argument("--no-key", action="store_true",
                    help="ignore the key ring and let the gesture open the "
                         "portal on its own")
    args = ap.parse_args()
    try:
        return asyncio.run(run(args.csv, args.debug, use_key=not args.no_key))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
