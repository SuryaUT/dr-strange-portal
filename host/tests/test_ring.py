"""Tests for the link between a gesture and the portal's openness.

These run the real detector and the real state machine over the real captures,
so they pin the whole chain the renderer depends on: counter-clockwise opens,
clockwise closes, and a hand that stops changes nothing.
"""
import numpy as np
import pytest

from portal.ring import GestureTracker, ReplaySource


def _capture(name):
    from pathlib import Path
    from portal.plot import load_capture
    path = Path(__file__).resolve().parent.parent / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    t, acc, _gyr = load_capture(path)
    return t, acc


def _drive(tracker, acc):
    openness = 0.0
    for sample in acc:
        openness = tracker.push(sample)
    return openness


def test_counter_clockwise_opens_the_portal():
    """As Strange does it: counter-clockwise draws the portal open."""
    _t, acc = _capture("ccw_short.csv")
    tracker = GestureTracker()

    assert _drive(tracker, acc) == pytest.approx(1.0)


def test_clockwise_alone_never_opens_the_portal():
    _t, acc = _capture("cw_short.csv")
    tracker = GestureTracker()

    assert _drive(tracker, acc) < 0.4


def test_clockwise_closes_a_portal_that_is_open():
    _t, ccw = _capture("ccw_short.csv")
    _t2, cw = _capture("cw_short.csv")
    tracker = GestureTracker()
    _drive(tracker, ccw)

    assert _drive(tracker, cw) == pytest.approx(0.0)


def test_a_hand_that_stops_leaves_the_portal_where_it_is():
    """The portal must hold its state with no input at all -- that is what
    lets you open one, drop your hand, and walk through it."""
    _t, acc = _capture("ccw_short.csv")
    tracker = GestureTracker()
    _drive(tracker, acc)

    still = np.tile(np.array([0.0, 0.0, 1.0]), (2000, 1))   # 20s of gravity
    assert _drive(tracker, still) == pytest.approx(1.0)


def test_walking_does_not_open_the_portal():
    _t, acc = _capture("walk0.csv")
    tracker = GestureTracker()

    assert _drive(tracker, acc) < 0.4


def test_replay_source_reports_openness_without_any_hardware():
    """The renderer must be drivable from a capture, so the whole chain can be
    exercised with no ring powered on."""
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "ccw_short.csv"
    if not path.exists():
        pytest.skip("ccw_short.csv not present")

    source = ReplaySource(path, speed=0.0)     # 0 = as fast as possible
    source.run_to_end()

    assert source.openness == pytest.approx(1.0)
    assert source.samples_seen > 100
