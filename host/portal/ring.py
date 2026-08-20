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

    def push(self, acc, armed: bool = True):
        """One (ax, ay, az) sample in g. Returns openness in [0,1].

        `armed` is the key ring. Note the detector still runs when disarmed --
        only the portal ignores it. Keeping the detector warm means an armed
        gesture starts from a settled filter rather than a cold one.
        """
        self.frame = self.detector.push((float(acc[0]), float(acc[1]), float(acc[2])))
        _latched, openness = self.portal.push(self.frame, armed=armed)
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


class BleSource:
    """A named BLE device, connected to forever, on a background thread.

    Both rings need identical plumbing -- own an asyncio loop off the render
    thread, find the device by name, and never give up -- so it lives here once.
    Subclasses supply `_attempt`, one scan-and-listen cycle, and everything
    around surviving its failure is inherited.
    """

    def __init__(self, device_name):
        self.device_name = device_name
        self.connected = False
        self.error = None
        self._stop = threading.Event()
        self._thread = None

    def _mark_disconnected(self):
        """Called whenever the link drops. Subclasses reset their state here."""
        self.connected = False

    async def _run(self, backoff=1.0):
        """Retry `_attempt` forever, surviving every failure.

        The scan itself can raise -- most commonly when Bluetooth is switched
        off -- so the whole attempt is inside the guard. Anything short of a
        crash keeps the thread alive and scanning, which is what lets a ring
        connect the moment the radio comes up, with no restart.
        """
        import asyncio

        friendly = {
            "powered off": "Bluetooth is off -- turn it on",
            "not powered on": "Bluetooth is off -- turn it on",
        }
        while not self._stop.is_set():
            try:
                await self._attempt()
            except Exception as exc:              # noqa: BLE001
                self._mark_disconnected()
                text = str(exc)
                self.error = next((msg for key, msg in friendly.items()
                                   if key in text.lower()), text)
            if not self._stop.is_set() and backoff:
                await asyncio.sleep(backoff)

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


class KeySource(BleSource):
    """Is the key ring being worn? One byte over BLE, on its own thread.

    Deliberately fails closed: `armed` is False until the key ring has actually
    said otherwise, and goes back to False the moment the link drops. A ring
    that cannot be heard from is not a ring that is being worn, and the safe
    reading of "I don't know" is no portal.

    Note this only stops the portal *responding* -- see `PortalState.push`,
    where disarming holds an already-open portal rather than slamming it shut.
    A brief dropout mid-scene therefore cannot cut the portal out of a shot.
    """

    def __init__(self, device_name=None):
        from .stream_client import KEY_DEVICE_NAME
        super().__init__(device_name or KEY_DEVICE_NAME)
        self.armed = False
        self.changes_seen = 0

    def _mark_disconnected(self):
        super()._mark_disconnected()
        self.armed = False

    @property
    def status(self):
        if self.error:
            return f"key: {self.error}"
        if not self.connected:
            return f"looking for {self.device_name}..."
        return f"key {'ARMED' if self.armed else 'disarmed'}"

    def _on_state(self, _sender, data):
        # An empty notification carries no state. Reading it as a disarm would
        # let one truncated packet shut the portal down mid-take, so ignore it
        # and keep whatever we last knew for certain.
        if not len(data):
            return
        armed = data[0] != 0
        if armed != self.armed:
            self.changes_seen += 1
        self.armed = armed

    async def _attempt(self):
        """One scan-and-listen cycle. Raises if the BLE stack is not ready."""
        import asyncio

        from bleak import BleakClient, BleakScanner
        from .stream_client import KEY_STATE_UUID

        device = await BleakScanner.find_device_by_name(self.device_name,
                                                        timeout=10.0)
        if device is None:
            self.error = f"no device named {self.device_name}"
            return
        try:
            async with BleakClient(device) as client:
                # Read before subscribing. The characteristic notifies only on
                # change, so a ring armed before the laptop connected would
                # otherwise stay invisible until the next tap.
                self._on_state(None, await client.read_gatt_char(KEY_STATE_UUID))
                await client.start_notify(KEY_STATE_UUID, self._on_state)
                self.connected, self.error = True, None
                while client.is_connected and not self._stop.is_set():
                    await asyncio.sleep(0.2)
        finally:
            self._mark_disconnected()


class RingSource(BleSource):
    """Live openness from the ring over BLE, on its own thread.

    Owns an asyncio loop in a background thread so the renderer never waits on
    Bluetooth. Openness is a plain float written by that thread and read by the
    render loop; no lock, because a torn read of a float is not possible here
    and a one-frame-stale value is invisible at 56fps.

    Pass a `KeySource` as `key` and every sample is gated on the other ring
    being worn. Left as None the portal is always armed, which is what the
    replay tests and a bare bring-up run want.
    """

    def __init__(self, device_name=None, on_event=None, key=None):
        from .stream_client import DEVICE_NAME
        super().__init__(device_name or DEVICE_NAME)
        self.tracker = GestureTracker()
        self.samples_seen = 0
        self.packets_seen = 0
        self.key = key
        self._on_event = on_event
        self._last_latched = None

    @property
    def armed(self):
        return True if self.key is None else self.key.armed

    @property
    def openness(self):
        return self.tracker.openness

    @property
    def latched(self):
        return self.tracker.latched

    @property
    def status(self):
        # The key half is always shown when there is a key ring. A flat key-ring
        # battery and a broken gesture detector look identical from behind the
        # projector otherwise -- both are just a portal that will not open.
        suffix = "" if self.key is None else f"   {self.key.status}"
        if self.error:
            return f"ring: {self.error}{suffix}"
        if not self.connected:
            return f"looking for {self.device_name}...{suffix}"
        return f"ring connected  {self.packets_seen} packets{suffix}"

    def stop(self):
        super().stop()
        if self.key is not None:
            self.key.stop()

    def _on_notify(self, _sender, data):
        from .decode import decode_packet
        try:
            packet = decode_packet(bytes(data))
        except ValueError:
            return                      # a dropped packet is not worth a stall
        self.packets_seen += 1
        # Sampled once per packet rather than per sample: the key ring's state
        # is written by another thread, and one consistent answer for the whole
        # 10 ms batch beats a gate that could flip halfway through it.
        armed = self.armed
        for sample in packet.samples:
            self.tracker.push(sample[:3], armed=armed)   # gyro deliberately unused
            self.samples_seen += 1
        if self.tracker.latched != self._last_latched:
            self._last_latched = self.tracker.latched
            if self._on_event:
                self._on_event(self.tracker.latched)

    async def _attempt(self):
        """One scan-and-listen cycle. Raises if the BLE stack is not ready."""
        import asyncio

        from bleak import BleakClient, BleakScanner
        from .stream_client import STREAM_UUID

        device = await BleakScanner.find_device_by_name(self.device_name,
                                                        timeout=10.0)
        if device is None:
            self.error = f"no device named {self.device_name}"
            return
        try:
            async with BleakClient(device) as client:
                await client.start_notify(STREAM_UUID, self._on_notify)
                self.connected, self.error = True, None
                while client.is_connected and not self._stop.is_set():
                    await asyncio.sleep(0.2)
        finally:
            self._mark_disconnected()
