"""Tests for the latching portal state machine.

The unit tests drive PortalState with hand-built detector frames, so they
exercise the state logic without the detector's behaviour mixed in. The
integration tests at the bottom run the real thing over real captures.
"""
import numpy as np
import pytest

from portal.detect import Frame
from portal.simulate import (CLOSED, OPEN, OPENING_SENSE, PortalConfig,
                             PortalState, simulate, transitions)

FS = 100.0
CLOSING_SENSE = -OPENING_SENSE


def moving(arc, sense):
    """A frame from a confident, gated gesture at the given rotation sense."""
    return Frame(openness=arc, direction=sense, circularity=0.8, stability=0.99,
                 radius_m=0.19, freq_hz=0.9, gate_open=True)


def still(arc):
    """A frame with the gate shut -- the hand has stopped."""
    return Frame(openness=arc, direction=0, circularity=0.1, stability=0.2,
                 radius_m=0.0, freq_hz=0.9, gate_open=False)


def drive(sm, arc_to, sense, samples=100, start=0.0):
    """Feed a smooth rise in the detector's arc from `start` to `arc_to`."""
    out = None
    for a in np.linspace(start, arc_to, samples):
        out = sm.push(moving(float(a), sense))
    return out


def coast(sm, arc, samples=300):
    """Hand stops dead; the detector's arc stops growing."""
    out = None
    for _ in range(samples):
        out = sm.push(still(arc))
    return out


def test_starts_closed():
    sm = PortalState(FS)
    assert sm.latched == CLOSED
    assert sm.openness == 0.0


def test_full_counter_clockwise_gesture_opens():
    sm = PortalState(FS)
    drive(sm, 1.0, OPENING_SENSE)
    assert sm.latched == OPEN
    assert sm.openness == pytest.approx(1.0)


def test_commit_finishes_the_portal_after_the_hand_stops():
    """Past the commit point the portal completes on its own. Without this you
    have to keep circling to the very end, and easing off springs it back."""
    sm = PortalState(FS)
    cfg = sm.cfg
    drive(sm, cfg.commit_at + 0.03, OPENING_SENSE)
    assert sm.latched == CLOSED, "should not be open yet"
    coast(sm, cfg.commit_at + 0.03)
    assert sm.latched == OPEN, "commit did not carry it to completion"


def test_stopping_before_the_commit_point_springs_back():
    """The other half of the bargain: a stray part-circle must not open a
    portal, or walking past a doorway becomes a light show."""
    sm = PortalState(FS)
    drive(sm, sm.cfg.commit_at - 0.10, OPENING_SENSE)
    coast(sm, sm.cfg.commit_at - 0.10)
    assert sm.latched == CLOSED
    assert sm.openness == pytest.approx(0.0)


def test_open_portal_survives_the_hand_dropping():
    """A finished portal is latched: it stays open indefinitely with no input."""
    sm = PortalState(FS)
    drive(sm, 1.0, OPENING_SENSE)
    coast(sm, 1.0, samples=2000)      # 20 s of nothing
    assert sm.latched == OPEN
    assert sm.openness == pytest.approx(1.0)


def test_clockwise_closes_an_open_portal():
    sm = PortalState(FS)
    drive(sm, 1.0, OPENING_SENSE)
    sm._prev_arc = 0.0                # detector re-arms between gestures
    drive(sm, 1.0, CLOSING_SENSE)
    assert sm.latched == CLOSED
    assert sm.openness == pytest.approx(0.0)


def test_closing_also_commits():
    sm = PortalState(FS)
    drive(sm, 1.0, OPENING_SENSE)
    sm._prev_arc = 0.0
    drive(sm, sm.cfg.commit_at + 0.03, CLOSING_SENSE)
    coast(sm, sm.cfg.commit_at + 0.03)
    assert sm.latched == CLOSED, "closing must commit the same way opening does"


def test_clockwise_at_a_closed_portal_does_nothing():
    """You cannot close what is already shut, however long you circle."""
    sm = PortalState(FS)
    drive(sm, 1.0, CLOSING_SENSE, samples=500)
    assert sm.latched == CLOSED
    assert sm.openness == pytest.approx(0.0)


def test_counter_clockwise_at_an_open_portal_does_nothing():
    sm = PortalState(FS)
    drive(sm, 1.0, OPENING_SENSE)
    sm._prev_arc = 0.0
    drive(sm, 1.0, OPENING_SENSE, samples=500)
    assert sm.latched == OPEN
    assert sm.openness == pytest.approx(1.0)


def test_commit_can_be_disabled():
    """commit_at = 1.0 restores pure follow-the-hand behaviour."""
    sm = PortalState(FS, PortalConfig(commit_at=1.0))
    drive(sm, 0.6, OPENING_SENSE)
    coast(sm, 0.6)
    assert sm.latched == CLOSED
    assert sm.openness == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Integration against real captures.
# --------------------------------------------------------------------------

def _load(name):
    from pathlib import Path
    from portal.plot import load_capture
    path = Path(__file__).resolve().parent.parent / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    t, acc, _gyr = load_capture(path)
    return t, acc


def test_real_counter_clockwise_opens_once_and_stays_open():
    """ccw_short is repeated counter-clockwise circles, as Strange opens a
    portal. The first opens it; the rest must do nothing, it is already open."""
    t, acc = _load("ccw_short.csv")
    states, _open, _res, _fs = simulate(t, acc)
    ev = transitions(states)
    assert len(ev) == 1
    assert ev[0][2] == OPEN
    assert states[-1] == OPEN


def test_real_clockwise_alone_never_opens():
    """Clockwise is the closing gesture; it cannot open a shut portal."""
    t, acc = _load("cw_short.csv")
    states, opens, _res, _fs = simulate(t, acc)
    assert transitions(states) == []
    assert opens.max() < 0.4


@pytest.mark.parametrize("name", ["walk0.csv", "nearmiss.csv"])
def test_negatives_never_change_portal_state(name):
    t, acc = _load(name)
    states, opens, _res, _fs = simulate(t, acc)
    assert transitions(states) == []
    assert opens.max() < PortalConfig().commit_at, (
        f"{name} reached {opens.max():.2f} openness, against a commit point of "
        f"{PortalConfig().commit_at}"
    )


def test_real_round_trip_opens_then_closes():
    """Counter-clockwise then clockwise, on real data end to end."""
    ta, aa = _load("ccw_short.csv")
    tb, ab = _load("cw_short.csv")
    t = np.concatenate([ta, tb + ta[-1] + 0.01])
    acc = np.vstack([aa, ab])
    states, _open, _res, _fs = simulate(t, acc)
    ev = [to for _i, _f, to in transitions(states)]
    assert ev == [OPEN, CLOSED]


# --- The key ring gate ------------------------------------------------------
#
# A second ring worn on the other hand arms the portal. `PortalState.push` takes
# `armed`, and a disarmed portal must ignore the hand entirely -- the gesture is
# still detected and still reported, it just does not move the portal.

def test_disarmed_gesture_never_opens():
    """The whole point of the key ring: no key, no portal, however good the circle."""
    sm = PortalState(FS)
    for a in np.linspace(0.0, 1.0, 100):
        sm.push(moving(float(a), OPENING_SENSE), armed=False)
    assert sm.latched == CLOSED
    assert sm.openness == pytest.approx(0.0)


def test_disarmed_gesture_does_not_even_start_the_arc():
    """Not just un-latched -- the arc must not creep up and draw on the wall."""
    sm = PortalState(FS)
    for a in np.linspace(0.0, 0.35, 40):
        sm.push(moving(float(a), OPENING_SENSE), armed=False)
    assert sm.openness == pytest.approx(0.0)


def test_arming_after_a_disarmed_gesture_does_not_snap_open():
    """The trap: the detector's accumulator keeps climbing while disarmed.

    If the gate only skips the update without tracking that climb, the first
    armed sample sees the entire disarmed gesture as one delta and the portal
    flicks open instantly, with no arc drawn. It must resume from zero progress.
    """
    sm = PortalState(FS)
    for a in np.linspace(0.0, 0.9, 90):          # a full circle, unarmed
        sm.push(moving(float(a), OPENING_SENSE), armed=False)
    assert sm.openness == pytest.approx(0.0)

    _state, openness = sm.push(moving(0.9, OPENING_SENSE), armed=True)
    assert openness < 0.05, "the disarmed arc was banked and released in one sample"
    assert sm.latched == CLOSED


def test_arming_then_gesturing_opens_normally():
    """Arming must leave the ordinary path completely untouched."""
    sm = PortalState(FS)
    coast(sm, 0.0, samples=50)
    for a in np.linspace(0.0, 1.0, 100):
        sm.push(moving(float(a), OPENING_SENSE), armed=True)
    assert sm.latched == OPEN


def test_disarming_holds_an_open_portal_rather_than_slamming_it():
    """Losing the key mid-scene should not cut the portal out of the shot.

    Disarming stops the portal listening to the hand; it does not close it. A
    dropped BLE packet or a brushed pad would otherwise kill a take.
    """
    sm = PortalState(FS)
    drive(sm, 1.0, OPENING_SENSE)
    assert sm.latched == OPEN

    for a in np.linspace(1.0, 2.0, 100):
        sm.push(moving(float(a), CLOSING_SENSE), armed=False)
    assert sm.latched == OPEN
    assert sm.openness == pytest.approx(1.0)


def test_disarming_mid_commit_abandons_the_commit():
    """Past the commit point the portal finishes on its own -- unless the key
    goes away. Otherwise pulling the ring off cannot stop a portal opening."""
    sm = PortalState(FS)
    drive(sm, 0.5, OPENING_SENSE, samples=50)     # past commit_at = 0.40
    assert sm.openness > 0.4

    for _ in range(400):
        sm.push(still(0.5), armed=False)
    assert sm.latched == CLOSED
    assert sm.openness == pytest.approx(0.0)


def test_armed_defaults_to_true_so_existing_callers_are_unaffected():
    sm = PortalState(FS)
    drive(sm, 1.0, OPENING_SENSE)
    assert sm.latched == OPEN
