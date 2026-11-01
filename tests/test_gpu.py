import os
import time

import imagecodecs
import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from rtx_hdr_studio.settings import HdrSettings
from rtx_hdr_studio.ui.jobs import JobRunner


@pytest.mark.gpu
@pytest.mark.skipif(os.environ.get("RTX_HDR_RUN_GPU") != "1", reason="Explicit GPU opt-in required")
@pytest.mark.parametrize(
    "settings",
    [
        HdrSettings(luminance=1000),
        HdrSettings(transfer="gamma22", debanding=False),
        HdrSettings(exposure=0.7, contrast=150, saturation=70, middle_gray=80),
        HdrSettings(exposure=-2, contrast=0, saturation=200, middle_gray=10, luminance=2000),
    ],
)
def test_native_engine_matches_python_and_handles_shape_changes(settings):
    from rtx_hdr_studio.color import packed_pq_to_scrgb
    from rtx_hdr_studio.engine import NvidiaEngine, prepare_sdr

    engine = NvidiaEngine()
    cp, nvvfx = engine.cp, engine.nvvfx
    try:
        for height, width in ((193, 257), (43, 115)):
            rgb = np.random.default_rng(5).integers(0, 256, (height, width, 3), np.uint8)
            frame = cp.asarray(prepare_sdr(rgb, settings))
            with nvvfx.TrueHDR(
                luminance=settings.luminance,
                contrast=settings.contrast,
                saturation=settings.saturation,
                middle_gray=settings.middle_gray,
                debanding_off=int(not settings.debanding),
            ) as reference:
                result = reference.run(frame)
                cp.cuda.runtime.deviceSynchronize()
                view = cp.from_dlpack(result.image)
                expected = packed_pq_to_scrgb(cp.asnumpy(view))
                del result, view
            del frame
            cp.get_default_memory_pool().free_all_blocks()
            actual = engine.convert(rgb, settings, lambda _: None)
            np.testing.assert_array_equal(actual, expected)
            assert not engine.effect.handle
    finally:
        engine.close()


@pytest.mark.gpu
@pytest.mark.skipif(os.environ.get("RTX_HDR_RUN_GPU") != "1", reason="Explicit GPU opt-in required")
def test_real_worker_preview_and_export(tmp_path, monkeypatch):
    monkeypatch.setenv("RTX_HDR_STUDIO_HOME", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "synthetic.png"
    gradient = np.linspace(0, 255, 511, dtype=np.uint8)[None, :].repeat(319, 0)
    Image.fromarray(np.stack([gradient] * 3, -1)).save(path)
    for mode in ("preview", "export"):
        events = []
        job = JobRunner(
            {
                "mode": mode,
                "files": [str(path)],
                "settings": HdrSettings(luminance=1000).to_dict(),
                "job_dir": str(tmp_path / mode),
                "output_dir": str(tmp_path / "out"),
            }
        )
        job.event.connect(events.append)
        job.start()
        deadline = time.monotonic() + 90
        while job.isRunning() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        if job.isRunning():
            job.cancel()
            job.wait(10000)
            pytest.fail("GPU worker timed out")
        app.processEvents()
        assert job.outcome.get("event") == "finished", job.outcome
        result = job.outcome["results"][0]
        assert "error" not in result, result
        assert "NVIDIA" in result["gpu"]
        assert np.load(result["hdr_preview"]).max() > 1
        if mode == "export":
            from pathlib import Path

            data = imagecodecs.jpegxr_decode(Path(result["output"]).read_bytes())
            assert data.shape == (319, 511, 4) and data.dtype == np.float16
