"""What the portal should be doing, second by second, for a given capture.

The detector reports *rotation*. This adds the layer above it: a latching portal
that opens on clockwise, closes on counter-clockwise, and holds whatever state
it is in when your hand stops.

    python -m portal.simulate cw_short.csv
    python -m portal.simulate cw_short.csv --timeline

State machine
-------------
Two latched states, CLOSED and OPEN, with `openness` travelling between them:

    CLOSED --- clockwise rotation accumulates openness 0 -> 1 ---> OPEN
    OPEN   --- counter-clockwise accumulates openness 1 -> 0 ---> CLOSED

Rotation in the direction you are already latched at does nothing: spinning
clockwise at an open portal cannot make it more than open.

Partial progress decays back to the latched state when you stop, but a latched
state itself never decays. Stop halfway through opening and the arc fades out;
finish the turn and the portal stays open with your hand at your side. Without
that split a stray half-circle would leave a permanent half-drawn arc on the
wall, which reads as a bug rather than as magic.
"""
import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .detect import Detector, DetectorConfig, run_capture
from .plot import load_capture

# Measured on the Phase 1 captures: the clockwise gesture reports direction -1,
# counter-clockwise +1. The sign is anchored to the sensor frame, so it is only
# meaningful for a ring mounted the same way round. Re-check after remounting.
#
# +1 means counter-clockwise opens the portal and clockwise closes it, which is
# how Strange does it on screen.
OPENING_SENSE = +1

CLOSED, OPENING, OPEN, CLOSING = "CLOSED", "OPENING", "OPEN", "CLOSING"


@dataclass
class PortalConfig:
    opening_sense: int = OPENING_SENSE
    # Partial progress bleeds away this fast once the hand stops.
    decay_tau_s: float = 0.8
    # Below this, an unlatched arc is treated as gone.
    epsilon: float = 0.02

    # How close to an end counts as arriving there. Latching on exact equality
    # leaves a dead band: the display rounds 0.995 up to "100%" while the state
    # is still unlatched, so the portal looks finished, then springs back. Any
    # renderer reading `openness` would have the same problem.
    latch_epsilon: float = 0.02

    # Commit point. Once this much of the arc has been drawn, the portal
    # finishes on its own and stops following the hand -- otherwise you have to
    # keep circling all the way to the end, and stopping midway springs it back
    # to where it started, which feels like the gesture failed.
    #
    # 0.40 is set by the negatives, not by taste: walking peaks at 0.17 openness
    # and near-miss arm motion at 0.25, so this clears both with margin. Below
    # the commit point the old behaviour still applies and a stray part-circle
    # decays away. Set to 1.0 to disable committing entirely.
    commit_at: float = 0.40
    # How long the unattended remainder takes.
    commit_time_s: float = 0.40


class PortalState:
    """Latching portal driven by detector frames. One `push` per sample."""

    def __init__(self, fs: float, cfg: PortalConfig | None = None):
        self.fs = float(fs)
        self.cfg = cfg or PortalConfig()
        self._decay = 1.0 - np.exp(-1.0 / (self.cfg.decay_tau_s * fs))
        self.openness = 0.0
        self.latched = CLOSED
        self._prev_arc = 0.0
        self._last_dir = 0
        self._committed = 0      # +1 finishing open, -1 finishing closed
        self._commit_step = 1.0 / max(self.cfg.commit_time_s * fs, 1.0)

    def push(self, frame, armed: bool = True) -> tuple[str, float]:
        c = self.cfg
        was = self.openness
        # The detector's accumulator only ever counts forward, so its per-sample
        # progress is the *rise* in its openness. Sign it by the direction the
        # hand is actually going.
        arc = frame.openness
        delta = max(arc - self._prev_arc, 0.0)
        self._prev_arc = arc

        # Direction drops to 0 whenever plane stability dips, including partway
        # through a perfectly good gesture. Hold the last confident reading
        # rather than discarding progress -- a momentary loss of confidence
        # about *which way* is not a reason to forget that the hand is moving.
        if frame.direction != 0:
            self._last_dir = frame.direction

        # The key ring. Without it the hand is simply not listened to: progress
        # is dropped and any commit abandoned, so the sample falls through to
        # the decay branch and openness returns to whatever we are latched at.
        #
        # `_prev_arc` is still advanced above, and that ordering is the whole
        # trick. The detector keeps accumulating while disarmed, so if the rise
        # were left untracked the first armed sample would see the entire
        # disarmed gesture as one delta and slam the portal open with no arc
        # ever drawn. Consuming the rise and discarding it means re-arming
        # resumes from zero progress, as though the gesture had just begun.
        if not armed:
            delta = 0.0
            self._committed = 0

        # No gate test here. The detector already applied it: a rise in its
        # accumulator IS gated progress. Re-testing the gate on this side threw
        # away the first third of every gesture, because the arc starts growing
        # in the same samples where the gate is still flickering on.
        if self._committed != 0:
            # Past the commit point the hand is no longer consulted. Run to the
            # end at a fixed rate so the portal always takes the same time to
            # finish, however the gesture tailed off.
            self.openness = float(np.clip(
                self.openness + self._committed * self._commit_step, 0.0, 1.0))
        elif delta > 0.0 and self._last_dir != 0:
            signed = delta if self._last_dir == c.opening_sense else -delta
            self.openness = float(np.clip(self.openness + signed, 0.0, 1.0))
        else:
            # No forward progress: fall back toward whichever state we are
            # latched at. This must not be conditional on the gate being shut --
            # a gated sample that happens to carry no progress would otherwise
            # match no branch at all and strand openness wherever it stopped.
            target = 1.0 if self.latched == OPEN else 0.0
            self.openness += self._decay * (target - self.openness)
            if abs(self.openness - target) < c.epsilon:
                self.openness = target

        if self._committed == 0:
            if self.latched == CLOSED and self.openness >= c.commit_at:
                self._committed = 1
            elif self.latched == OPEN and self.openness <= 1.0 - c.commit_at:
                self._committed = -1

        # Snap only in the direction of travel. Snapping whenever openness is
        # merely *near* an end also fires while it is climbing away from that
        # end, pinning it there: a rise to 0.01 would be dragged back to 0 every
        # sample and the portal could never leave closed. Mirrored at the top,
        # it would jerk a closing portal back to fully open.
        if self.openness >= 1.0 - c.latch_epsilon and self.openness >= was:
            self.openness = 1.0          # snap, so downstream sees exactly 1.0
            self.latched = OPEN
            self._committed = 0
        elif self.openness <= c.latch_epsilon and self.openness <= was:
            self.openness = 0.0
            self.latched = CLOSED
            self._committed = 0

        if self.openness >= 1.0:
            state = OPEN
        elif self.openness <= 0.0:
            state = CLOSED
        elif self.latched == OPEN:
            state = CLOSING
        else:
            state = OPENING
        return state, self.openness


def simulate(t, acc, dcfg=None, pcfg=None):
    """Run detector + state machine over a capture. Returns (states, openness)."""
    t = np.asarray(t, float)
    fs = (len(t) - 1) / (t[-1] - t[0]) if len(t) > 1 else 100.0
    res = run_capture(t, acc, dcfg)
    sm = PortalState(fs, pcfg)
    states, opens = [], []
    for f in res.frames:
        s, o = sm.push(f)
        states.append(s)
        opens.append(o)
    return np.array(states), np.array(opens), res, fs


def motion_bursts(acc, fs, on=0.45, off=0.28, min_gap_s=0.3):
    """Indices where the hand starts moving. Schmitt trigger with a minimum
    quiet gap, so one gesture is not split into several by a momentary lull.

    Thresholds are set from real captures: between repetitions the hand settles
    to only ~0.1-0.25 g, not to zero, so a low release threshold never fires and
    seven gestures read as one.
    """
    def ema(x, tau):
        a = 1.0 - np.exp(-1.0 / (tau * fs))
        y = np.zeros_like(x)
        v = x[0]
        for i, xi in enumerate(x):
            v += a * (xi - v)
            y[i] = v
        return y

    dyn = acc - ema(acc, 1.5)
    mag = ema(np.linalg.norm(dyn, axis=1), 0.10)
    starts, moving, quiet = [], False, 0
    for i, m in enumerate(mag):
        if moving:
            if m < off:
                quiet += 1
                if quiet > min_gap_s * fs:
                    moving = False
            else:
                quiet = 0
        elif m > on:
            starts.append(i)
            moving, quiet = True, 0
    return starts


def transitions(states):
    """(index, from_state, to_state) for every latched change."""
    out, prev = [], states[0]
    for i, s in enumerate(states):
        if s in (OPEN, CLOSED) and s != prev and prev in (OPEN, CLOSED, OPENING, CLOSING):
            if not out or out[-1][2] != s:
                out.append((i, prev, s))
        if s in (OPEN, CLOSED):
            prev = s
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("capture")
    ap.add_argument("--timeline", action="store_true",
                    help="print a per-second bar of portal openness")
    args = ap.parse_args()

    path = Path(args.capture)
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        return 1

    t, acc, _gyr = load_capture(path)
    states, opens, res, fs = simulate(t, acc)
    starts = motion_bursts(acc, fs)

    print(f"\n{path.name}   {t[-1]:.1f} s   {len(starts)} motion bursts")

    ev = transitions(states)
    if not ev:
        print("  portal never changed state "
              f"(peak openness {opens.max():.2f})")
    else:
        print("\n  PORTAL EVENTS")
        print("    time     event      took   turns   from hand starting to move")
        times = []
        for i, frm, to in ev:
            prior = [j for j in starts if j <= i]
            j0 = prior[-1] if prior else 0
            took = t[i] - t[j0]
            f = float(np.median(res.freq_hz[j0:i + 1])) if i > j0 else res.freq_hz[i]
            if to == OPEN:
                times.append(took)
            print(f"    {t[i]:6.2f}s  {'OPENS' if to == OPEN else 'CLOSES':<9}"
                  f"{took:5.2f}s  {took * f:5.2f}   (started {t[j0]:.2f}s)")
        if times:
            print(f"\n  TIME TO OPEN: fastest {min(times):.2f}s   "
                  f"median {np.median(times):.2f}s   slowest {max(times):.2f}s")

    if args.timeline:
        print("\n  TIMELINE  (# = open, - = partial, . = closed)")
        for s in range(int(t[-1]) + 1):
            m = (t >= s) & (t < s + 1)
            if not m.any():
                continue
            o = float(np.median(opens[m]))
            st = states[m][len(states[m]) // 2]
            bar = "#" * int(round(o * 30))
            print(f"    {s:3d}s |{bar:<30}| {o:4.2f}  {st}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
