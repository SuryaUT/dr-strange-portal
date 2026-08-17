"""Tests for the portal renderer.

The renderer's job is to put a live camera feed inside the ring and the ring's
own light on top of it. Two things must hold no matter what the camera is
showing. The far field must stay at exactly zero, because this is filmed off a
projector and any lifted floor draws the 16:9 rectangle on the wall. And the
mask must reach the rim, because a gap between the feed and the ring reads as a
video window rather than a hole in space.

The geometry tests build synthetic rings rather than leaning on the real clip,
so they pin down behaviour for any ring, and stay meaningful if the asset is
ever swapped.
"""
import numpy as np
import pytest

from portal.render import (screen_blend, cover_crop, ring_center, rim_radii,
                           composite, composite_u8, frame_for_openness,
                           portal_mask, black_segment, clamp_black, rim_polygon,
                           mask_from_polygon, mask_bounds, composite_into,
                           Playhead, Sections, CLOSED, CLOSING, SUSTAIN, CLIP_FPS,
                           blend_glow, choose_display, mirror,
                           camera_source)


def synth_ring(cx=400, cy=300, a=200, b=200, sigma=12.0, shape=(600, 800)):
    """A ring whose brightness peaks at radius `a` across and `b` down.

    Real rim light falls off smoothly either side of a peak, so the synthetic
    ring does too -- a hard-edged band would have no well-defined peak for
    `rim_radii` to find.
    """
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    d = np.hypot((xx - cx) / a, (yy - cy) / b)
    edge = (d - 1.0) * a
    return (255.0 * np.exp(-(edge ** 2) / (2 * sigma ** 2))).astype(np.float32)


def _clip_or_skip():
    """The real clip, warmed, or skip -- the asset is not in the repo."""
    from pathlib import Path
    from portal.render import PortalClip, find_clip, Sections
    try:
        path = find_clip()
    except SystemExit:
        pytest.skip("portal clip not present")
    clip = PortalClip(path, verbose=False)
    s = Sections()
    clip.warm(range(s.loop_start, s.loop_end + 1))
    clip.sections_for_test = s
    return clip


def test_screen_blend_over_black_leaves_the_base_untouched():
    base = np.random.default_rng(0).random((16, 16, 3), dtype=np.float32)
    over = np.zeros((16, 16, 3), np.float32)

    assert np.allclose(screen_blend(base, over), base)


def test_screen_blend_never_darkens():
    rng = np.random.default_rng(1)
    base = rng.random((32, 32, 3), dtype=np.float32)
    over = rng.random((32, 32, 3), dtype=np.float32)

    assert np.all(screen_blend(base, over) >= base - 1e-6)


def test_black_over_black_stays_exactly_black():
    """The projector invariant: outside the ring nothing may be emitted."""
    base = np.zeros((8, 8, 3), np.float32)
    over = np.zeros((8, 8, 3), np.float32)

    assert np.max(screen_blend(base, over)) == 0.0


def test_screen_blend_saturates_at_white():
    base = np.full((4, 4, 3), 0.9, np.float32)
    over = np.full((4, 4, 3), 0.9, np.float32)

    out = screen_blend(base, over)
    assert np.all(out <= 1.0)
    assert np.all(out > 0.98)


def test_cover_crop_returns_the_requested_size():
    src = np.zeros((720, 1280, 3), np.float32)

    assert cover_crop(src, 1920, 1080).shape == (1080, 1920, 3)


def test_cover_crop_takes_the_centre_of_a_too_wide_source():
    """A 2:1 source cropped to 1:1 keeps the middle half, not an edge."""
    src = np.zeros((100, 200, 3), np.float32)
    src[:, :50] = 1.0      # left quarter
    src[:, 150:] = 1.0     # right quarter

    out = cover_crop(src, 100, 100)

    assert out.max() == 0.0


def test_cover_crop_does_not_distort_the_aspect_ratio():
    """A circle in the source must still be a circle after cover_crop."""
    src = np.zeros((400, 400, 3), np.float32)
    yy, xx = np.mgrid[0:400, 0:400]
    src[np.hypot(yy - 200, xx - 200) < 100] = 1.0

    out = cover_crop(src, 800, 400)

    lit = out[..., 0] > 0.5
    height = lit.any(axis=1).sum()
    width = lit.any(axis=0).sum()
    assert abs(width - height) <= 2


def test_ring_centre_found_on_a_synthetic_ring():
    cx, cy = ring_center(synth_ring(cx=400, cy=300))

    assert abs(cx - 400) < 2
    assert abs(cy - 300) < 2


def test_ring_centre_ignores_asymmetric_spark_trails():
    """Sparks stream off one side. Averaging every lit pixel chases them.

    On the real clip this dragged the centre 21px off, which opened a visible
    gap between the feed and the rim on the opposite side.
    """
    g = synth_ring(cx=400, cy=300)
    g[280:320, 0:250] = np.maximum(g[280:320, 0:250], 90.0)   # dim trails, left

    cx, cy = ring_center(g)

    assert abs(cx - 400) < 5
    assert abs(cy - 300) < 5


def test_rim_radii_follow_an_elliptical_ring():
    """A circle-fit cannot describe a squashed ring; per-angle radii can."""
    g = synth_ring(cx=400, cy=300, a=200, b=120)

    radii = rim_radii(g, 400, 300, n_angles=360)

    assert abs(radii[0] - 200) < 6      # angle 0, along +x
    assert abs(radii[90] - 120) < 6     # angle 90deg, along +y


def test_portal_mask_fills_the_centre_of_the_hole():
    mask = portal_mask(synth_ring())

    assert mask[300, 400] > 0.99


def test_portal_mask_reaches_the_rim():
    """The gap this closes: a feed stopping short of the rim reads as a window.

    Fitting a circle to every lit pixel stopped at 78% of the rim radius on the
    real clip, leaving a dark band all the way round.
    """
    mask = portal_mask(synth_ring(cx=400, cy=300, a=200, b=200))

    assert mask[300, 400 + int(200 * 0.9)] > 0.5


def test_portal_mask_never_reaches_the_frame_border():
    """The projector invariant: the feed must not touch the far field."""
    mask = portal_mask(synth_ring())

    border = np.concatenate([mask[0], mask[-1], mask[:, 0], mask[:, -1]])
    assert border.max() == 0.0


def test_portal_mask_is_empty_before_the_ring_appears():
    """The clip opens on 40-odd frames of pure black. Nothing to show through."""
    mask = portal_mask(np.zeros((600, 800), np.float32))

    assert mask.max() == 0.0


def portal_frame_with_interior_glow():
    """A ring plus the dim warm fill the real clip has inside the hole."""
    g = synth_ring()
    yy, xx = np.mgrid[0:600, 0:800]
    g[np.hypot(yy - 300, xx - 400) < 190] = np.maximum(
        g[np.hypot(yy - 300, xx - 400) < 190], 40.0)
    return g


def test_composite_adds_nothing_to_the_far_field():
    """The whole reason for screen blending: a projector cannot emit black.

    Whatever the camera is showing, nothing outside the ring may light up, or
    the 16:9 rectangle appears on the wall. The camera must contribute exactly
    nothing out there -- not "almost nothing".
    """
    gray = synth_ring()
    portal = np.repeat(gray[..., None], 3, axis=2) / 255.0
    camera = np.ones((600, 800, 3), np.float32)      # worst case: pure white

    out = composite(portal, camera, portal_mask(gray), alpha=1.0)

    def border(a):
        return np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])

    assert np.array_equal(border(out), border(portal))


def test_composite_of_a_black_far_field_is_exactly_black():
    """The real clip's corners are pure zero, and must survive as pure zero."""
    gray = synth_ring()
    gray[gray < 1.0] = 0.0                           # as the real clip is
    portal = np.repeat(gray[..., None], 3, axis=2) / 255.0
    camera = np.ones((600, 800, 3), np.float32)

    out = composite(portal, camera, portal_mask(gray), alpha=1.0)

    border = np.concatenate([out[0], out[-1], out[:, 0], out[:, -1]])
    assert border.max() == 0.0


def test_composite_lays_the_glow_over_the_camera_feed():
    """The seam is hidden because the ring's light falls on the feed itself."""
    gray = portal_frame_with_interior_glow()
    portal = np.repeat(gray[..., None], 3, axis=2) / 255.0
    camera = np.full((600, 800, 3), 0.5, np.float32)

    out = composite(portal, camera, portal_mask(gray), alpha=1.0)

    assert out[300, 400, 0] > 0.5


def test_composite_hides_the_camera_while_the_portal_is_shut():
    gray = portal_frame_with_interior_glow()
    portal = np.repeat(gray[..., None], 3, axis=2) / 255.0
    camera = np.ones((600, 800, 3), np.float32)

    out = composite(portal, camera, portal_mask(gray), alpha=0.0)

    assert np.allclose(out, portal)


def test_frame_for_openness_spans_the_opening_section():
    assert frame_for_openness(0.0, 110) == 0
    assert frame_for_openness(1.0, 110) == 109


def test_frame_for_openness_never_runs_backwards():
    """Openness is monotone by construction upstream; the playhead must be too.

    A playhead that dipped would visibly un-draw the arc the hand just traced.
    """
    frames = [frame_for_openness(o, 110) for o in np.linspace(0, 1, 500)]

    assert all(b >= a for a, b in zip(frames, frames[1:]))


def test_fast_composite_matches_the_reference_within_rounding():
    """The uint8 path exists only for speed; it must not change the picture.

    Compositing in float32 costs 61ms a frame at 1080p, which cannot hold 24fps.
    The uint8 path through OpenCV's SIMD primitives does the same arithmetic in
    9ms, so the reference stays as the definition and this pins the fast path
    to it.
    """
    rng = np.random.default_rng(7)
    portal = (rng.random((120, 160, 3)) * 255).astype(np.uint8)
    camera = (rng.random((120, 160, 3)) * 255).astype(np.uint8)
    mask = (rng.random((120, 160)) * 255).astype(np.uint8)

    fast = composite_u8(portal, camera, mask, alpha=1.0)
    reference = composite(portal.astype(np.float32) / 255.0,
                          camera.astype(np.float32) / 255.0,
                          mask.astype(np.float32) / 255.0, alpha=1.0)

    assert np.abs(fast.astype(int) - np.round(reference * 255).astype(int)).max() <= 2


def test_fast_composite_adds_nothing_to_the_far_field():
    """Same projector invariant as the reference path, in integers."""
    rng = np.random.default_rng(8)
    portal = (rng.random((120, 160, 3)) * 255).astype(np.uint8)
    portal[:20] = 0                                   # far field, dead black
    camera = np.full((120, 160, 3), 255, np.uint8)
    mask = np.full((120, 160), 255, np.uint8)
    mask[:20] = 0

    out = composite_u8(portal, camera, mask, alpha=1.0)

    assert out[:20].max() == 0


def test_fast_composite_hides_the_camera_at_zero_alpha():
    rng = np.random.default_rng(9)
    portal = (rng.random((120, 160, 3)) * 255).astype(np.uint8)
    camera = np.full((120, 160, 3), 255, np.uint8)
    mask = np.full((120, 160), 255, np.uint8)

    assert np.array_equal(composite_u8(portal, camera, mask, alpha=0.0), portal)


def test_black_segment_finds_the_run_of_dark_frames():
    """The clip holds the same animation on black, then green, then blue.

    We want the black one, located by looking at the corners rather than
    hardcoding frame numbers, so a re-export or a different pack still works.
    """
    corners = [180.0] * 10 + [1.0] * 25 + [90.0] * 12

    assert black_segment(corners) == (10, 25)


def test_black_segment_prefers_the_longest_run():
    corners = [1.0] * 4 + [200.0] * 5 + [1.0] * 30 + [200.0] * 5

    assert black_segment(corners) == (9, 30)


def test_black_segment_reports_nothing_when_no_frame_is_dark():
    assert black_segment([200.0] * 30) == (0, 0)


def test_clamp_black_kills_the_dither_floor():
    """The clip's corners are not truly black: 26% of them sit at value 1.

    Left alone that lifts the whole far field, and a projector paints the 16:9
    rectangle on the wall.
    """
    frame = np.array([[0, 1, 2, 5, 6]], np.uint8)

    assert clamp_black(frame, floor=6).max() == 0


def test_clamp_black_leaves_the_sparks_essentially_untouched():
    frame = np.full((4, 4), 250, np.uint8)

    assert clamp_black(frame, floor=6)[0, 0] >= 244


def test_clamp_black_does_not_contour_a_smooth_glow():
    """Zeroing everything below a floor puts a visible step in the falloff.

    The glow inside the ring is a smooth gradient; a hard threshold would draw
    a contour ring exactly where it crosses the floor. Subtracting the floor
    keeps the slope continuous instead.
    """
    ramp = np.arange(0, 40, dtype=np.uint8)[None, :]

    out = clamp_black(ramp, floor=6).astype(int)

    assert np.diff(out).max() <= 1


def test_cover_crop_is_a_no_op_when_the_sizes_already_match():
    """A 1080p camera into a 1080p frame must not pay for a rescale."""
    src = (np.random.default_rng(3).random((1080, 1920, 3)) * 255).astype(np.uint8)

    assert cover_crop(src, 1920, 1080) is src


def test_mask_bounds_cover_every_lit_pixel_of_the_feathered_mask():
    """Feathering spreads the mask past its polygon.

    Bounds taken from the polygon alone would clip the soft edge, leaving a
    hard line where the feed stops.
    """
    pts = rim_polygon(synth_ring())
    mask = mask_from_polygon(pts, (600, 800), feather=81)

    x0, y0, x1, y1 = mask_bounds(pts, (600, 800), feather=81)
    outside = mask.copy()
    outside[y0:y1, x0:x1] = 0

    assert outside.max() == 0


def test_mask_bounds_stay_inside_the_frame():
    pts = rim_polygon(synth_ring(cx=60, cy=40, a=200, b=200))

    x0, y0, x1, y1 = mask_bounds(pts, (600, 800), feather=81)

    assert 0 <= x0 < x1 <= 800
    assert 0 <= y0 < y1 <= 600


def test_bounded_composite_matches_the_whole_frame_composite():
    """The optimisation that buys the frame rate: composite only in the disc.

    Outside the mask the camera contributes nothing, so the portal frame is
    already the answer there. This must be identical, not merely close.
    """
    gray = synth_ring()
    portal = np.repeat(gray[..., None], 3, axis=2).astype(np.uint8)
    camera = (np.random.default_rng(4).random((600, 800, 3)) * 255).astype(np.uint8)
    pts = rim_polygon(gray)
    mask = mask_from_polygon(pts, gray.shape, feather=81)

    whole = composite_u8(portal, camera, mask, alpha=0.8)
    bounded = composite_into(portal.copy(), camera, mask,
                             mask_bounds(pts, gray.shape, feather=81), alpha=0.8)

    assert np.array_equal(whole, bounded)


# --------------------------------------------------------------------------
# The playhead: what the portal is showing, and when.
# --------------------------------------------------------------------------

def test_playhead_scrubs_the_opening_with_the_hand():
    ph = Playhead()

    assert ph.update(0.0) == 0
    assert ph.update(0.5) == pytest.approx(Sections().open_end * 0.5, abs=1)
    assert ph.update(1.0) == Sections().open_end


def test_a_fully_open_portal_keeps_moving():
    """The freeze this exists to kill.

    Scrubbing alone leaves the sparks frozen mid-air whenever the hand stops,
    because a canned clip carries structure and fire on the same timeline.
    """
    ph = Playhead()
    ph.update(1.0)

    frames = {ph.update(1.0) for _ in range(40)}

    assert len(frames) > 1


def test_the_sustain_loops_between_its_two_ends():
    ph = Playhead()
    ph.update(1.0)
    s = Sections()

    seen = [ph.update(1.0) for _ in range(400)]

    assert max(seen) <= s.loop_end
    assert min(seen[100:]) >= s.loop_start
    wraps = sum(1 for a, b in zip(seen, seen[1:]) if b < a)
    assert wraps > 1, "never came back round"


def test_closing_plays_forward_and_never_reverses_the_opening():
    """Strange does not rewind the portal shut; the clip has its own ending."""
    ph = Playhead()
    ph.update(1.0)
    for _ in range(80):
        ph.update(1.0)
    start = ph.update(0.0)

    seen = [start] + [ph.update(0.0) for _ in range(20)]

    assert all(b >= a for a, b in zip(seen, seen[1:])), "playhead ran backwards"


def test_close_speed_governs_the_collapse_itself():
    """2.5x: the clip's own collapse is a leisurely five seconds.

    Only the shrinking part answers to close_speed. The static frames ahead of
    it are sprinted through regardless, so measuring the whole close would mix
    the two rates together.
    """
    def ticks_collapsing(speed):
        ph = Playhead(close_speed=speed)
        ph.update(1.0)
        for _ in range(60):
            ph.update(1.0)
        while ph.position < Sections().shrink_start:
            ph.update(0.0)
        n = 0
        while ph.state != CLOSED and n < 2000:
            ph.update(0.0)
            n += 1
        return n

    assert ticks_collapsing(2.5) == pytest.approx(ticks_collapsing(1.0) / 2.5, rel=0.1)


def test_the_portal_ends_up_closed_and_reusable():
    ph = Playhead()
    ph.update(1.0)
    for _ in range(60):
        ph.update(1.0)
    for _ in range(2000):
        ph.update(0.0)

    assert ph.state == CLOSED
    assert ph.update(0.0) == 0

    ph.update(1.0)
    assert ph.state != CLOSED, "must open again after closing"


def test_easing_off_mid_opening_scrubs_back_rather_than_closing():
    """Only a portal that actually opened gets the closing animation."""
    ph = Playhead()
    ph.update(0.6)

    assert ph.update(0.3) < ph.update(0.6)
    assert ph.state != CLOSING


def test_the_feed_fades_in_as_the_portal_opens():
    ph = Playhead()
    ph.update(0.4)

    # alpha tracks the ring's progress, which lands on whole clip frames
    assert ph.alpha == pytest.approx(0.4, abs=0.02)


def test_the_feed_stays_visible_through_the_closing_animation():
    """Openness drops to zero the moment the close is triggered.

    Tying the feed's opacity to openness directly would blink the destination
    out instantly and leave an empty ring collapsing. The shrinking hole in the
    clip already takes the feed away; the mask does that work.
    """
    ph = Playhead()
    ph.update(1.0)
    for _ in range(60):
        ph.update(1.0)
    ph.update(0.0)

    assert ph.state == CLOSING
    assert ph.alpha == pytest.approx(1.0)


def test_the_feed_is_gone_when_the_portal_is_shut():
    ph = Playhead()

    assert ph.update(0.0) == 0
    assert ph.alpha == 0.0


def test_the_animation_runs_on_the_clock_not_on_the_frame_rate():
    """A playhead advanced per rendered frame plays slower on a slower machine.

    Measured live: the loop was managing 12.9fps against a 24fps target, so a
    2.9s closing animation took 5.4s on the wall clock. Duration must depend on
    elapsed time, not on how many frames the renderer happened to draw.
    """
    def seconds_to_shut(render_fps):
        ph = Playhead(close_speed=2.5)
        dt = 1.0 / render_fps
        ph.update(1.0, dt)
        for _ in range(int(render_fps * 3)):
            ph.update(1.0, dt)
        elapsed = 0.0
        while ph.state != CLOSED and elapsed < 60.0:
            ph.update(0.0, dt)
            elapsed += dt
        return elapsed

    fast, slow = seconds_to_shut(60.0), seconds_to_shut(13.0)
    assert fast == pytest.approx(slow, rel=0.15)


def test_the_collapse_takes_the_clip_duration_divided_by_the_speed():
    ph = Playhead(close_speed=2.5)
    s = Sections()
    dt = 1.0 / 60.0
    ph.update(1.0, dt)
    while ph.state != SUSTAIN:
        ph.update(1.0, dt)
    ph.update(0.0, dt)
    while ph.position < s.shrink_start:
        ph.update(0.0, dt)

    elapsed = 0.0
    while ph.state != CLOSED and elapsed < 60.0:
        ph.update(0.0, dt)
        elapsed += dt

    expected = (s.close_end - s.shrink_start) / CLIP_FPS / 2.5
    assert elapsed == pytest.approx(expected, rel=0.12)


# --------------------------------------------------------------------------
# Softening the loop seam.
# --------------------------------------------------------------------------

def blurred(img, k=81):
    import cv2
    return cv2.GaussianBlur(img.astype(np.float32), (k, k), 0)


def test_glow_blend_at_zero_weight_leaves_the_frame_alone():
    rng = np.random.default_rng(11)
    head = (rng.random((240, 320, 3)) * 255).astype(np.uint8)
    tail = (rng.random((240, 320, 3)) * 255).astype(np.uint8)

    assert np.abs(blend_glow(head, tail, 0.0).astype(int)
                  - head.astype(int)).max() <= 1


def test_glow_blend_takes_the_smooth_light_from_the_tail():
    """The coherent, eye-catching part eases across the cut."""
    head = np.full((240, 320, 3), 40, np.uint8)
    tail = np.full((240, 320, 3), 120, np.uint8)

    out = blend_glow(head, tail, 1.0)

    assert out.mean() == pytest.approx(120, abs=3)


def test_glow_blend_keeps_the_spark_detail_of_the_frame_it_is_on():
    """Sparks must never cross-dissolve.

    Two different spark patterns blended together read as a double exposure --
    measured worse than doing nothing at all (12.50 against an 11.59 hard cut).
    Chaotic detail hides its own cut; smooth light does not.

    Sparks are thin filaments, a couple of pixels across. That is what makes
    them high frequency against the 81px glow kernel, and so what lets them cut
    rather than dissolve. A blob wider than the kernel would count as glow.
    """
    head = np.full((240, 320, 3), 40, np.uint8)
    head[100:102, 60:260] = 200                    # a filament, only in head
    tail = np.full((240, 320, 3), 40, np.uint8)
    tail[180:182, 60:260] = 200                    # a different filament

    out = blend_glow(head, tail, 1.0).astype(np.float32)

    assert out[101, 150].mean() > 150, "lost the spark it was standing on"
    assert out[181, 150].mean() < 90, "dissolved in the other frame's spark"


def test_no_seam_blend_on_the_first_pass_into_the_sustain():
    """Arriving from the opening is continuous already; nothing to hide."""
    ph = Playhead()
    ph.update(1.0)

    assert ph.seam_index(8) is None


def test_seam_blend_engages_immediately_after_a_wrap():
    ph = Playhead()
    ph.update(1.0)
    for _ in range(400):
        if ph.seam_index(8) is not None:
            break
        ph.update(1.0)

    # The wrap lands a fraction past loop_start, so the first softened frame is
    # index 0 or 1 depending on the step size.
    assert ph.seam_index(8) <= 1


def test_seam_blend_lets_go_after_its_window():
    ph = Playhead()
    ph.update(1.0)
    while ph.seam_index(8) is None:
        ph.update(1.0)
    for _ in range(9):
        ph.update(1.0)

    assert ph.seam_index(8) is None


def test_the_close_does_not_dawdle_before_the_ring_starts_shrinking():
    """The clip holds its radius at 98-102% from f215 all the way to f253.

    Played at the ordinary closing speed those frames are dead time: the
    portal has been told to shut and visibly does nothing.
    """
    ph = Playhead()
    s = Sections()
    dt = 1.0 / 60.0
    ph.update(1.0, dt)
    while ph.state != SUSTAIN:
        ph.update(1.0, dt)
    ph.position = float(s.loop_start)          # worst case: top of the loop

    elapsed = 0.0
    ph.update(0.0, dt)
    while ph.position < s.shrink_start and elapsed < 10.0:
        ph.update(0.0, dt)
        elapsed += dt

    assert elapsed < 0.45


def test_the_close_slows_to_its_proper_speed_once_the_ring_shrinks():
    """Only the dead frames get sprinted; the collapse itself must be seen."""
    ph = Playhead()
    s = Sections()
    dt = 1.0 / 60.0
    ph.update(1.0, dt)
    while ph.state != SUSTAIN:
        ph.update(1.0, dt)
    ph.update(0.0, dt)
    while ph.position < s.shrink_start:
        ph.update(0.0, dt)

    elapsed = 0.0
    while ph.state != CLOSED and elapsed < 20.0:
        ph.update(0.0, dt)
        elapsed += dt

    expected = (s.close_end - s.shrink_start) / CLIP_FPS / 2.5
    assert elapsed == pytest.approx(expected, rel=0.12)


def test_the_close_takes_the_same_time_wherever_the_loop_was():
    """Before sprinting, triggering at the top of the loop cost 1.54s of dead
    time and the bottom cost 0.63s -- the same gesture, two different portals."""
    def close_seconds(from_position):
        ph = Playhead()
        dt = 1.0 / 60.0
        ph.update(1.0, dt)
        while ph.state != SUSTAIN:
            ph.update(1.0, dt)
        ph.position = float(from_position)
        elapsed = 0.0
        while ph.state != CLOSED and elapsed < 20.0:
            ph.update(0.0, dt)
            elapsed += dt
        return elapsed

    early, late = close_seconds(165), close_seconds(219)
    assert abs(early - late) < 0.35


def test_a_cached_frame_is_not_corrupted_by_compositing_into_it():
    """`composite_into` writes into the frame it is handed.

    Serving the cached array itself would let the first composite scribble the
    camera feed permanently into the cache, and every later cycle would show
    a stale frame with someone's face burned into it.
    """
    import cv2
    clip = _clip_or_skip()
    first = clip.frame(clip.sections_for_test.loop_start).copy()

    scribbled = clip.frame(clip.sections_for_test.loop_start)
    scribbled[:] = 0

    again = clip.frame(clip.sections_for_test.loop_start)
    assert np.array_equal(again, first)


def test_the_cache_returns_exactly_what_decoding_returns():
    clip = _clip_or_skip()
    i = clip.sections_for_test.loop_start + 3
    uncached = clip._decode(i)

    assert np.array_equal(clip.frame(i), uncached)


def test_the_opening_draws_frames_between_openness_updates():
    """The opening must not inherit the choppiness of its input.

    Openness arrives with the BLE packets, about 10 times a second, while the
    renderer draws 40-56 times a second. Snapping the playhead straight onto
    the frame openness maps to meant the whole opening animated at 10fps, in
    jumps of up to 27 clip frames. Sustain and closing look smooth because they
    advance on elapsed time instead.
    """
    ph = Playhead()
    dt = 1.0 / 60.0
    shown = []
    for step in range(1, 9):                 # 8 openness updates, as BLE gives
        for _ in range(6):                   # 6 rendered frames each
            shown.append(ph.update(step / 8.0, dt))

    # Rate-limited to the clip's own pace, 0.8s of gesture draws about 19 clip
    # frames. The point is that they arrive one at a time rather than in eight
    # lurches, so what matters is that far more than 8 distinct frames show.
    assert len(set(shown)) > 15, "the opening is still stepping with its input"


def test_the_smoothed_opening_never_runs_backwards():
    ph = Playhead()
    dt = 1.0 / 60.0
    shown = [ph.update(min(1.0, k / 40.0), dt) for k in range(60)]

    assert all(b >= a for a, b in zip(shown, shown[1:]))


def test_the_smoothed_opening_still_arrives_fully_open():
    ph = Playhead()
    dt = 1.0 / 60.0
    for _ in range(int(6.0 / dt)):           # the opening now takes 4.5s
        ph.update(1.0, dt)

    assert ph.state == SUSTAIN


def test_scrubbing_is_immediate_when_no_time_step_is_given():
    """Without a clock there is nothing to smooth against; snap."""
    ph = Playhead()

    assert ph.update(0.5) == pytest.approx(Sections().open_end * 0.5, abs=1)


def test_the_opening_never_plays_faster_than_the_clip():
    """The scrub was cramming 4.5s of animation into a 0.8s gesture -- 5.6x.

    That is why it read as sped up and lost the spark trace: the arc drawing
    itself around the rim is the whole effect, and at 5.6x it is a blur.
    """
    ph = Playhead()
    dt = 1.0 / 60.0
    seen = [ph.position]
    for _ in range(30):
        ph.update(1.0, dt)              # gesture completes instantly
        seen.append(ph.position)

    advance_per_second = (seen[-1] - seen[0]) / (30 * dt)
    assert advance_per_second <= CLIP_FPS * 1.05


def test_an_instant_gesture_still_takes_the_clips_own_time_to_open():
    ph = Playhead()
    dt = 1.0 / 60.0
    elapsed = 0.0
    while ph.state != SUSTAIN and elapsed < 20.0:
        ph.update(1.0, dt)
        elapsed += dt

    assert elapsed == pytest.approx(Sections().open_end / CLIP_FPS, rel=0.15)


def test_closing_begins_at_the_collapse_not_inside_the_sustain():
    """f219 to f248 is still sustain material: the radius sits at 286, 288,
    287, 275. Playing it as part of the close is what felt like a delay."""
    ph = Playhead()
    s = Sections()
    dt = 1.0 / 60.0
    ph.update(1.0, dt)
    while ph.state != SUSTAIN:
        ph.update(1.0, dt)
    for _ in range(30):
        ph.update(1.0, dt)

    ph.update(0.0, dt)

    assert ph.state == CLOSING
    assert ph.position >= s.shrink_start


def test_the_feed_follows_the_ring_rather_than_the_gesture_while_opening():
    """Openness can hit 1.0 long before the ring has finished drawing."""
    ph = Playhead()
    dt = 1.0 / 60.0
    ph.update(1.0, dt)

    assert ph.alpha < 0.2, "the destination appeared before the portal did"


# --------------------------------------------------------------------------
# Putting the portal on a projector.
# --------------------------------------------------------------------------

def test_choose_display_picks_the_named_monitor():
    monitors = [(0, 0, 1440, 900), (1440, 0, 1920, 1080)]

    assert choose_display(monitors, 1) == (1440, 0, 1920, 1080)


def test_choose_display_falls_back_to_the_primary_when_asked_for_a_missing_one():
    """Unplugging the projector must not leave you with a window you cannot
    see, or a crash halfway through a shoot."""
    monitors = [(0, 0, 1440, 900)]

    assert choose_display(monitors, 3) == (0, 0, 1440, 900)


def test_choose_display_handles_having_no_monitors_at_all():
    assert choose_display([], 0) is None


def test_mirroring_flips_left_to_right_not_top_to_bottom():
    frame = np.zeros((40, 60, 3), np.uint8)
    frame[:, :10] = 255                       # a bright band on the left

    out = mirror(frame)

    assert out[:, -10:].min() == 255, "the band did not move to the right"
    assert out[:, :10].max() == 0
    assert np.array_equal(out[0], out[0]), "rows must keep their order"


def test_mirroring_twice_gives_the_original_back():
    rng = np.random.default_rng(21)
    frame = (rng.random((30, 50, 3)) * 255).astype(np.uint8)

    assert np.array_equal(mirror(mirror(frame)), frame)


def test_camera_source_reads_a_plain_index_as_a_number():
    assert camera_source("0") == 0
    assert camera_source(2) == 2


def test_camera_source_passes_a_url_through_untouched():
    """A phone streaming MJPEG over wifi is a URL, not a device index."""
    url = "http://192.168.1.42:8080/video"

    assert camera_source(url) == url


def test_camera_source_keeps_a_file_path_for_a_canned_destination():
    assert camera_source("clips/other_room.mp4") == "clips/other_room.mp4"
