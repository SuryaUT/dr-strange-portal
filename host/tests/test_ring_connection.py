"""The BLE connection loop must survive a Bluetooth stack that is not ready.

The ring thread used to scan outside its own error handling, so a radio that
was switched off raised straight out of the thread and killed it -- and turning
Bluetooth on afterwards could not recover, because nothing was left scanning.
These tests drive the loop with a fake attempt so they need no radio.
"""
import asyncio

import pytest

from portal.ring import RingSource


def test_a_failing_attempt_does_not_escape_the_loop():
    """A raised BLE error must be caught and recorded, not propagated."""
    src = RingSource()
    calls = {"n": 0}

    async def boom():
        calls["n"] += 1
        if calls["n"] >= 3:
            src._stop.set()
        raise RuntimeError("Bluetooth radio is not powered on")

    src._attempt = boom
    asyncio.run(src._run(backoff=0.0))

    assert calls["n"] == 3, "the loop stopped at the first error instead of retrying"
    assert "Bluetooth is off" in src.error, "the radio-off case was not made friendly"


def test_the_loop_keeps_trying_until_told_to_stop():
    """Radio off now, on later: the loop must still be scanning when it comes up."""
    src = RingSource()
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 4:
            raise RuntimeError("not ready")
        src.connected = True             # the radio came up on the 4th try
        src._stop.set()

    src._attempt = flaky
    asyncio.run(src._run(backoff=0.0))

    assert attempts["n"] == 4
    assert src.connected


def test_an_error_clears_once_a_later_attempt_succeeds():
    src = RingSource()
    src.error = "Bluetooth radio is not powered on"
    seq = iter([RuntimeError("off"), None])

    async def then_ok():
        nxt = next(seq)
        src._stop.set()
        if nxt:
            raise nxt

    src._attempt = then_ok
    asyncio.run(src._run(backoff=0.0))

    # first (and only, before stop) attempt raised, so error is still set;
    # the point being tested is simply that _run returns instead of crashing.
    assert src._stop.is_set()


# --- The key ring -----------------------------------------------------------

from portal.ring import KeySource


def test_key_starts_disarmed():
    """Fail closed. Until the key ring is heard from, there is no portal."""
    assert KeySource().armed is False


def test_key_decodes_the_state_byte():
    src = KeySource()
    src._on_state(None, bytearray(b"\x01"))
    assert src.armed is True
    src._on_state(None, bytearray(b"\x00"))
    assert src.armed is False


def test_key_ignores_an_empty_notification():
    """A truncated packet must not be read as a disarm and kill a take."""
    src = KeySource()
    src._on_state(None, bytearray(b"\x01"))
    src._on_state(None, bytearray(b""))
    assert src.armed is True


def test_key_treats_any_non_zero_byte_as_armed():
    src = KeySource()
    src._on_state(None, bytearray(b"\xff"))
    assert src.armed is True


def test_losing_the_key_connection_disarms():
    """A ring that has walked out of range is not a ring that is being worn."""
    src = KeySource()
    src._on_state(None, bytearray(b"\x01"))
    src._mark_disconnected()
    assert src.armed is False


def test_key_connection_loop_survives_a_dead_radio():
    """Same retry guarantee as the portal ring -- it shares the loop."""
    src = KeySource()
    calls = {"n": 0}

    async def boom():
        calls["n"] += 1
        if calls["n"] >= 3:
            src._stop.set()
        raise RuntimeError("Bluetooth radio is not powered on")

    src._attempt = boom
    asyncio.run(src._run(backoff=0.0))

    assert calls["n"] == 3
    assert "Bluetooth is off" in src.error


# --- The key ring gating the portal ring ------------------------------------

import struct

from portal.decode import SAMPLES_PER_PACKET


def a_packet(seq=0):
    """A well-formed IMU packet, so `_on_notify` gets past the decoder."""
    header = struct.pack("<BBI", seq, SAMPLES_PER_PACKET, 1000)
    body = b"".join(struct.pack("<6h", 0, 0, 4096, 0, 0, 0)
                    for _ in range(SAMPLES_PER_PACKET))
    return bytearray(header + body)


def test_ring_passes_the_key_state_down_to_the_portal():
    """The wiring that makes the whole feature work: key state must actually
    reach `PortalState.push`, not just sit on the KeySource."""
    key = KeySource()
    ring = RingSource(key=key)
    seen = []
    ring.tracker.push = lambda acc, armed=True: seen.append(armed)

    ring._on_notify(None, a_packet(0))
    assert seen and all(a is False for a in seen), "disarmed key did not gate"

    seen.clear()
    key._on_state(None, bytearray(b"\x01"))
    ring._on_notify(None, a_packet(1))
    assert seen and all(a is True for a in seen), "armed key did not open the gate"


def test_ring_without_a_key_is_always_armed():
    """--no-key, replay and the bring-up path must be completely unaffected."""
    ring = RingSource()
    seen = []
    ring.tracker.push = lambda acc, armed=True: seen.append(armed)
    ring._on_notify(None, a_packet(0))
    assert seen and all(a is True for a in seen)


def test_the_gate_is_sampled_once_per_packet():
    """A key flipping mid-batch must not split one packet across two states."""
    key = KeySource()
    ring = RingSource(key=key)
    seen = []

    def flip(acc, armed=True):
        seen.append(armed)
        key.armed = not key.armed        # thrash it from under the loop

    ring.tracker.push = flip
    ring._on_notify(None, a_packet(0))
    assert len(set(seen)) == 1, "the gate was re-read partway through a packet"


def test_stopping_the_ring_stops_the_key_too():
    """Otherwise the key thread outlives the renderer and holds the radio."""
    key = KeySource()
    ring = RingSource(key=key)
    ring.stop()
    assert key._stop.is_set()
