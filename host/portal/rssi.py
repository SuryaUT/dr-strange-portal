"""Live signal-strength meter for the ring, for diagnosing RF problems.

Run this, then change one thing at a time — lid on, lid off, antenna moved,
ring rotated — and watch the number. It quantifies what "sometimes it works"
actually means.

    python -m portal.rssi

Note: the ring must NOT be connected while this runs. A connected peripheral
stops advertising, and this reads RSSI from advertisements.
"""

import asyncio
import sys
import time
from collections import deque

from bleak import BleakScanner

DEVICE_NAME = "StrangeRing"
WINDOW = 10  # advertisements averaged for the rolling figure


def verdict(dbm: float) -> str:
    """Rough guidance for a 2.4 GHz link at this range."""
    if dbm > -60:
        return "excellent"
    if dbm > -70:
        return "good"
    if dbm > -80:
        return "workable - some loss likely on long captures"
    if dbm > -90:
        return "MARGINAL - expect dropped packets"
    return "BAD - link will not hold"


def bar(dbm: float, width: int = 40) -> str:
    """Map -100..-40 dBm onto a bar so changes are visible at a glance."""
    frac = max(0.0, min(1.0, (dbm + 100.0) / 60.0))
    filled = int(frac * width)
    return "#" * filled + "." * (width - filled)


async def run() -> int:
    recent: deque[float] = deque(maxlen=WINDOW)
    seen = 0
    last_print = 0.0

    def on_detect(device, adv) -> None:
        nonlocal seen, last_print
        if device.name != DEVICE_NAME:
            return
        seen += 1
        recent.append(float(adv.rssi))
        now = time.monotonic()
        if now - last_print < 0.25:      # cap the refresh rate
            return
        last_print = now
        mean = sum(recent) / len(recent)
        print(f"\r{mean:6.1f} dBm  [{bar(mean)}]  {verdict(mean):<38}"
              f" n={seen}", end="", flush=True)

    print(f"scanning for {DEVICE_NAME}. Ctrl-C to stop.")
    print("Make sure the ring is NOT connected to anything else.\n")

    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        while True:
            await asyncio.sleep(0.5)
            if seen == 0:
                print("\rwaiting for advertisements...", end="", flush=True)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await scanner.stop()
        print()
        if recent:
            mean = sum(recent) / len(recent)
            print(f"last rolling mean: {mean:.1f} dBm ({verdict(mean)})")
        else:
            print("no advertisements seen at all - ring off, or signal too weak")
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
