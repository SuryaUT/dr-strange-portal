"""Reconstruct and plot the motion recorded in a capture.

Position is deliberately NOT reconstructed. Double-integrating accelerometer
data lets bias grow as t^2, so a "path" would be dominated by drift within a
couple of seconds. What is recoverable is the dynamic acceleration vector, and
for circular motion that vector sweeps a circle in the plane of travel — so the
trajectory plotted here is the shape of the motion, in acceleration space.

Standalone use, to re-plot any capture:
    python -m portal.plot capture.csv
    python -m portal.plot capture.csv other_name.png
"""

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")          # no GUI needed; we only write files
import matplotlib.pyplot as plt
import numpy as np

# Gravity is the slow-moving part of the accelerometer signal. This is the time
# constant of the moving average used to estimate and remove it. It must be well
# above one gesture period (~1 s) or it would eat the gesture itself.
GRAVITY_TAU_S = 1.5


@dataclass
class MotionSummary:
    """Numbers worth printing or asserting on, independent of the figure."""

    samples: int
    duration_s: float
    rate_hz: float
    planarity: float          # fraction of energy in the dominant plane, 0-1
    median_speed_hz: float    # circles per second while actually moving
    peak_amplitude_g: float
    net_turns: float          # signed; sign is the direction of rotation


def load_capture(path: str | Path):
    """Read a capture CSV into (t_seconds, accel_g, gyro_dps) arrays."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path} contains no data rows")

    t = np.array([float(r["device_ms"]) for r in rows]) / 1000.0
    t -= t[0]
    acc = np.array([[float(r["ax_g"]), float(r["ay_g"]), float(r["az_g"])]
                    for r in rows])
    gyr = np.array([[float(r["gx_dps"]), float(r["gy_dps"]), float(r["gz_dps"])]
                    for r in rows])
    return t, acc, gyr


def analyse(t, acc):
    """Remove gravity, find the plane of motion, and track phase within it."""
    fs = len(t) / (t[-1] - t[0]) if t[-1] > t[0] else 0.0

    alpha = 1.0 - np.exp(-1.0 / (GRAVITY_TAU_S * fs)) if fs > 0 else 0.5
    grav = np.zeros_like(acc)
    g = acc[0].copy()
    for i, a in enumerate(acc):
        g += alpha * (a - g)
        grav[i] = g
    dyn = acc - grav

    # The plane the motion actually happened in.
    centred = dyn - dyn.mean(axis=0)
    _, sv, vt = np.linalg.svd(centred, full_matrices=False)
    energy = sv**2 / np.sum(sv**2)

    # SVD basis vectors have arbitrary sign, so the rotation sense they imply
    # flips at random between captures. Anchor the basis to the sensor frame:
    # make the plane normal point positively along whichever sensor axis it is
    # most aligned with. With the ring rigidly mounted and the gesture plane
    # roughly fixed, that makes the sign of rotation mean the same thing in
    # every capture — which is what makes direction labels comparable.
    normal = np.cross(vt[0], vt[1])
    if normal[np.argmax(np.abs(normal))] < 0:
        vt[1] = -vt[1]

    u = centred @ vt[0]
    v = centred @ vt[1]

    # Phase within that plane. For circular motion this advances monotonically,
    # and its sign is the direction of travel.
    phase = np.unwrap(np.arctan2(v, u))
    turns = (phase - phase[0]) / (2 * np.pi)
    speed = np.gradient(phase, t) / (2 * np.pi)
    amp = np.hypot(u, v)

    active = amp > max(0.05, 0.25 * amp.max())
    median_speed = float(np.median(np.abs(speed[active]))) if active.sum() > 10 else 0.0

    summary = MotionSummary(
        samples=len(t),
        duration_s=float(t[-1]),
        rate_hz=float(fs),
        planarity=float(energy[0] + energy[1]),
        median_speed_hz=median_speed,
        peak_amplitude_g=float(amp.max()),
        net_turns=float(turns[-1]),
    )
    return u, v, amp, turns, speed, active, summary


def plot_capture(csv_path: str | Path, png_path: str | Path | None = None) -> MotionSummary:
    """Plot a capture CSV. Returns the summary; writes the PNG beside the CSV."""
    csv_path = Path(csv_path)
    png_path = Path(png_path) if png_path else csv_path.with_suffix(".png")

    t, acc, gyr = load_capture(csv_path)
    u, v, amp, turns, speed, active, s = analyse(t, acc)

    fig = plt.figure(figsize=(15, 9))
    fig.suptitle(f"Recorded motion — {csv_path.name}", fontsize=13)

    ax1 = fig.add_subplot(2, 3, 1)
    for i, lbl in enumerate("xyz"):
        ax1.plot(t, acc[:, i], lw=0.8, label=f"a{lbl}")
    ax1.set_title("Accelerometer (raw)"); ax1.set_ylabel("g")
    ax1.legend(fontsize=8); ax1.grid(alpha=0.3)

    ax2 = fig.add_subplot(2, 3, 2)
    for i, lbl in enumerate("xyz"):
        ax2.plot(t, gyr[:, i], lw=0.8, label=f"g{lbl}")
    ax2.set_title("Gyroscope (raw)"); ax2.set_ylabel("deg/s")
    ax2.legend(fontsize=8); ax2.grid(alpha=0.3)

    ax3 = fig.add_subplot(2, 3, 3)
    ax3.plot(t, amp, lw=0.9, color="crimson")
    ax3.set_title("Motion strength (in-plane amplitude)")
    ax3.set_ylabel("g"); ax3.set_xlabel("s"); ax3.grid(alpha=0.3)

    ax4 = fig.add_subplot(2, 3, 4)
    pts = ax4.scatter(u, v, c=t, cmap="viridis", s=4)
    ax4.set_title("Motion path in its own plane\n(a circle here = a circle in the air)")
    ax4.set_xlabel("principal axis 1 (g)"); ax4.set_ylabel("principal axis 2 (g)")
    ax4.axhline(0, color="grey", lw=0.5); ax4.axvline(0, color="grey", lw=0.5)
    ax4.set_aspect("equal"); ax4.grid(alpha=0.3)
    fig.colorbar(pts, ax=ax4, label="time (s)")

    ax5 = fig.add_subplot(2, 3, 5)
    ax5.plot(t, turns, lw=1.2, color="darkorange")
    ax5.set_title("Accumulated rotation\n(steady ramp = sustained circling)")
    ax5.set_ylabel("turns"); ax5.set_xlabel("s")
    ax5.axhline(0, color="grey", lw=0.5); ax5.grid(alpha=0.3)

    ax6 = fig.add_subplot(2, 3, 6)
    ax6.plot(t[active], speed[active], ".", ms=2, color="teal")
    ax6.set_title("Gesture speed while moving"); ax6.set_ylabel("circles/sec")
    ax6.set_xlabel("s"); ax6.axhline(0, color="grey", lw=0.5); ax6.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(png_path, dpi=110)
    plt.close(fig)
    return s


def describe(s: MotionSummary) -> str:
    # Sign is anchored to the sensor frame, so it is comparable between
    # captures — but which physical direction maps to "+" depends on how the
    # ring is mounted. Label it A/B rather than claiming to know which is
    # clockwise in the room.
    sense = "sense A (+)" if s.net_turns >= 0 else "sense B (-)"
    lines = [
        f"  {s.samples} samples, {s.duration_s:.1f} s at {s.rate_hz:.1f} Hz",
        f"  motion plane holds {100 * s.planarity:.1f}% of energy",
        f"  {s.median_speed_hz:.2f} circles/sec median, peak {s.peak_amplitude_g:.2f} g",
        f"  net rotation {s.net_turns:+.2f} turns ({sense})",
    ]
    if s.rate_hz < 90.0:
        lines.append(
            f"  WARNING: {s.rate_hz:.0f} Hz is well below the expected 100 Hz - "
            f"roughly {100 * (1 - s.rate_hz / 100.0):.0f}% of samples are missing.\n"
            f"  Gaps look like stillness to a detector. Do not train on this capture."
        )
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m portal.plot CAPTURE.csv [OUT.png]", file=sys.stderr)
        return 2
    csv_path = sys.argv[1]
    png_path = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        summary = plot_capture(csv_path, png_path)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(describe(summary))
    print(f"wrote {Path(png_path) if png_path else Path(csv_path).with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
