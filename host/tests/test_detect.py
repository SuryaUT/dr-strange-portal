"""Tests for the gesture detector.

The synthetic tests pin down behaviour that must hold for *any* sane choice of
threshold: a perfect circle is detected, a pure back-and-forth shake is not,
reversing the circle reverses the reported direction, and openness never runs
backwards. The golden tests at the bottom then pin the actual thresholds
against real captures.
"""
import numpy as np
import pytest

from portal.detect import Detector, DetectorConfig, run_capture

FS = 100.0
G = 9.80665


def synth(duration_s, f0=0.98, radius_m=0.19, sense=1.0, ellipse=1.0,
          e1=(1.0, 0.0, 0.0), e2=(0.0, 1.0, 0.0), gravity=(0.0, 0.0, 1.0),
          fs=FS, noise_g=0.0, seed=0):
    """Accelerometer trace for a sensor carried around a circle.

    The sensor's orientation is fixed (the "cart on a Ferris wheel" case), so
    the centripetal vector sweeps a full turn in the sensor frame. `ellipse`
    squashes the minor axis: 1.0 is a circle, 0.0 is a straight-line shake.
    """
    t = np.arange(0.0, duration_s, 1.0 / fs)
    w = 2.0 * np.pi * f0
    amp_g = (w ** 2) * radius_m / G
    u = np.asarray(e1, float)
    v = np.asarray(e2, float)
    acc = (amp_g * np.cos(w * t))[:, None] * u \
        + (ellipse * amp_g * np.sin(sense * w * t))[:, None] * v
    acc = acc + np.asarray(gravity, float)
    if noise_g:
        acc = acc + np.random.default_rng(seed).normal(0.0, noise_g, acc.shape)
    return t, acc


def test_perfect_circle_opens_the_portal():
    t, acc = synth(6.0)
    res = run_capture(t, acc, DetectorConfig())
    assert res.openness.max() == pytest.approx(1.0)
    assert res.opened_at is not None


def test_perfect_circle_reports_high_circularity():
    t, acc = synth(6.0)
    res = run_capture(t, acc, DetectorConfig())
    settled = res.circularity[int(2.0 * FS):]
    assert np.median(settled) > 0.9


def test_pure_linear_shake_is_rejected():
    """A back-and-forth shake is two equal counter-rotating components, so it
    must never accumulate. This is the property the whole design rests on."""
    t, acc = synth(12.0, ellipse=0.0)
    res = run_capture(t, acc, DetectorConfig())
    assert res.opened_at is None
    assert res.openness.max() < 0.25


def test_shake_circularity_is_near_zero():
    t, acc = synth(12.0, ellipse=0.0)
    res = run_capture(t, acc, DetectorConfig())
    settled = res.circularity[int(2.0 * FS):]
    assert np.median(settled) < 0.2


def test_direction_reverses_with_the_circle():
    t_a, acc_a = synth(6.0, sense=+1.0)
    t_b, acc_b = synth(6.0, sense=-1.0)
    a = run_capture(t_a, acc_a, DetectorConfig())
    b = run_capture(t_b, acc_b, DetectorConfig())
    assert a.direction[-1] != 0
    assert a.direction[-1] == -b.direction[-1]


def test_openness_never_decreases_while_gated():
    """The arc must not un-draw. Backward phase steps are discarded, so
    openness is monotone for as long as the gate holds."""
    t, acc = synth(8.0, noise_g=0.03)
    res = run_capture(t, acc, DetectorConfig())
    held = res.gate_open[1:] & res.gate_open[:-1]
    steps = np.diff(res.openness)[held]
    assert (steps >= -1e-12).all()


def test_gravity_offset_does_not_change_the_result():
    """Gravity is removed as DC, so mounting the ring at a different angle
    must not alter detection."""
    t, flat = synth(6.0, gravity=(0.0, 0.0, 1.0))
    _, tilted = synth(6.0, gravity=(0.6, -0.5, 0.62))
    a = run_capture(t, flat, DetectorConfig())
    b = run_capture(t, tilted, DetectorConfig())
    assert a.opened_at is not None and b.opened_at is not None
    assert a.opened_at == pytest.approx(b.opened_at, abs=0.3)


def test_detector_is_causal_and_streaming():
    """Feeding samples one at a time must equal the batch result exactly --
    this is what makes the port to the C3 a straight translation."""
    t, acc = synth(5.0)
    batch = run_capture(t, acc, DetectorConfig())
    det = Detector(FS, DetectorConfig())
    stream = np.array([det.push(a).openness for a in acc])
    assert np.allclose(stream, batch.openness)


def test_slow_and_fast_gestures_both_open():
    """Amplitude scales with omega^2, so the gate must normalise by frequency
    rather than testing raw acceleration."""
    for f0 in (0.6, 1.6):
        t, acc = synth(10.0, f0=f0)
        res = run_capture(t, acc, DetectorConfig())
        assert res.opened_at is not None, f"failed to open at {f0} Hz"


# --------------------------------------------------------------------------
# Golden tests against real captures. These are the ones that matter.
# --------------------------------------------------------------------------

CAPTURES = pytest.importorskip("pathlib") and None


def _load(name):
    from pathlib import Path
    from portal.plot import load_capture
    path = Path(__file__).resolve().parent.parent / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    t, acc, _gyr = load_capture(path)
    return t, acc


@pytest.mark.parametrize("name", ["cw_0.csv", "cw_1.csv"])
def test_real_gesture_opens_the_portal(name):
    t, acc = _load(name)
    res = run_capture(t, acc, DetectorConfig())
    assert res.opened_at is not None


def test_walking_never_opens_the_portal():
    """46 s of walking around an apartment accumulated 18 net turns on a naive
    accumulator. The shape gate must reject all of it."""
    t, acc = _load("walk0.csv")
    res = run_capture(t, acc, DetectorConfig())
    assert res.opened_at is None, (
        f"false portal at t={res.opened_at:.1f}s; "
        f"peak openness {res.openness.max():.2f}"
    )


def _count_opens(openness, rearm=0.5):
    """Portals fired. Re-arms only after openness falls back below `rearm`, so
    holding a finished portal open does not count repeatedly."""
    count, armed = 0, True
    for o in openness:
        if armed and o >= 1.0:
            count += 1
            armed = False
        elif not armed and o < rearm:
            armed = True
    return count


@pytest.mark.parametrize("name,reps", [("cw_short.csv", 7), ("ccw_short.csv", 6)])
def test_every_repetition_is_detected(name, reps):
    """Real gestures from a standing start, one portal per repetition -- no
    misses and no double-fires. This is the closest thing to the demo itself."""
    t, acc = _load(name)
    res = run_capture(t, acc, DetectorConfig())
    assert _count_opens(res.openness) == reps


@pytest.mark.parametrize("name,reps", [("cw_raise_then_circle.csv", 6),
                                       ("ccw_raise_then_circle.csv", 6)])
def test_raising_the_arm_first_still_works(name, reps):
    """Raising the arm changes the sensor's orientation, so the gravity
    estimator has to re-converge right before the gesture. It was not obvious
    this would survive; it does."""
    t, acc = _load(name)
    res = run_capture(t, acc, DetectorConfig())
    assert _count_opens(res.openness) >= reps


@pytest.mark.parametrize("name,sense", [("cw_short.csv", -1), ("ccw_short.csv", +1)])
def test_direction_is_correct_on_real_captures(name, sense):
    """Direction was only ever verified synthetically before these captures.

    Zeros are excluded: direction 0 is the honest "stability is too low to
    say", not a wrong answer. What must never happen is a confident report of
    the wrong sense.
    """
    t, acc = _load(name)
    res = run_capture(t, acc, DetectorConfig())
    fired = res.direction[res.openness >= 1.0]
    confident = fired[fired != 0]
    assert confident.size > 100, "almost never confident about direction"
    assert (confident == sense).all(), "reported the wrong rotation sense"


def test_near_miss_arm_motion_never_opens():
    """75 s of talking with your hands, reaching, waving, adjusting the ring.
    These happen while standing at the mark, so a false portal here ruins a
    take -- a stricter requirement than walking."""
    t, acc = _load("nearmiss.csv")
    res = run_capture(t, acc, DetectorConfig())
    assert _count_opens(res.openness) == 0
    assert res.openness.max() < 0.5


def test_walking_keeps_a_wide_margin():
    """Not opening is not enough -- walking must stay far from the threshold,
    or the arc will visibly flicker onto the wall while you cross the room."""
    t, acc = _load("walk0.csv")
    res = run_capture(t, acc, DetectorConfig())
    assert res.openness.max() < 0.35
    assert res.gate_open.mean() < 0.05


def test_gesture_from_a_standing_start_opens_while_still_circling():
    """The captures are 40 s continuous spins, but the real gesture starts from
    rest. There is an unavoidable warm-up: circularity cannot be measured
    without observing a full period, and the plane normal has to average up
    from zero. That costs roughly the first turn and a half, so the portal
    completes on about the third turn -- it must not need more than four.
    """
    turns = 4.0
    duration = turns / 0.98
    t_g, acc_g = synth(duration, noise_g=0.01)
    still = np.tile([0.0, 0.0, 1.0], (150, 1)) \
        + np.random.default_rng(1).normal(0.0, 0.01, (150, 3))
    acc = np.vstack([still, acc_g, still])
    t = np.arange(len(acc)) / FS
    res = run_capture(t, acc, DetectorConfig())
    assert res.opened_at is not None, "four turns must open the portal"
    assert res.opened_at < 1.5 + duration, "must open while the hand is still circling"
    # The fast turning-consistency path exists to keep this near two turns. If
    # it regresses, the slow lock-in alone needs ~3.7 and the portal stops
    # feeling connected to the hand.
    turns_in = (res.opened_at - 1.5) * 0.98
    assert turns_in < 2.5, f"took {turns_in:.1f} turns; fast path has regressed"
