"""Split-view composition shared by the CPU reference and the GPU presenter.

Prepared ``before`` and ``after`` frames are uploaded to the GPU once. Each repaint
is then described as whole-height column copies from those two textures plus a
narrow divider, so dragging the divider costs a few kilobytes of CPU work instead
of copying and uploading a full FP16 frame.
"""

import numpy as np

from ..color import srgb_to_linear

DIVIDER_SRGB = np.array([152, 223, 164])


def divider_color(sdr_white_nits: float) -> np.ndarray:
    return srgb_to_linear(DIVIDER_SRGB / 255) * sdr_white_nits / 80


def composition_plan(mode, width, split, top, image_height, line_width):
    """Return ``(copies, divider)``.

    ``copies`` is a list of ``(source, left, right)`` column ranges that together
    cover ``0..width`` exactly once (source 0 = before, 1 = after). ``divider`` is
    ``(x, y, w, h)`` or ``None``.
    """
    if mode == "after":
        return [(1, 0, width)], None
    if mode == "before":
        return [(0, 0, width)], None
    boundary = min(width - 1, max(0, round(width * split)))
    copies = [(s, a, b) for s, a, b in ((0, 0, boundary), (1, boundary, width)) if b > a]
    line = min(line_width, width - boundary)
    divider = (boundary, top, line, image_height) if image_height > 0 and line > 0 else None
    return copies, divider


def render_region(sources, copies, divider, color, x, y, width, height):
    """CPU composition of one rectangle of the frame (reference and overlay base)."""
    patch = np.empty((height, width, 4), np.float16)
    for source, left, right in copies:
        a, b = max(left, x), min(right, x + width)
        if a < b:
            patch[:, a - x : b - x] = sources[source][y : y + height, a:b]
    if divider is not None:
        dx, dy, dw, dh = divider
        a, b = max(dx, x), min(dx + dw, x + width)
        top, bottom = max(dy, y), min(dy + dh, y + height)
        if a < b and top < bottom:
            patch[top - y : bottom - y, a - x : b - x, :3] = color
    return patch


def present_plan(renderer, width, copies, divider, color):
    """Issue the plan as GPU copies plus one small divider upload."""
    for source, left, right in copies:
        if left == 0 and right == width:
            renderer.copy_full(source)
        else:
            renderer.copy_region(source, left, right)
    if divider is not None:
        x, y, w, h = divider
        line = np.empty((h, w, 4), np.float16)
        line[..., :3] = color
        line[..., 3] = 1
        renderer.upload_region(x, y, line)
