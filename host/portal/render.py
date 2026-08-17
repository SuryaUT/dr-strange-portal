"""Render the portal: a live camera feed inside the ring, the ring's light on top.

The source clip holds the same animation three times over, on black, on green
and on blue. We use the black one and never key it. Fire is additive light with
no hard edge, so a chroma key would have to invent a coverage value for every
wispy spark; screen blending the black version instead reproduces the element
exactly as it was rendered, and leaves the far field at zero, which is what the
projector needs.
"""
import argparse
import math
from dataclasses import dataclass
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np


def screen_blend(base, over):
    """Add light: the compositing model for glows.

    Can only brighten, so where `over` is black the base passes through
    untouched -- and where both are black the result is exactly black.

    Written as `a + b - ab` rather than the textbook `1 - (1-a)(1-b)`. They are
    the same identity, but the textbook form cancels catastrophically in
    float32: with `a` at zero it evaluates `1 - (1 - b)`, which rounds to zero
    for any `b` below float32 epsilon and quietly drops the faintest glow.
    """
    return base + over - base * over


RIM_THRESHOLD = 150.0


def ring_center(gray, thresh=RIM_THRESHOLD):
    """Centre of the ring, or None if nothing is lit yet.

    Only genuinely bright pixels count. Sparks stream off one side of the ring
    and are dim but numerous, so averaging everything lit walks the centre
    toward the trails and away from the hole.
    """
    ys, xs = np.nonzero(gray > thresh)
    if len(xs) < 100:
        return None
    return float(xs.mean()), float(ys.mean())


def rim_radii(gray, cx, cy, n_angles=360, max_r=None, smooth=15):
    """Distance from (cx, cy) out to the rim's brightest point, per angle.

    March outward along each of `n_angles` rays and take the peak. This makes
    no assumption that the hole is round, so the feed fills a squashed or
    lopsided ring as readily as a circle. `smooth` averages neighbouring rays
    so a single dark spark gap cannot punch a notch in the outline.
    """
    h, w = gray.shape[:2]
    if max_r is None:
        max_r = int(min(h, w) * 0.5)
    blurred = cv2.GaussianBlur(gray, (31, 31), 0)

    angles = np.linspace(0.0, 2.0 * np.pi, n_angles, endpoint=False)
    steps = np.arange(max_r)
    px = np.clip((cx + np.cos(angles)[:, None] * steps).astype(int), 0, w - 1)
    py = np.clip((cy + np.sin(angles)[:, None] * steps).astype(int), 0, h - 1)
    radii = np.argmax(blurred[py, px], axis=1).astype(np.float32)

    kernel = np.ones(smooth, np.float32) / smooth
    wrapped = np.concatenate([radii, radii, radii])
    return np.convolve(wrapped, kernel, mode="same")[n_angles:2 * n_angles]


def rim_polygon(gray, fill=0.98):
    """The outline the camera feed fills, or None before the ring appears.

    `fill` places the edge just inside the rim's brightest point, so the ring's
    own light lands on top of the seam and hides it. Stop much short of that
    and a dark band opens up between feed and rim, which reads as a video
    window rather than a hole in space.

    Depends only on the clip, so the render loop precomputes one of these per
    frame at startup and never runs the geometry again.
    """
    center = ring_center(gray)
    if center is None:
        return None
    cx, cy = center

    radii = rim_radii(gray, cx, cy)
    angles = np.linspace(0.0, 2.0 * np.pi, len(radii), endpoint=False)
    return np.stack([cx + np.cos(angles) * radii * fill,
                     cy + np.sin(angles) * radii * fill], axis=1)


def mask_from_polygon(pts, shape, feather=81):
    """Fill and feather an outline into a uint8 mask.

    Rasterised at half resolution and scaled back up. The mask is smooth by
    construction so nothing is lost, and the feathering blur -- the expensive
    part -- gets four times cheaper, which is the difference between holding
    24fps and not.
    """
    h, w = shape[:2]
    half = np.zeros((h // 2, w // 2), np.uint8)
    cv2.fillPoly(half, [(np.asarray(pts) * 0.5).astype(np.int32)], 255)
    k = max(3, (feather // 2) | 1)
    half = cv2.GaussianBlur(half, (k, k), 0)
    return cv2.resize(half, (w, h), interpolation=cv2.INTER_LINEAR)


def portal_mask(gray, fill=0.98, feather=81):
    """Where the camera feed shows through, as a float mask in 0..1."""
    pts = rim_polygon(gray, fill)
    if pts is None:
        return np.zeros(gray.shape[:2], np.float32)
    return mask_from_polygon(pts, gray.shape[:2], feather).astype(np.float32) / 255.0


BLACK_FLOOR = 2


def clamp_black(frame, floor=BLACK_FLOOR):
    """Force the far field to true zero by subtracting a black level.

    The clip's "black" background is not black. Over the whole take, 26% of the
    corner pixels sit at value 1 -- a uniform dither floor across the entire
    frame. A projector cannot emit black, so that floor paints the 16:9
    rectangle on the wall in a dark room.

    A floor of 2 erases it: only 0.017% of corner pixels exceed 2, and those
    are individual sparks that fly out past the ring. They are content, and
    they stay. Going higher costs real picture quality for nothing -- a floor
    of 6 measured 35.4dB PSNR against the source where 2 gives 42.6dB.

    Subtracts rather than thresholds. The glow inside the ring is a smooth
    falloff, and zeroing everything under a cutoff would draw a visible contour
    ring where it crosses; subtracting keeps the slope continuous and costs the
    sparks a few levels nobody can see.
    """
    return cv2.subtract(frame, floor)


def black_segment(corner_luma, thresh=8.0):
    """Longest run of frames with dark corners, as `(start, count)`.

    The pack ships the same animation three times over -- on black, on green
    and on blue -- and we want the black one. Finding it by its corners rather
    than by hardcoded frame numbers means a re-export or a different pack still
    works, and it fails loudly instead of silently keying a green frame.
    """
    best_start, best_len = 0, 0
    run_start = None
    for i, luma in enumerate(list(corner_luma) + [float("inf")]):
        if luma <= thresh:
            if run_start is None:
                run_start = i
        elif run_start is not None:
            if i - run_start > best_len:
                best_start, best_len = run_start, i - run_start
            run_start = None
    return best_start, best_len


def composite(portal, camera, mask, alpha=1.0):
    """Camera inside the mask, portal light screened on top.

    The order matters. Pasting the camera over the portal instead would cover
    the glow that falls inside the hole and leave a hard circular cut, which
    reads as a sticker. Screening the portal on last puts its light *on* the
    feed, and leaves the far field untouched at zero.
    """
    return screen_blend(camera * (mask * alpha)[..., None], portal)


def composite_u8(portal, camera, mask, alpha=1.0):
    """`composite`, in integers, for the render loop.

    Identical arithmetic; only the types differ. The float path allocates four
    full-HD float32 temporaries per frame and costs 61ms, which cannot hold the
    clip's 24fps. OpenCV's saturating integer primitives do it in 9ms.

    Grouped as `portal + scaled*(1 - portal)` rather than the reference's
    `a + b - ab`. Integer ops saturate, and the direct form overflows at
    `add` before the product comes off again, collapsing every pixel where
    camera and ring are both bright. This grouping keeps each intermediate
    inside 0..255.
    """
    scaled = cv2.multiply(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), camera,
                          scale=alpha / 255.0)
    lit = cv2.subtract(scaled, cv2.multiply(scaled, portal, scale=1.0 / 255.0))
    return cv2.add(portal, lit)


GLOW_KERNEL = 81


def blend_glow(head, tail, weight, kernel=GLOW_KERNEL):
    """Ease the smooth light across a cut while the spark detail hard-switches.

    The loop's seam is not a brightness problem -- levelling the two frames
    made the mismatch worse (12.08 against 11.59) -- it is that 59% of the
    difference lives in the spark pattern. But sparks must never cross-
    dissolve: two chaotic patterns blended read as a double exposure, measured
    worse than doing nothing at all.

    So the frame is split. The low frequencies, which carry the coherent glow
    the eye tracks, dissolve from `tail` to `head` by `weight`. The high
    frequencies stay entirely `head`'s, cutting in one step that hides inside
    the sparks' own motion.
    """
    head_f = head.astype(np.float32)
    low_head = cv2.GaussianBlur(head_f, (kernel, kernel), 0)
    detail = head_f - low_head
    low_tail = cv2.GaussianBlur(tail.astype(np.float32), (kernel, kernel), 0)
    low = low_head + (low_tail - low_head) * weight
    return np.clip(low + detail, 0, 255).astype(np.uint8)


CLOSED, OPENING, SUSTAIN, CLOSING = "CLOSED", "OPENING", "SUSTAIN", "CLOSING"

# The clip is 23.976fps. The playhead advances against this, not against
# whatever rate the renderer manages, so the animation keeps its intended
# duration on a slow machine and merely drops frames.
CLIP_FPS = 24000.0 / 1001.0


@dataclass
class Sections:
    """Where the clip's phases begin and end, measured off the black take.

    `open_end` is the brightest frame, where the arc has just closed into a
    full ring. The loop bounds come from searching the sustain for the pair of
    frames that match most closely: f219 back to f165 differs by RMS 11.15
    against 9.54 for an ordinary consecutive pair, so the jump is only 1.17x a
    step the eye already absorbs 24 times a second. Nothing is blended.

    Everything past the sustain is the clip's own closing animation, so closing
    is not a rewind -- it is simply letting the playhead keep running forward.
    """
    open_end: int = 107
    loop_start: int = 165
    loop_end: int = 219
    shrink_start: int = 248
    close_end: int = 340


class Playhead:
    """Which clip frame to show, given how open the portal is.

    Openness scrubs the arc while it is being drawn, so the sparks trace along
    with the hand. Once it reaches full, the playhead goes time-driven and
    loops the sustain, because a canned clip cannot separate openness-driven
    structure from time-driven fire -- and holding a scrubbed playhead still
    would freeze the fire in mid-air.
    """

    def __init__(self, sections=None, close_speed=2.5, open_speed=1.0,
                 smooth_tau=0.05):
        self.s = sections or Sections()
        self.close_speed = close_speed
        self.open_speed = open_speed
        self.smooth_tau = smooth_tau
        self.state = CLOSED
        self.position = 0.0
        self._openness = 0.0
        self._wrapped = False

    @property
    def alpha(self):
        """How strongly the camera feed shows through, 0..1.

        Follows openness only while the arc is being drawn. Once the portal is
        open the feed is simply there, and through the closing animation it
        stays there -- the shrinking hole in the clip takes it away on its own,
        so fading it as well would blink the destination out and leave an empty
        ring collapsing.
        """
        if self.state == CLOSED:
            return 0.0
        if self.state == OPENING:
            # Follows how far the ring has actually drawn, not how far the
            # gesture has got: openness can reach 1.0 seconds before there is
            # a hole to look through.
            return float(np.clip(self.position / max(self.s.open_end, 1), 0.0, 1.0))
        return 1.0

    def seam_index(self, n):
        """How far into the post-wrap softening window we are, else None.

        Only a wrap needs softening. Arriving into the sustain from the opening
        is already continuous -- those are consecutive frames of the clip.
        """
        if not self._wrapped or self.state != SUSTAIN:
            return None
        k = int(self.position - self.s.loop_start)
        return k if 0 <= k < n else None

    def update(self, openness, dt=None):
        """Advance by `dt` seconds and return the clip frame to show.

        `dt` defaults to exactly one clip frame, which is what the unit tests
        want. The render loop passes real elapsed time, so a renderer that
        cannot hold 24fps drops frames rather than playing in slow motion.
        """
        step = 1.0 if dt is None else dt * CLIP_FPS
        self._openness = openness
        if self.state in (CLOSED, OPENING):
            before = self.position
            target = float(frame_for_openness(min(openness, 1.0),
                                              self.s.open_end + 1))
            if dt is None or self.smooth_tau <= 0.0:
                self.position = target
            else:
                # Chase the target instead of snapping onto it. Openness
                # arrives with the BLE packets, ~10 times a second, while the
                # renderer draws 40-56 times a second; snapping made the whole
                # opening animate at the input's rate, in jumps of up to 27
                # clip frames. A short time constant fills in the frames
                # between updates for a few tens of milliseconds of lag --
                # nothing against the ~2s the detector needs to be sure of the
                # gesture in the first place.
                self.position += (target - self.position) * (
                    1.0 - math.exp(-dt / self.smooth_tau))
            # Never faster than the clip itself. Openness reaches 1.0 in
            # about 0.8s while the arc takes 4.5s to draw, so following it
            # directly played the opening at 5.6x and turned the spark trace
            # into a blur. Rate-limited, a quick gesture simply hands over and
            # the animation finishes itself at its own pace.
            if dt is not None:
                limit = step * self.open_speed
                self.position = before + max(-limit, min(limit,
                                                         self.position - before))
            if openness >= 1.0 and self.position >= self.s.open_end - 1.0:
                self.state = SUSTAIN
            else:
                self.state = OPENING if openness > 0.0 or self.position > 0.5 \
                    else CLOSED
        elif self.state == SUSTAIN:
            if openness < 1.0:
                # Jump to where the ring actually starts shrinking. f219-f248
                # holds its radius at 286-288px: sustain material, and playing
                # it as the close is what read as a delay.
                self.state = CLOSING
                self.position = max(self.position, float(self.s.shrink_start))
            else:
                self.position += step
                if self.position > self.s.loop_end:
                    span = self.s.loop_end - self.s.loop_start
                    over = self.position - self.s.loop_end
                    self.position = self.s.loop_start + (over % max(span, 1e-6))
                    self._wrapped = True
        if self.state == CLOSING:
            self.position += step * self.close_speed
            if self.position >= self.s.close_end:
                self.state = CLOSED
                self.position = 0.0
        return int(self.position)


def mask_bounds(pts, shape, feather=81):
    """Frame-clipped box around a feathered mask, as `(x0, y0, x1, y1)`.

    Widened by the feather, because blurring spreads the mask past its polygon
    and a box drawn on the polygon alone would clip the soft edge into a hard
    line.
    """
    h, w = shape[:2]
    pts = np.asarray(pts)
    margin = feather
    x0 = int(max(0, np.floor(pts[:, 0].min()) - margin))
    y0 = int(max(0, np.floor(pts[:, 1].min()) - margin))
    x1 = int(min(w, np.ceil(pts[:, 0].max()) + margin))
    y1 = int(min(h, np.ceil(pts[:, 1].max()) + margin))
    return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)


def composite_into(portal, camera, mask, bounds, alpha=1.0):
    """`composite_u8` restricted to `bounds`, writing into `portal`.

    Outside the mask the camera contributes nothing, so the portal frame is
    already the finished picture there. The disc covers roughly a quarter of
    the frame, so confining the arithmetic to it is most of what buys the
    frame rate.

    Mutates and returns `portal`, which is a freshly decoded frame in the
    render loop and owned by the caller.
    """
    x0, y0, x1, y1 = bounds
    portal[y0:y1, x0:x1] = composite_u8(portal[y0:y1, x0:x1],
                                        camera[y0:y1, x0:x1],
                                        mask[y0:y1, x0:x1], alpha)
    return portal


def frame_for_openness(openness, n_open_frames):
    """Scrub the opening section with the hand: openness 0..1 -> frame index.

    The sparks trace the rim as the arc closes, so scrubbing this section makes
    the portal draw itself along with the gesture.
    """
    idx = int(round(float(np.clip(openness, 0.0, 1.0)) * (n_open_frames - 1)))
    return max(0, min(idx, n_open_frames - 1))


def camera_source(value):
    """A device index if it looks like one, otherwise a URL or file path.

    Lets the portal look through a phone streaming MJPEG over wifi, or a
    recorded clip of somewhere else, exactly as readily as a local webcam.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def mirror(frame):
    """Flip left-to-right, so the feed reads like a mirror rather than a window.

    Only left-right. A vertical flip would put the destination upside down.
    """
    return cv2.flip(frame, 1)


def list_displays():
    """Every monitor as (x, y, width, height), primary first. Windows only.

    Falls back to an empty list anywhere else, which `choose_display` treats as
    "just leave the window where it is".
    """
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return []
    monitors = []

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    proc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                              ctypes.POINTER(RECT), ctypes.c_double)

    def callback(_hmon, _hdc, rect, _data):
        r = rect.contents
        monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    user32.EnumDisplayMonitors(0, 0, proc(callback), 0)
    monitors.sort(key=lambda m: (m[0] != 0 or m[1] != 0, m[0], m[1]))
    return monitors


def choose_display(monitors, index):
    """The monitor to put the portal on, or None if there are none to pick.

    An out-of-range index falls back to the primary rather than failing: losing
    the projector mid-shoot should leave you a window you can still see.
    """
    if not monitors:
        return None
    if 0 <= index < len(monitors):
        return monitors[index]
    return monitors[0]


def cover_crop(img, out_w, out_h):
    """Scale `img` to cover `out_w` x `out_h` and centre-crop the overflow.

    Aspect ratio is preserved, so a webcam of any shape fills the frame without
    stretching faces.
    """
    h, w = img.shape[:2]
    if (h, w) == (out_h, out_w):
        return img
    scale = max(out_w / w, out_h / h)
    resized = cv2.resize(img, (int(round(w * scale)), int(round(h * scale))),
                         interpolation=cv2.INTER_AREA)
    rh, rw = resized.shape[:2]
    x0 = (rw - out_w) // 2
    y0 = (rh - out_h) // 2
    return resized[y0:y0 + out_h, x0:x0 + out_w]


def corner_luma(frame, size=60):
    """Mean brightness of the four corners -- what the background colour is."""
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean([g[:size, :size].mean(), g[:size, -size:].mean(),
                          g[-size:, :size].mean(), g[-size:, -size:].mean()]))


class PortalClip:
    """The black-background take, with its rim geometry worked out in advance.

    Two things make the render loop cheap. The rim geometry depends only on the
    clip, so every frame's outline is measured once here rather than 60 times a
    second later. And the frames are held as JPEG rather than raw -- 341 frames
    of 1080p is 2.1GB raw against 33MB encoded, for 7ms of decode.

    Both are cached beside the clip, so only the first run pays for any of it.
    """

    CACHE_VERSION = 1

    def __init__(self, path, fill=0.98, floor=BLACK_FLOOR, verbose=True):
        self.path = Path(path)
        self.fill = fill
        self.floor = floor
        self._log = (lambda m: print(m, flush=True)) if verbose else (lambda m: None)
        self._fcache, self._mcache = {}, {}
        cache = self.path.with_suffix(".portalcache.npz")
        if not self._load_cache(cache):
            self._build()
            self._save_cache(cache)
        self._log(f"clip ready: {len(self)} frames, "
                  f"{self._blobs.nbytes / 1e6:.0f}MB encoded")

    def __len__(self):
        return len(self._offsets) - 1

    def _decode(self, index):
        index = max(0, min(int(index), len(self) - 1))
        blob = self._blobs[self._offsets[index]:self._offsets[index + 1]]
        return clamp_black(cv2.imdecode(blob, cv2.IMREAD_COLOR), self.floor)

    def frame(self, index):
        """Decoded frame `index`, with the black level already forced to zero.

        Cached frames are copied on the way out. `composite_into` writes into
        the frame it is handed, so serving the cached array itself would burn
        the camera feed permanently into the cache.
        """
        index = max(0, min(int(index), len(self) - 1))
        hit = self._fcache.get(index)
        return hit.copy() if hit is not None else self._decode(index)

    def warm(self, indices, feather=81, budget_mb=600):
        """Preload decoded frames and masks for frames that repeat.

        The sustain loops the same few dozen frames forever, so decoding them
        every time is pure waste: 10.5ms of JPEG plus 3.8ms of mask per frame,
        against a copy. Bounded by `budget_mb` so a long loop cannot eat the
        machine.
        """
        used = 0
        for i in indices:
            i = max(0, min(int(i), len(self) - 1))
            if i in self._fcache:
                continue
            f, m = self._decode(i), self._build_mask(i, feather)
            used += f.nbytes + m.nbytes
            if used > budget_mb * 1e6:
                self._log(f"cache stopped at {len(self._fcache)} frames "
                          f"({budget_mb}MB budget)")
                break
            self._fcache[i], self._mcache[i] = f, m
        if self._fcache:
            mb = sum(f.nbytes for f in self._fcache.values())
            mb += sum(m.nbytes for m in self._mcache.values())
            self._log(f"cached {len(self._fcache)} frames + masks "
                      f"({mb / 1e6:.0f}MB)")

    def mask(self, index, feather=81):
        """uint8 mask for frame `index`, built from the precomputed outline.

        Not copied: the composite only reads the mask, never writes it.
        """
        index = max(0, min(int(index), len(self) - 1))
        hit = self._mcache.get(index)
        if hit is not None:
            return hit
        return self._build_mask(index, feather)

    def _build_mask(self, index, feather=81):
        index = max(0, min(int(index), len(self) - 1))
        pts = self._polys[index]
        if not np.isfinite(pts).all():
            return np.zeros(self.shape, np.uint8)
        return mask_from_polygon(pts, self.shape, feather)

    def build_seam(self, sections, n=8):
        """Precompute the softened frames used just after the loop wraps.

        Two full-HD Gaussian blurs per frame is far too slow to do live, but
        these frames never change, so they are built once here and simply
        played back.
        """
        self._seam = []
        for k in range(n):
            head = self.frame(sections.loop_start + k)
            tail = self.frame(sections.loop_end + k)   # what actually followed
            self._seam.append(blend_glow(head, tail, 1.0 - k / n))

    def seam_frame(self, k):
        return self._seam[k].copy()

    def bounds(self, index, feather=81):
        """Box the camera can reach in frame `index`, or None before the ring."""
        index = max(0, min(int(index), len(self) - 1))
        pts = self._polys[index]
        if not np.isfinite(pts).all():
            return None
        return mask_bounds(pts, self.shape, feather)

    def _build(self):
        self._log(f"reading {self.path.name} (first run only)...")
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise SystemExit(f"error: cannot open {self.path}")

        encoded, corners, shape = [], [], None
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            shape = frame.shape[:2]
            corners.append(corner_luma(frame))
            encoded.append(cv2.imencode(".jpg", frame,
                                        [cv2.IMWRITE_JPEG_QUALITY, 95])[1])
        cap.release()
        if not encoded:
            raise SystemExit(f"error: no frames decoded from {self.path}")

        start, count = black_segment(corners)
        if count == 0:
            raise SystemExit(
                f"error: no black-background section found in {self.path.name}. "
                "This renderer screen-blends a black take; a green or blue one "
                "would need keying instead.")
        self._log(f"black take: frames {start}..{start + count - 1} "
                  f"of {len(encoded)}")

        self.shape = shape
        chunk = encoded[start:start + count]
        self._offsets = np.cumsum([0] + [c.nbytes for c in chunk]).astype(np.int64)
        self._blobs = np.concatenate([c.ravel() for c in chunk])

        self._log(f"measuring rim geometry on {count} frames...")
        polys = []
        for i in range(count):
            gray = cv2.cvtColor(cv2.imdecode(chunk[i], cv2.IMREAD_COLOR),
                                cv2.COLOR_BGR2GRAY).astype(np.float32)
            pts = rim_polygon(gray, self.fill)
            polys.append(np.full((360, 2), np.nan) if pts is None else pts)
        self._polys = np.asarray(polys, np.float32)

    def _signature(self):
        st = self.path.stat()
        return np.array([self.CACHE_VERSION, st.st_size, int(st.st_mtime),
                         int(self.fill * 10000)], np.int64)

    def _load_cache(self, cache):
        if not cache.exists():
            return False
        try:
            with np.load(cache) as z:
                if not np.array_equal(z["signature"], self._signature()):
                    return False
                self._blobs = z["blobs"]
                self._offsets = z["offsets"]
                self._polys = z["polys"]
                self.shape = tuple(int(v) for v in z["shape"])
        except Exception:
            return False
        return True

    def _save_cache(self, cache):
        np.savez(cache, signature=self._signature(), blobs=self._blobs,
                 offsets=self._offsets, polys=self._polys,
                 shape=np.asarray(self.shape))
        self._log(f"cached geometry to {cache.name}")


DEFAULT_CLIP = "DOCTOR STRANGE PORTAL GREEN SCREEN ULTRA HD 4K - Filmcom Creation (1080p).mp4"


def find_clip(explicit=None):
    """Locate the portal clip: the given path, the default, or any mp4 there."""
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"error: no such clip: {path}")
        return path
    assets = Path(__file__).resolve().parents[2] / "assets"
    default = assets / DEFAULT_CLIP
    if default.exists():
        return default
    for candidate in sorted(assets.glob("*.mp4")):
        return candidate
    raise SystemExit(f"error: no .mp4 found in {assets}. Pass one with --clip.")


class Camera:
    """The destination the portal looks onto, or colour bars if there is none.

    Grabs on its own thread and keeps only the newest frame. A blocking read
    costs 32ms even on a good backend, which is most of a 24fps frame budget;
    off the critical path the render loop never waits for it, and a camera
    slower than the render simply repeats a frame.

    The backend matters more than anything else here. On this laptop DirectShow
    delivers 1080p at 5fps and 720p at 10fps, while Media Foundation does 1080p
    at 31fps from the same camera. `--dshow` is the escape hatch for cameras
    where Media Foundation misbehaves.
    """

    def __init__(self, index, width, height, dshow=False):
        local = isinstance(index, int)
        if local and index < 0:
            self.cap = None
        elif local:
            self.cap = cv2.VideoCapture(index,
                                        cv2.CAP_DSHOW if dshow else cv2.CAP_ANY)
        else:
            # A URL or path: let OpenCV/FFmpeg pick the backend, and never ask
            # a network stream to change its resolution.
            self.cap = cv2.VideoCapture(index)
        if self.cap is not None and not self.cap.isOpened():
            print(f"warning: could not open camera {index!r}, using colour bars",
                  file=sys.stderr)
            self.cap = None
        if self.cap is not None and local:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if self.cap is not None and not local:
            # Keep the newest frame only; a stalled network stream must not
            # back up a queue of stale frames behind the live one.
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._bars = self._colour_bars(height, width)

        self._latest = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        if self.cap is not None:
            self._thread = threading.Thread(target=self._grab, daemon=True)
            self._thread.start()

    def _grab(self):
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if not ok:
                self._stop.wait(0.01)
                continue
            with self._lock:
                self._latest = frame

    @staticmethod
    def _colour_bars(h, w):
        hues = np.linspace(0, 179, 8).astype(np.uint8)
        bar = np.repeat(hues, int(np.ceil(w / 8)))[:w]
        hsv = np.zeros((h, w, 3), np.uint8)
        hsv[..., 0] = bar[None, :]
        hsv[..., 1] = 200
        hsv[..., 2] = 230
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    def read(self):
        """Newest frame grabbed so far; never blocks on the camera."""
        with self._lock:
            if self._latest is not None:
                return self._latest
        return self._bars

    def wait_ready(self, timeout=5.0):
        """Block until the first frame lands, so the window opens on real video."""
        deadline = time.perf_counter() + timeout
        while self.cap is not None and time.perf_counter() < deadline:
            with self._lock:
                if self._latest is not None:
                    return True
            time.sleep(0.02)
        return self.cap is None

    def release(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()


HELP = """  a / d   scrub the portal closed / open      space  auto open-close
  f       toggle fullscreen                    q      quit

With --ring or --replay the gesture drives it instead: counter-clockwise
opens, clockwise closes, and a hand that stops leaves it where it is."""


def open_source(args):
    """Where openness comes from: the ring, a capture, or the keyboard."""
    if args.ring and args.replay:
        raise SystemExit("error: pass --ring or --replay, not both")
    if args.ring:
        from .ring import RingSource
        print("waiting for the ring...")
        return RingSource(
            on_event=lambda st: print(f"  portal {st}", flush=True)).start()
    if args.replay:
        from .ring import ReplaySource
        print(f"replaying {args.replay} at {args.replay_speed}x")
        return ReplaySource(args.replay, speed=args.replay_speed,
                            loop=True).start()
    return None


def run(args):
    clip = PortalClip(find_clip(args.clip), fill=args.fill, floor=args.black_floor)
    height, width = clip.shape
    sections = Sections(open_end=args.open_end, loop_start=args.loop_start,
                        loop_end=args.loop_end, shrink_start=args.shrink_start,
                        close_end=min(args.close_end, len(clip) - 1))
    playhead = Playhead(sections, close_speed=args.close_speed,
                        open_speed=args.open_speed,
                        smooth_tau=args.open_smoothing)
    clip.build_seam(sections, args.seam_frames)
    if args.cache_mb > 0:
        clip.warm(range(sections.loop_start, sections.loop_end + 1),
                  args.feather, args.cache_mb)
    camera = Camera(-1 if args.no_camera else camera_source(args.camera),
                    width, height, dshow=args.dshow)
    if not camera.wait_ready():
        print("warning: camera opened but sent no frames; using colour bars",
              file=sys.stderr)

    window = "portal"
    # GUI_NORMAL keeps OpenCV from adding its own toolbar and status bar.
    cv2.namedWindow(window, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL)
    cv2.resizeWindow(window, width // 2, height // 2)

    # Move first, fullscreen second. The other order fullscreens on whichever
    # display the window happened to open on, and the move is then ignored.
    target = choose_display(list_displays(), args.display)
    if args.x is not None:
        cv2.moveWindow(window, args.x, args.y or 0)
    elif target is not None and args.display:
        cv2.moveWindow(window, target[0], target[1])
        print(f"display {args.display}: {target[2]}x{target[3]} at "
              f"({target[0]}, {target[1]})")
    if args.fullscreen:
        cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN,
                              cv2.WINDOW_FULLSCREEN)

    source = open_source(args)
    print(f"\nopening 0..{sections.open_end}   sustain loop "
          f"{sections.loop_start}..{sections.loop_end}   closing to "
          f"{sections.close_end} at {args.close_speed}x\n{HELP}\n")
    openness, auto, fullscreen = 0.0, 0, args.fullscreen
    frame_time = 1.0 / args.fps if args.fps > 0 else 0.0
    last, fps = time.perf_counter(), 0.0

    while True:
        if source is not None:
            openness = source.openness
        elif auto:
            openness = float(np.clip(openness + auto * args.rate, 0.0, 1.0))
            if openness in (0.0, 1.0):
                auto = 0

        now = time.perf_counter()
        dt = min(now - last, 0.25)      # a long stall must not jump the playhead
        last = now
        fps = 0.9 * fps + 0.1 / max(dt, 1e-6)

        index = playhead.update(openness, dt)
        alpha = playhead.alpha
        seam = playhead.seam_index(args.seam_frames)
        out = clip.seam_frame(seam) if seam is not None else clip.frame(index)
        bounds = clip.bounds(index, args.feather)
        if bounds is not None and alpha > 0.0:
            feed = camera.read()
            if args.mirror:
                feed = mirror(feed)
            out = composite_into(out, cover_crop(feed, width, height),
                                 clip.mask(index, args.feather), bounds,
                                 alpha=alpha)

        if args.stats:
            cv2.putText(out, f"{playhead.state:8s} openness {openness:.2f}  "
                             f"frame {index:3d}  {fps:4.1f}fps",
                        (30, height - 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        (255, 255, 255), 2)
            if source is not None:
                cv2.putText(out, source.status, (30, height - 88),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (180, 220, 255), 2)
        cv2.imshow(window, out)

        # Uncapped by default. The playhead runs on the clock, so drawing
        # more frames does not speed the animation up -- it just draws it more
        # smoothly. Capping actively cost frames here: Windows rounds a sleep
        # up to the next ~15.6ms tick, so asking for 20ms gave 31, holding the
        # loop near 19fps against a 24fps target. Uncapped it manages 40.
        if frame_time:
            spare = frame_time - (time.perf_counter() - now)
            key = cv2.waitKey(max(1, int(spare * 1000)))
        else:
            key = cv2.waitKey(1)
        key &= 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("a"):
            openness, auto = max(0.0, openness - args.rate * 3), 0
        elif key == ord("d"):
            openness, auto = min(1.0, openness + args.rate * 3), 0
        elif key == ord(" "):
            auto = -1 if playhead.state in (SUSTAIN, CLOSING) else 1
        elif key == ord("f"):
            fullscreen = not fullscreen
            cv2.setWindowProperty(
                window, cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)

    if source is not None:
        source.stop()
    camera.release()
    cv2.destroyAllWindows()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Portal preview: camera feed inside the ring, ring light on top.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=HELP)
    ap.add_argument("--clip", help="portal clip (default: the one in assets/)")
    ap.add_argument("--ring", action="store_true",
                    help="drive openness from the ring over BLE: "
                         "counter-clockwise opens, clockwise closes")
    ap.add_argument("--replay",
                    help="drive openness from a recorded capture instead of "
                         "the ring, e.g. ccw_short.csv")
    ap.add_argument("--replay-speed", type=float, default=1.0,
                    help="replay rate as a multiple of real time (default 1)")
    ap.add_argument("--camera", default="0",
                    help="camera index (default 0), or a stream URL such as "
                         "http://<phone-ip>:8080/video from an IP-webcam app, "
                         "or a video file to use as the destination")
    ap.add_argument("--no-camera", action="store_true",
                    help="use colour bars instead of a camera")
    ap.add_argument("--dshow", action="store_true",
                    help="force the DirectShow backend (much slower here, "
                         "but a fallback if the default misbehaves)")
    ap.add_argument("--fill", type=float, default=0.98,
                    help="how far the feed reaches toward the rim (default 0.98)")
    ap.add_argument("--feather", type=int, default=81,
                    help="softness of the feed's edge, in pixels (default 81)")
    ap.add_argument("--black-floor", type=int, default=BLACK_FLOOR,
                    help=f"black level subtracted from the clip "
                         f"(default {BLACK_FLOOR}; raise if the projector "
                         f"still shows a lit rectangle)")
    ap.add_argument("--open-end", type=int, default=Sections.open_end,
                    help=f"last frame of the opening arc "
                         f"(default {Sections.open_end})")
    ap.add_argument("--loop-start", type=int, default=Sections.loop_start,
                    help=f"first frame of the sustain loop "
                         f"(default {Sections.loop_start})")
    ap.add_argument("--loop-end", type=int, default=Sections.loop_end,
                    help=f"last frame of the sustain loop, which jumps back "
                         f"to --loop-start (default {Sections.loop_end})")
    ap.add_argument("--close-end", type=int, default=Sections.close_end,
                    help=f"last frame of the closing animation "
                         f"(default {Sections.close_end})")
    ap.add_argument("--cache-mb", type=int, default=600,
                    help="memory for preloaded sustain frames; 0 disables. "
                         "Cuts frame time from 19.5ms to about 5ms, which "
                         "tightens how closely the sparks track your hand "
                         "(default 600)")
    ap.add_argument("--seam-frames", type=int, default=8,
                    help="frames over which the glow eases across the loop "
                         "seam; 0 disables softening (default 8)")
    ap.add_argument("--close-speed", type=float, default=2.5,
                    help="how much faster than the clip the close plays "
                         "(default 2.5)")
    ap.add_argument("--shrink-start", type=int, default=Sections.shrink_start,
                    help=f"frame where the ring actually starts shrinking; "
                         f"closing jumps straight here rather than playing "
                         f"the static frames before it "
                         f"(default {Sections.shrink_start})")
    ap.add_argument("--open-smoothing", type=float, default=0.05,
                    help="seconds of smoothing on the opening scrub, so it "
                         "draws at the render rate rather than at the rate "
                         "openness arrives; 0 disables (default 0.05)")
    ap.add_argument("--open-speed", type=float, default=1.0,
                    help="cap on how fast the opening may draw, as a multiple "
                         "of the clip's own rate. 1.0 keeps the spark trace at "
                         "the speed it was animated (default 1)")
    ap.add_argument("--rate", type=float, default=0.02,
                    help="openness change per frame when animating (default 0.02)")
    ap.add_argument("--fps", type=float, default=0.0,
                    help="cap the frame rate; 0 means uncapped (the default). "
                         "The animation runs on the clock either way, so a cap "
                         "only makes it choppier")
    ap.add_argument("--fullscreen", action="store_true", help="start fullscreen")
    ap.add_argument("--list-displays", action="store_true",
                    help="print the attached monitors and their indices, "
                         "then exit")
    ap.add_argument("--display", type=int, default=0,
                    help="which monitor to open on, 0 being the primary. Use "
                         "with --fullscreen to fill a projector")
    ap.add_argument("--x", type=int, default=None,
                    help="explicit window x, if --display picks wrong")
    ap.add_argument("--y", type=int, default=None, help="explicit window y")
    ap.add_argument("--no-mirror", dest="mirror", action="store_false",
                    help="do not flip the camera feed left to right")
    ap.set_defaults(mirror=True)
    ap.add_argument("--stats", action="store_true", help="overlay openness and fps")
    args = ap.parse_args(argv)
    if args.list_displays:
        monitors = list_displays()
        if not monitors:
            print("no displays detected")
        for i, (x, y, w, h) in enumerate(monitors):
            primary = " (primary)" if (x, y) == (0, 0) else ""
            print(f"  --display {i}   {w}x{h} at ({x}, {y}){primary}")
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
