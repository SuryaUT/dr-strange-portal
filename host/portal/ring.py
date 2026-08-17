"""Openness for the renderer: live from the ring, or replayed from a capture.

The renderer's whole input is one scalar in [0,1]. This module is what produces
it, running the same detector and the same latching state machine that
`portal.live` prints to a terminal -- so what you see on the wall is driven by
exactly the code the golden tests pin against real captures.

Counter-clockwise opens, clockwise closes, and a hand that stops changes
nothing: the portal latches. See `OPENING_SENSE` in `portal.simulate`.
"""
import csv
import threading
import time
from pathlib import Path

import numpy as np

from .detect import Detector, DetectorConfig
from .simulate import PortalConfig, PortalState
from .stream_client import SAMPLE_PERIOD_MS

SAMPLE_RATE_HZ = 1000.0 / SAMPLE_PERIOD_MS


class GestureTracker:
    """Accelerometer samples in, portal openness out.

    Thin wrapper holding the detector and the state machine together so that
    every source -- BLE, a capture, a test -- drives the portal through
    identical code. The gyro is deliberately unused: the Phase 1 data showed a
    gyro veto rejected real gestures without catching anything the
    accelerometer missed.
    """

    def __init__(self, sample_rate_hz=SAMPLE_RATE_HZ,
                 detector_config=None, portal_config=None):
        self.detector = Detector(sample_rate_hz, detector_config or DetectorConfig())
        self.portal = PortalState(sample_rate_hz, portal_config or PortalConfig())
        self.frame = None

    def push(self, acc):
        """One (ax, ay, az) sample in g. Returns openness in [0,1]."""
        self.frame = self.detector.push((float(acc[0]), float(acc[1]), float(acc[2])))
        _latched, openness = self.portal.push(self.frame)
        return openness

    @property
    def openness(self):
        return self.portal.openness

    @property
    def latched(self):
        return self.portal.latched

    @property
    def direction(self):
        return 0 if self.frame is None else self.frame.direction


class ReplaySource:
    """Openness from a recorded capture, for driving the renderer with no ring.

    `speed` is a multiple of real time; 0 runs as fast as the CPU allows, which
    is what the tests want. Anything else paces the samples so the portal opens
    over the same 1.2 seconds it did when the capture was made.
    """

    def __init__(self, path, speed=1.0, loop=False):
        self.path = Path(path)
        self.speed = speed
        self.loop = loop
        self.tracker = GestureTracker()
        self.samples_seen = 0
        self._acc = self._load()
        self._stop = threading.Event()
        self._thread = None

    def _load(self):
        with open(self.path, newline="") as handle:
            rows = list(csv.DictReader(handle))
        return np.array([[float(r["ax_g"]), float(r["ay_g"]), float(r["az_g"])]
                         for r in rows], dtype=float)

    @property
    def openness(self):
        return self.tracker.openness

    @property
    def latched(self):
        return self.tracker.latched

    @property
    def status(self):
        return f"replay {self.path.name}"

    def run_to_end(self):
        for sample in self._acc:
            self.tracker.push(sample)
            self.samples_seen += 1

    def _play(self):
        period = 0.0 if self.speed <= 0 else 1.0 / (SAMPLE_RATE_HZ * self.speed)
        while not self._stop.is_set():
            start = time.perf_counter()
            for i, sample in enumerate(self._acc):
                if self._stop.is_set():
                    return
                self.tracker.push(sample)
                self.samples_seen += 1
                if period:
                    due = start + (i + 1) * period
                    slack = due - time.perf_counter()
                    if slack > 0:
                        self._stop.wait(slack)
            if not self.loop:
                return

    def start(self):
        self._thread = threading.Thread(target=self._play, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


class RingSource:
    """Live openness from the ring over BLE, on its own thread.

    Owns an asyncio loop in a background thread so the renderer never waits on
    Bluetooth. Openness is a plain float written by that thread and read by the
    render loop; no lock, because a torn read of a float is not possible here
    and a one-frame-stale value is invisible at 56fps.
    """

    def __init__(self, device_name=None, on_event=None):
        from .stream_client import DEVICE_NAME
        self.device_name = device_name or DEVICE_NAME
        self.tracker = GestureTracker()
        self.connected = False
        self.error = None
        self.samples_seen = 0
        self.packets_seen = 0
        self._on_event = on_event
        self._last_latched = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def openness(self):
        return self.tracker.openness

    @property
    def latched(self):
        return self.tracker.latched

    @property
    def status(self):
        if self.error:
            return f"ring: {self.error}"
        if not self.connected:
            return f"looking for {self.device_name}..."
        return f"ring connected  {self.packets_seen} packets"

    def _on_notify(self, _sender, data):
        from .decode import decode_packet
        try:
            packet = decode_packet(bytes(data))
        except ValueError:
            return                      # a dropped packet is not worth a stall
        self.packets_seen += 1
        for sample in packet.samples:
            self.tracker.push(sample[:3])        # gyro deliberately unused
            self.samples_seen += 1
        if self.tracker.latched != self._last_latched:
            self._last_latched = self.tracker.latched
            if self._on_event:
                self._on_event(self.tracker.latched)

    async def _run(self):
        from bleak import BleakClient, BleakScanner
        from .stream_client import STREAM_UUID
        while not self._stop.is_set():
            device = await BleakScanner.find_device_by_name(self.device_name,
                                                            timeout=10.0)
            if device is None:
                self.error = f"no device named {self.device_name}"
                continue
            try:
                async with BleakClient(device) as client:
                    await client.start_notify(STREAM_UUID, self._on_notify)
                    self.connected, self.error = True, None
                    while client.is_connected and not self._stop.is_set():
                        await __import__("asyncio").sleep(0.2)
            except Exception as exc:                  # noqa: BLE001
                self.error = str(exc)
            finally:
                self.connected = False

    def _thread_main(self):
        import asyncio
        asyncio.run(self._run())

    def start(self):
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
