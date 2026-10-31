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
