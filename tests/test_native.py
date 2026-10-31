import os
import sys

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QWidget


@pytest.mark.native
@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("RTX_HDR_RUN_NATIVE") != "1",
    reason="Windows and explicit native opt-in required",
)
def test_fp16_gpu_readback_and_resize():
    from rtx_hdr_studio.graphics.directx import Presenter

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.resize(127, 83)
    renderer = Presenter(int(window.winId()), 127, 83)
    try:
        for w, h in ((127, 83), (211, 119)):
            renderer.resize(w, h)
            pixels = np.full((h, w, 4), [12.5, -0.125, 2.5, 1], np.float16)
            renderer.upload(pixels)
            np.testing.assert_array_equal(renderer.readback(), pixels)
            renderer.present()
    finally:
        renderer.close()
        window.close()
        app.processEvents()
