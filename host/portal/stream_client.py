"""Connects to the StrangeRing, prints live IMU values, and logs CSV.

Usage:
    python -m portal.stream_client                          # live display only
    python -m portal.stream_client --csv walk.csv           # display and log
    python -m portal.stream_client --csv gesture.csv --plot # log, then plot it
    python -m portal.stream_client --csv gesture.csv --quiet
"""

import argparse
import asyncio
import csv
import sys
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner

from portal.decode import decode_packet

DEVICE_NAME = "StrangeRing"
STREAM_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

CSV_HEADER = ["host_time_s", "device_ms", "seq", "ax_g", "ay_g", "az_g",
              "gx_dps", "gy_dps", "gz_dps"]

# The device batches this many samples per notification at 100 Hz.
SAMPLE_PERIOD_MS = 10


class StreamStats:
    """Tracks packet loss and rate so bad captures are caught while recording."""

    def __init__(self) -> None:
        self.packets = 0
        self.samples = 0
        self.dropped = 0
        self._last_seq: int | None = None
        self._started = time.monotonic()

    def note(self, seq: int, n: int) -> None:
        if self._last_seq is not None:
            gap = (seq - self._last_seq) & 0xFF
            if gap != 1:
                self.dropped += gap - 1
        self._last_seq = seq
        self.packets += 1
        self.samples += n

    @property
    def rate_hz(self) -> float:
        elapsed = time.monotonic() - self._started
        return self.samples / elapsed if elapsed > 0 else 0.0


async def run(csv_path: str | None, quiet: bool) -> int:
    print(f"scanning for {DEVICE_NAME}...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=15.0)
    if device is None:
        print(f"error: no device named {DEVICE_NAME} found", file=sys.stderr)
        print("check the ring is powered and advertising", file=sys.stderr)
        return 1

    print(f"found {device.address}, connecting...")

    stats = StreamStats()
    csv_file = None
    writer = None
    if csv_path:
        csv_file = open(csv_path, "w", newline="")
        writer = csv.writer(csv_file)
        writer.writerow(CSV_HEADER)
        print(f"logging to {csv_path}")

    def on_notify(_sender, data: bytearray) -> None:
        try:
            pkt = decode_packet(bytes(data))
        except ValueError as exc:
            print(f"malformed packet: {exc}", file=sys.stderr)
            return

        stats.note(pkt.seq, len(pkt.samples))
        host_time = time.monotonic()

        if writer is not None:
            for i, s in enumerate(pkt.samples):
                writer.writerow([
                    f"{host_time:.4f}",
                    pkt.t0_ms + i * SAMPLE_PERIOD_MS,
                    pkt.seq,
                    *(f"{v:.4f}" for v in s),
                ])

        if not quiet and pkt.samples:
            ax, ay, az, gx, gy, gz = pkt.samples[-1]
            mag = (ax * ax + ay * ay + az * az) ** 0.5
            print(
                f"\ra {ax:+6.2f} {ay:+6.2f} {az:+6.2f} |{mag:4.2f}|g  "
                f"g {gx:+7.1f} {gy:+7.1f} {gz:+7.1f} dps  "
                f"{stats.rate_hz:5.1f} Hz  drop {stats.dropped}",
                end="",
                flush=True,
            )

    try:
        async with BleakClient(device) as client:
            await client.start_notify(STREAM_UUID, on_notify)
            print("streaming. press Ctrl-C to stop.")
            while client.is_connected:
                await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if csv_file is not None:
            csv_file.close()
        print()
        print(f"packets {stats.packets}  samples {stats.samples}  "
              f"dropped {stats.dropped}  mean rate {stats.rate_hz:.1f} Hz")

    return 0


def write_plot(csv_path: str) -> None:
    """Plot a finished capture. Safe to call even if the capture is unusable."""
    # Imported here rather than at module scope so plain streaming never pays
    # matplotlib's import cost, and still runs if matplotlib is absent.
    from portal.plot import describe, plot_capture

    png_path = Path(csv_path).with_suffix(".png")
    try:
        print(describe(plot_capture(csv_path, png_path)))
        print(f"wrote {png_path}")
    except (OSError, ValueError, KeyError) as exc:
        print(f"could not plot capture: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stream IMU data from the ring.")
    parser.add_argument("--csv", help="write samples to this CSV file")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress the live display")
    parser.add_argument("--plot", action="store_true",
                        help="on exit, write a motion plot beside the CSV "
                             "(capture.csv -> capture.png); requires --csv")
    args = parser.parse_args()

    if args.plot and not args.csv:
        print("--plot needs --csv: there is nothing to plot without a capture",
              file=sys.stderr)

    try:
        rc = asyncio.run(run(args.csv, args.quiet))
    except KeyboardInterrupt:
        rc = 0

    # Plotting happens HERE, after the event loop has fully unwound, and not
    # inside run(). Ctrl-C raises KeyboardInterrupt out of asyncio.run() rather
    # than inside the coroutine, so anything placed after the streaming loop in
    # run() is skipped on the one exit path that actually gets used.
    if args.plot and args.csv and Path(args.csv).exists():
        write_plot(args.csv)

    return rc


if __name__ == "__main__":
    sys.exit(main())
