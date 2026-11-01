"""GPU-side split composition must match the original CPU frame exactly."""

import numpy as np
import pytest

from rtx_hdr_studio.color import srgb_to_linear
from rtx_hdr_studio.graphics.directx import DirectXError, check
from rtx_hdr_studio.ui.composition import (
    composition_plan,
    divider_color,
    present_plan,
    render_region,
)


def reference_compose(before, after, mode, split, y, ih, ratio, white):
    """The 1.2.0 HdrSurface.compose implementation (full-frame CPU copy)."""
    width = before.shape[1]
    if mode == "after":
        return after
    if mode == "before":
        return before
    boundary = min(width - 1, max(0, round(width * split)))
    frame = before.copy()
    frame[:, boundary:] = after[:, boundary:]
    color = srgb_to_linear(np.array([152, 223, 164]) / 255) * white / 80
    frame[y : y + ih, boundary : boundary + max(1, round(ratio)), :3] = color
    return frame


class FakeRenderer:
    """Applies Presenter operations to a NumPy backbuffer."""

    def __init__(self, before, after):
        self.sources = (before, after)
        self.buffer = np.full_like(before, np.nan)  # Flip-discard: undefined content.
        self.uploaded = 0

    def copy_full(self, source):
        self.buffer[...] = self.sources[source]

    def copy_region(self, source, left, right):
        self.buffer[:, left:right] = self.sources[source][:, left:right]

    def upload_region(self, x, y, rgba):
        self.buffer[y : y + rgba.shape[0], x : x + rgba.shape[1]] = rgba
        self.uploaded += rgba.size * 2


def frames(height=37, width=61):
    rng = np.random.default_rng(4)
    before = rng.normal(1, 2, (height, width, 4)).astype(np.float16)
    after = rng.normal(5, 3, (height, width, 4)).astype(np.float16)
    before[..., 3] = after[..., 3] = 1
    return before, after


@pytest.mark.parametrize("mode", ["split", "before", "after"])
@pytest.mark.parametrize("split", [0.0, 0.02, 0.37, 0.5, 0.98, 1.0])
@pytest.mark.parametrize("ratio", [1, 1.5, 2])
def test_gpu_plan_reproduces_the_cpu_frame(mode, split, ratio):
    before, after = frames()
    height, width = before.shape[:2]
    white = 240
    line = max(1, round(ratio))
    copies, divider = composition_plan(mode, width, split, 5, 27, line)
    # Copies tile the width exactly once, so the whole flip-discard buffer is redrawn.
    covered = np.zeros(width, int)
    for _, left, right in copies:
        covered[left:right] += 1
    assert (covered == 1).all()
    expected = reference_compose(before, after, mode, split, 5, 27, ratio, white)
    renderer = FakeRenderer(before, after)
    present_plan(renderer, width, copies, divider, divider_color(white))
    np.testing.assert_array_equal(renderer.buffer, expected)
    full = render_region(
        (before, after), copies, divider, divider_color(white), 0, 0, width, height
    )
    np.testing.assert_array_equal(full, expected)
    # Per-repaint CPU upload is the divider only, not the frame.
    assert renderer.uploaded <= 27 * line * 4 * 2


@pytest.mark.parametrize(
    "region", [(0, 0, 61, 37), (20, 3, 30, 10), (55, 30, 6, 7), (28, 0, 4, 37)]
)
def test_overlay_patches_match_the_same_part_of_the_full_frame(region):
    before, after = frames()
    copies, divider = composition_plan("split", 61, 0.5, 5, 27, 2)
    color = divider_color(200)
    full = render_region((before, after), copies, divider, color, 0, 0, 61, 37)
    x, y, w, h = region
    patch = render_region((before, after), copies, divider, color, x, y, w, h)
    np.testing.assert_array_equal(patch, full[y : y + h, x : x + w])


def test_directx_errors_keep_hresult_and_classify_device_loss():
    with pytest.raises(DirectXError) as raised:
        check(0x887A0005 - 2**32, "Present HDR frame")  # signed HRESULT
    assert raised.value.hresult == 0x887A0005 and raised.value.device_lost
    assert "Present HDR frame failed (0x887A0005" in str(raised.value)
    with pytest.raises(DirectXError) as raised:
        check(0x8007000E - 2**32, "Resize HDR surface")  # E_OUTOFMEMORY
    assert not raised.value.device_lost
    assert isinstance(raised.value, RuntimeError)
    check(0x087A0001, "Present HDR frame")  # DXGI_STATUS_OCCLUDED is not a failure.
