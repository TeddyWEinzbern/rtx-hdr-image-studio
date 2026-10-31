import math

import numpy as np
import pytest

from rtx_hdr_studio.color import packed_pq_to_scrgb, pq_to_nits, srgb_to_linear
from rtx_hdr_studio.engine import prepare_sdr
from rtx_hdr_studio.settings import HdrSettings


def test_pq_reference_luminance():
    np.testing.assert_allclose(
        pq_to_nits(np.array([0, 0.5080784215, 0.7518270962, 1])), [0, 100, 1000, 10000], atol=0.001
    )


def test_wide_gamut_red_has_negative_scrgb_channels():
    red = packed_pq_to_scrgb(np.array([[1023]], np.uint32))[0, 0]
    assert red[0] > 1 and red[1] < 0 and red[2] < 0


def test_srgb_threshold_and_input_exposure():
    assert srgb_to_linear(np.array([0.04045]))[0] == pytest.approx(0.003130805, abs=1e-8)
    rgb = np.array([[[0, 128, 255]]], np.uint8)
    normal = prepare_sdr(rgb, HdrSettings())
    darker = prepare_sdr(rgb, HdrSettings(exposure=-1))
    assert normal.shape == (3, 1, 1) and normal.flags.c_contiguous
    assert darker[2, 0, 0] < normal[2, 0, 0]
    gamma = prepare_sdr(rgb, HdrSettings(transfer="gamma22"))
    assert gamma[1, 0, 0] == pytest.approx(128 / 255)


@pytest.mark.parametrize(
    "invalid",
    [
        {"luminance": 300},
        {"luminance": True},
        {"contrast": 201},
        {"saturation": -1},
        {"middle_gray": 0},
        {"exposure": math.nan},
        {"exposure": math.inf},
        {"exposure": "1"},
        {"device": -1},
        {"device": True},
        {"debanding": 1},
        {"transfer": "pq"},
        {"background": "red"},
        {"unexpected": 1},
    ],
)
def test_invalid_settings_fail_at_boundary(invalid):
    with pytest.raises(ValueError):
        HdrSettings.from_dict(invalid)


def test_settings_roundtrip():
    settings = HdrSettings(luminance=1000, debanding=False, exposure=0.25)
    assert HdrSettings.from_dict(settings.to_dict()) == settings
