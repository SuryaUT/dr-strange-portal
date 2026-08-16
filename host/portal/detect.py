"""Turn a stream of accelerometer samples into a portal `openness` in [0, 1].

The detector is an *accumulator*, not a classifier: it reports progress on every
sample so the portal can trace along with the hand, rather than announcing a
verdict once the gesture is over.

Only the accelerometer is used. The original design expected the wrist to stay
rigid, making a large gyro reading positive evidence *against* the gesture --
but the Phase 1 captures show 108-118 deg/s of wrist rock during a perfectly
good gesture, so that veto would have rejected the real thing. The gyro is not
read here.

How it works
------------
Gravity is the slow part of the accelerometer signal and is removed as DC. What
remains during a circle is centripetal acceleration, which sweeps a full turn in
the sensor frame -- a rotating phasor.

Rather than choosing a plane first (which needs a non-causal SVD, or an
enrolment step), all three axes are demodulated at `f0` and averaged. That
yields one complex amplitude vector `A = P + iQ`, and the motion at `f0` is
exactly the ellipse

    m(t) = P*cos(wt) - Q*sin(wt)

from which everything follows algebraically. With `S = |P|^2 + |Q|^2` and
`D = |P x Q|`, the squared semi-axes are the roots of `u^2 - S*u + D^2 = 0`, so:

    circularity b/a   how circle-like the motion is  (1 = circle, 0 = a line)
    P x Q             the plane normal; its direction is the rotation sense
    a                 the major semi-axis, giving radius via a*g/w^2

A cross product and one running sum per axis. No matrices, and it ports to the
C3 almost verbatim.

Why the averaging is a boxcar and not a one-pole
------------------------------------------------
Demodulating a *real* signal leaves an image at -2*f0. A one-pole low-pass does
not reject it well -- one octave is simply too close -- and the residual is
counter-rotating, so it inflates the minor axis and drags circularity down. At
tau = 0.35 s the image survives at 0.226, which caps the reported circularity of
a *perfect* circle at (1-0.226)/(1+0.226) = 0.63.

Averaging over exactly one carrier period instead puts an exact null on the
image (a boxcar of N samples nulls at fs/N, 2fs/N, ...), so a perfect circle
reads as 1.0. The cost is a group delay of half a period, which only affects the
gate -- phase is taken from the unfiltered signal and carries no lag.

Why circularity is the discriminator
------------------------------------
A pure back-and-forth shake is two *equal* counter-rotating components
(`cos(wt) = (e^{iwt} + e^{-iwt})/2`), so it produces no net rotation and
`b/a = 0`. An ellipse is unequal and does accumulate.

Frequency and direction do *not* separate gesture from noise -- walking around
an apartment produced 0.75 Hz of rotation in the same sense as a 0.98 Hz
gesture, and a naive accumulator fired every ~2.5 seconds. Shape is what
separates them: the gesture is 98% planar, walking is 77%.
"""
from dataclasses import dataclass, field

import numpy as np

G_MS2 = 9.80665


@dataclass(frozen=True)
class DetectorConfig:
    """Tunables. Defaults are fitted to the Phase 1 captures; see tests."""

    # Starting guess for the demodulation frequency, at the measured gesture
    # rate; it is tracked from there. `lockin_periods` sets the averaging
    # window as a multiple of the tracked period; 1.0 puts an exact null on the
    # -2f demodulation image. The frequency is clamped to the range of gesture
    # speeds a person can plausibly produce.
    f0_hz: float = 0.98
    lockin_periods: float = 1.0
    min_freq_hz: float = 0.35
    max_freq_hz: float = 2.5

    # The frequency tracker only engages when there is a real oscillation to
    # lock onto. Both floors sit well below the gate proper -- they exist to
    # stop the loop chasing noise, not to judge the gesture.
    track_amp_floor_g: float = 0.05
    track_min_circularity: float = 0.30

    # Gravity must be estimated slowly enough not to eat the gesture itself.
    gravity_tau_s: float = 1.5

    # Plane-normal averaging. A consistent circle holds its normal still; 3D
    # flailing does not. This replaces the offline planarity measure. The time
    # constant is short because stability has to *build up* -- too slow and a
    # brief two-turn gesture ends before the gate ever opens.
    normal_tau_s: float = 0.25
    freq_tau_s: float = 0.5

    # Gate thresholds, fitted to the Phase 1 captures. Measured separation:
    #
    # Refitted against real short gestures, which are markedly less circular
    # than the 40 s continuous spins the first cut was calibrated on: three
    # circles from rest never settle into a rhythm, so the first accelerates,
    # the last decelerates, and there is barely a steady middle.
    #
    # The comparison must be made over the window that actually matters. A
    # portal needs roughly a full turn of gating, and circularity sustained for
    # 1 s separates cleanly where a 0.5 s snapshot does not:
    #
    #   sustained circularity   0.5 s   1.0 s
    #   gestures (short/slow)   0.70+   0.65-0.72
    #   continuous spin         0.93    0.89
    #   walking                 0.50    0.41
    #   near-miss arm motion    0.60    0.36     <- brief accident, not sustained
    #
    # Hence 0.45. An earlier cut used 0.55, reasoning that walking's 1 s
    # figure of 0.41 deserved wide clearance -- but circularity margin is the
    # wrong thing to protect. What matters is how close a negative gets to
    # actually firing, and peak openness barely moves across this range:
    #
    #   min_circularity   0.45   0.50   0.55
    #   detections          30     28     27
    #   walking peak      0.17   0.17   0.15
    #   near-miss peak    0.25   0.24   0.23
    #
    # 0.45 buys three more real detections for 0.02 of openness on the
    # negatives, which are still ~4x away from opening a portal. Stability and
    # the full-turn accumulation requirement carry the rejection, not this.
    min_circularity: float = 0.45
    min_normal_stability: float = 0.90
    min_radius_m: float = 0.09
    max_radius_m: float = 0.60

    # Fast path: turning-consistency over a fraction of a turn. This is what
    # lets the arc start tracing almost immediately instead of waiting a full
    # period for the lock-in. Measured coherence at 1/8 turn: gesture 0.83-0.85,
    # walking 0.52. Less separation than the full-period lock-in (0.45), which
    # is why it opens the gate but does not hold the veto.
    fast_window_periods: float = 0.125
    fast_min_coherence: float = 0.70
    fast_hold_coherence: float = 0.55
    fast_radius_scale: float = 2.0

    # Hysteresis: once the gate is open it is held on looser thresholds. A
    # gesture in progress is prior evidence that the next sample is part of the
    # same gesture, so brief dropouts should not cost accumulated progress --
    # every flicker decays the accumulator and pushes the portal a fraction of
    # a turn further away. Entry stays strict, which is what keeps walking out.
    hold_circularity: float = 0.34
    hold_normal_stability: float = 0.78
    hold_radius_scale: float = 1.6

    # Phase advance below this fraction of the nominal per-sample step is
    # treated as noise and discarded, so a jittering signal cannot ratchet
    # openness upward.
    min_rate_frac: float = 0.08

    # When the gate closes, a partial arc fades rather than snapping to zero.
    release_tau_s: float = 0.4


@dataclass
class Frame:
    """Everything the detector knows at one sample."""

    openness: float = 0.0
    direction: int = 0
    circularity: float = 0.0
    stability: float = 0.0
    radius_m: float = 0.0
    freq_hz: float = 0.0
    gate_open: bool = False


@dataclass
class Result:
    """Per-sample arrays for a whole capture, plus the one event that matters."""

    t: np.ndarray
    openness: np.ndarray
    direction: np.ndarray
    circularity: np.ndarray
    stability: np.ndarray
    radius_m: np.ndarray
    freq_hz: np.ndarray
    gate_open: np.ndarray
    opened_at: float | None = None
    frames: list = field(default_factory=list)


def _alpha(tau_s: float, fs: float) -> float:
    """Per-sample coefficient of a one-pole low-pass with time constant tau."""
    return 1.0 - np.exp(-1.0 / (tau_s * fs))


def _wrap(x: float) -> float:
    """Fold an angle difference into (-pi, pi]."""
    return (x + np.pi) % (2.0 * np.pi) - np.pi



class Detector:
    """Streaming detector. One `push` per accelerometer sample, in g."""

    def __init__(self, fs: float, cfg: DetectorConfig | None = None):
        self.fs = float(fs)
        self.cfg = cfg or DetectorConfig()
        c = self.cfg

        self._a_grav = _alpha(c.gravity_tau_s, fs)
        self._a_norm = _alpha(c.normal_tau_s, fs)
        self._a_freq = _alpha(c.freq_tau_s, fs)
        self._a_rel = _alpha(c.release_tau_s, fs)

        # History of dynamic acceleration, long enough to hold one period of
        # the slowest gesture we accept. The averaging window is re-sized every
        # sample to one period of the *tracked* frequency, which keeps the null
        # on the demodulation image at any gesture speed. On the C3 this is a
        # fixed ~200 x 3 float buffer (2.4 kB) and a dot product per sample.
        self._nmax = max(4, int(np.ceil(c.lockin_periods * fs / c.min_freq_hz)))
        self._hist = np.zeros((self._nmax, 3))
        self._filled = 0
        self._head = 0

        self._n = 0
        self._grav: np.ndarray | None = None
        self._normal = np.zeros(3)                # EMA of the unit normal
        self._phi_prev: float | None = None
        self._freq = c.f0_hz
        self._accum = 0.0                         # accumulated phase, radians

        self._opened = False
        self._gated = False
        self._e1 = np.array([1.0, 0.0, 0.0])

        self._dyn_prev = np.zeros(3)
        self._cr_vec = np.zeros(3)
        self._cr_mag = 0.0
        self._amp2 = 0.0
        self._fast_gated = False

    # -- the operator ------------------------------------------------------
    def push(self, acc_g) -> Frame:
        c = self.cfg
        a = np.asarray(acc_g, dtype=float)

        # 1. Gravity as DC.
        if self._grav is None:
            self._grav = a.copy()
        else:
            self._grav += self._a_grav * (a - self._grav)
        dyn = a - self._grav

        # 1b. The fast path. `a x adot` is constant and non-zero for a rotating
        #     vector and exactly zero for a straight-line shake, so it senses
        #     turning immediately. Instantaneously it discriminates nothing --
        #     differentiation amplifies noise, which makes a and adot
        #     non-parallel, so everything reads round (gesture 0.85 vs walking
        #     0.80). What separates them is whether the turning is *consistent*:
        #     averaging the cross product as a vector cancels random turning and
        #     keeps steady turning. Over just an eighth of a turn that already
        #     gives gesture 0.84 vs walking 0.52.
        ddyn = (dyn - self._dyn_prev) * self.fs
        self._dyn_prev = dyn.copy()
        cr = np.cross(dyn, ddyn)

        tau_fast = c.fast_window_periods / max(self._freq, c.min_freq_hz)
        af = _alpha(tau_fast, self.fs)
        self._cr_vec += af * (cr - self._cr_vec)
        self._cr_mag += af * (float(np.linalg.norm(cr)) - self._cr_mag)
        self._amp2 += af * (float(dyn @ dyn) - self._amp2)

        coherent = float(np.linalg.norm(self._cr_vec))
        coherence = coherent / self._cr_mag if self._cr_mag > 1e-12 else 0.0

        # For a circle |a x adot| / |a|^2 is exactly omega, so the fast path
        # gets its own frequency and radius without waiting for the lock-in.
        w_fast = coherent / self._amp2 if self._amp2 > 1e-12 else 0.0
        w_fast = float(np.clip(w_fast, 2.0 * np.pi * c.min_freq_hz,
                               2.0 * np.pi * c.max_freq_hz))
        radius_fast = np.sqrt(max(self._amp2, 0.0)) * G_MS2 / (w_fast * w_fast)

        thr = c.fast_hold_coherence if self._fast_gated else c.fast_min_coherence
        fast_ok = (coherence >= thr
                   and c.min_radius_m / c.fast_radius_scale
                   <= radius_fast <= c.max_radius_m * c.fast_radius_scale)
        self._fast_gated = fast_ok

        # 2. Demodulate all three axes at the tracked frequency and average over
        #    exactly one of its periods. Sizing the window to the frequency is
        #    what keeps the -2f image on a null when the gesture is faster or
        #    slower than nominal; a window fixed at f0 caps a perfect circle's
        #    reported circularity at 0.61 by 0.6 Hz.
        self._hist[self._head] = dyn
        self._filled = min(self._filled + 1, self._nmax)
        self._n += 1

        n_win = int(round(c.lockin_periods * self.fs / self._freq))
        n_win = max(4, min(n_win, self._filled, self._nmax))
        k = np.arange(n_win)
        idx = (self._head - k) % self._nmax
        carrier = np.exp(2j * np.pi * self._freq * k / self.fs)
        lock = (self._hist[idx] * carrier[:, None]).sum(axis=0) / n_win
        self._head = (self._head + 1) % self._nmax

        p = 2.0 * lock.real
        q = 2.0 * lock.imag

        # 3. Ellipse geometry. Semi-axes are the roots of u^2 - S*u + D^2 = 0.
        s = float(p @ p + q @ q)
        # Q x P, not P x Q: for motion c*(cos(wt)*e1 + sin(wt)*e2) the algebra
        # gives P = c*e1 and Q = -c*e2, so P x Q comes out *anti*-aligned with
        # the rotation normal. Taking Q x P instead makes (e1, e2, n) right
        # handed with the actual motion, so phase always advances positively
        # and the accumulator needs no direction latch to guess at.
        cross = np.cross(q, p)
        d = float(np.linalg.norm(cross))
        root = np.sqrt(max(s * s - 4.0 * d * d, 0.0))
        a_major = np.sqrt(max(0.5 * (s + root), 0.0))
        b_minor = np.sqrt(max(0.5 * (s - root), 0.0))
        circ = float(b_minor / a_major) if a_major > 1e-9 else 0.0

        # 4. Plane stability. Averaging unit normals collapses toward zero if
        #    the plane wanders or the rotation sense keeps flipping.
        if d > 1e-9:
            self._normal += self._a_norm * (cross / d - self._normal)
        else:
            self._normal -= self._a_norm * self._normal
        stability = float(np.linalg.norm(self._normal))

        # 5. Phase, from the projection of the raw dynamic signal onto the
        #    gesture plane. Taken from `dyn` rather than the averaged amplitude
        #    so it carries no filter lag -- the arc must track the hand.
        #
        #    The in-plane basis is built from the *normal*, not from P and Q.
        #    P and Q rotate at (f - f0) in the demodulated frame, so a basis
        #    built on them co-rotates with the frequency error and pins the
        #    measured rate to f0 no matter how fast the hand actually moves.
        #    The normal is stationary, so a basis anchored to it is too.
        phi = self._phi_prev if self._phi_prev is not None else 0.0
        if stability > 1e-3:
            nhat = self._normal / stability
            # Carry the previous e1 forward and re-orthogonalise it against the
            # new normal, rather than re-deriving it from scratch each sample.
            # Picking e1 from the least-aligned sensor axis makes it jump
            # whenever two components of n are nearly equal, and a jumping basis
            # produces phase steps of up to 95 degrees in one sample -- which
            # the accumulator would happily bank as real progress.
            e1 = self._e1 - (self._e1 @ nhat) * nhat
            n1 = float(np.linalg.norm(e1))
            if n1 < 0.1:                       # basis has gone parallel to n
                ref = np.zeros(3)
                ref[int(np.argmin(np.abs(nhat)))] = 1.0
                e1 = ref - (ref @ nhat) * nhat
                n1 = float(np.linalg.norm(e1))
            if n1 > 1e-9:
                e1 = e1 / n1
                self._e1 = e1
                e2 = np.cross(nhat, e1)   # (e1, e2, nhat) right-handed
                phi = float(np.arctan2(dyn @ e2, dyn @ e1))

        # 6. Instantaneous frequency, smoothed. The pointwise derivative spans
        #    8x between p10 and p90 on real data, so it is only usable averaged.
        #    The tracker is a feedback loop -- frequency sets the window size,
        #    which sets the phase, which sets the frequency -- so it must only
        #    run when there is something real to lock onto. Left ungated it
        #    ratchets to the ceiling on noise, shrinking the window until it
        #    nulls nothing, and never recovers. With no signal it relaxes back
        #    to nominal instead.
        tracking = (self._phi_prev is not None
                    and a_major > c.track_amp_floor_g
                    and circ > c.track_min_circularity)
        if tracking:
            # Signed, and clipped only after averaging. Taking abs() of a noisy
            # rate first would rectify the noise and bias the estimate high --
            # it read 1.15 Hz on a 0.98 Hz gesture that way.
            rate = _wrap(phi - self._phi_prev) * self.fs / (2.0 * np.pi)
            self._freq += self._a_freq * (rate - self._freq)
        else:
            self._freq += self._a_freq * (c.f0_hz - self._freq)
        self._freq = float(np.clip(self._freq, c.min_freq_hz, c.max_freq_hz))

        # 7. Radius. Because the demodulation now sits *on* the tracked
        #    frequency, the averager has unity gain there and needs no roll-off
        #    correction. Dividing by omega^2 is what makes the gate a test of
        #    "is this a circle of plausible size" rather than of raw
        #    acceleration -- amplitude varies 16x across a 4x speed change.
        w = 2.0 * np.pi * self._freq
        radius = a_major * G_MS2 / (w * w)

        # 8. Direction comes from the plane normal, not from the phase step.
        #    The (e1, e2) basis is built from P and Q, which themselves flip
        #    when the circle reverses -- so phase always advances positively in
        #    that basis and cannot reveal direction. The normal can: it is
        #    anchored to the sensor frame, so its sign is comparable between
        #    captures, exactly like the sense A/B convention in plot.py.
        direction = 0
        if stability >= c.min_normal_stability:
            axis = int(np.argmax(np.abs(self._normal)))
            direction = 1 if self._normal[axis] > 0 else -1

        # 9. The gate: the fast path opens it, the slow path holds a veto.
        #
        #    The slow test only gets a vote once its window is actually full of
        #    motion. At the start of a gesture the window still holds the
        #    stillness that preceded it, so the lock-in output is meaningless --
        #    vetoing on that would reinstate the very warm-up the fast path
        #    exists to remove. Amplitude is what says "this window is real".
        #    Walking has no such excuse: its window is full of genuine motion
        #    that simply is not round, so the veto lands and holds.
        if self._gated:
            slow_ok = (circ >= c.hold_circularity
                       and stability >= c.hold_normal_stability
                       and c.min_radius_m / c.hold_radius_scale
                       <= radius <= c.max_radius_m * c.hold_radius_scale)
        else:
            slow_ok = (circ >= c.min_circularity
                       and stability >= c.min_normal_stability
                       and c.min_radius_m <= radius <= c.max_radius_m)

        #    Whichever path can actually see decides. Once the lock-in window is
        #    full of real motion it is strictly the better judge (separation
        #    0.45 against the fast path's 0.31), so it takes over completely --
        #    leaving the fast path as a permanent requirement would let its
        #    noisier dips punch holes in a gesture the slow path can see
        #    perfectly well.
        slow_confident = a_major > c.track_amp_floor_g
        gate = slow_ok if slow_confident else fast_ok
        self._gated = gate

        # 10. Accumulate. Backward steps are *discarded*, not subtracted, so the
        #     traced arc never un-draws. On real captures raw phase crawls
        #     backward by up to 66 deg -- a fifth of the circle -- which would
        #     be plainly visible on screen.
        if gate and self._phi_prev is not None:
            step = _wrap(phi - self._phi_prev)
            deadband = c.min_rate_frac * 2.0 * np.pi * self._freq / self.fs
            # A hand cannot advance faster than max_freq_hz, so anything above
            # that is an artefact, not progress. Belt and braces alongside the
            # continuous basis above.
            max_step = 2.0 * np.pi * c.max_freq_hz / self.fs
            if deadband < step <= max_step:
                self._accum += step - deadband
        elif not gate:
            self._accum -= self._a_rel * self._accum
            if self._accum < 1e-4:
                self._accum = 0.0

        self._phi_prev = phi

        openness = min(self._accum / (2.0 * np.pi), 1.0)
        if openness >= 1.0:
            self._opened = True

        return Frame(openness=openness, direction=direction, circularity=circ,
                     stability=stability, radius_m=radius,
                     freq_hz=self._freq, gate_open=gate)


def run_capture(t, acc, cfg: DetectorConfig | None = None) -> Result:
    """Run the detector over a whole capture. Equivalent to streaming it."""
    t = np.asarray(t, dtype=float)
    acc = np.asarray(acc, dtype=float)
    # (len - 1) intervals span the capture; using len would bias fs upward.
    fs = (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 and t[-1] > t[0] else 100.0

    det = Detector(fs, cfg)
    frames = [det.push(row) for row in acc]

    openness = np.array([f.openness for f in frames])
    opened = np.flatnonzero(openness >= 1.0)
    return Result(
        t=t,
        openness=openness,
        direction=np.array([f.direction for f in frames]),
        circularity=np.array([f.circularity for f in frames]),
        stability=np.array([f.stability for f in frames]),
        radius_m=np.array([f.radius_m for f in frames]),
        freq_hz=np.array([f.freq_hz for f in frames]),
        gate_open=np.array([f.gate_open for f in frames]),
        opened_at=float(t[opened[0]]) if opened.size else None,
        frames=frames,
    )
