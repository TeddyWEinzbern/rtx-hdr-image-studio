import pytest

from rtx_hdr_studio.ui.geometry import image_placement


@pytest.mark.parametrize(
    "image, viewport, mode, expected",
    [
        ((400, 200), (800, 600), "fit", (0, 100, 800, 400)),
        ((200, 400), (800, 600), "fit", (250, 0, 300, 600)),
        ((400, 200), (800, 600), "fill", (-200, 0, 1200, 600)),
        ((200, 400), (800, 600), "fill", (0, -500, 800, 1600)),
        ((400, 300), (800, 600), "fill", (0, 0, 800, 600)),
        ((400, 200), (800, 600), "stretch", (0, 0, 800, 600)),
        ((400, 200), (800, 600), "actual", (200, 200, 400, 200)),
        ((800, 600), (800, 600), "actual", (0, 0, 800, 600)),
        ((1000, 200), (800, 600), "actual", (0, 220, 800, 160)),
        ((200, 1000), (800, 600), "actual", (340, 0, 120, 600)),
        ((1600, 1200), (800, 600), "actual", (0, 0, 800, 600)),
    ],
)
def test_fullscreen_placement(image, viewport, mode, expected):
    assert image_placement(*image, *viewport, mode) == expected
