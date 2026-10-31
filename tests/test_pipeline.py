import json

import imagecodecs
import numpy as np
from PIL import Image

from rtx_hdr_studio.pipeline import process_files
from rtx_hdr_studio.settings import HdrSettings


class FakeEngine:
    name = "Deterministic test adapter (not NVIDIA)"
    closed = False

    def __init__(self, device):
        self.device = device

    def convert(self, rgb, settings, progress):
        return np.full((*rgb.shape[:2], 3), [12.5, -0.125, 1], np.float32)

    def close(self):
        self.closed = True


def test_batch_continues_and_closes_engine_with_valid_outputs(tmp_path):
    paths = []
    for folder in ("one", "two"):
        directory = tmp_path / folder
        directory.mkdir()
        path = directory / "same.png"
        Image.new("RGB", (17, 13), "red").save(path)
        paths.append(str(path))
    bad = tmp_path / "corrupt.png"
    bad.write_bytes(b"not an image")
    engine = FakeEngine(0)
    events = []
    results = process_files(
        {
            "mode": "export",
            "files": [paths[0], str(bad), paths[1]],
            "settings": HdrSettings().to_dict(),
            "job_dir": str(tmp_path / "cache"),
            "output_dir": str(tmp_path / "exports"),
        },
        events.append,
        lambda _: engine,
    )
    assert engine.closed and "error" in results[1]
    assert results[0]["output"] != results[2]["output"]
    for result in (results[0], results[2]):
        from pathlib import Path

        path = Path(result["output"])
        assert imagecodecs.jpegxr_decode(path.read_bytes()).shape == (13, 17, 4)
        metadata = json.loads(path.with_suffix(".settings.json").read_text())
        assert metadata["gpu"] == engine.name
    assert sum(e["event"] == "file_error" for e in events) == 1
