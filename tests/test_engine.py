"""CPU-side NvidiaEngine logic with a fake CUDA runtime (no GPU required)."""

import ctypes
import itertools
from types import SimpleNamespace

import numpy as np
import pytest

from rtx_hdr_studio.color import (
    HdrStatistics,
    hdr_statistics,
    packed_pq_to_scrgb,
    srgb8_to_linear,
    srgb_to_linear,
)
from rtx_hdr_studio.engine import NvidiaEngine, prepare_sdr, sdr_lut
from rtx_hdr_studio.pipeline import process_files
from rtx_hdr_studio.settings import HdrSettings


class FakeRuntime:
    def __init__(self):
        self.sticky = None
        self.synchronized = 0

    def memcpy(self, destination, source, size, _kind):
        ctypes.memmove(destination, source, size)

    def deviceSynchronize(self):  # noqa: N802 - CUDA runtime name
        self.synchronized += 1
        if self.sticky:
            raise RuntimeError(self.sticky)


class FakeCupy:
    uint32 = np.uint32

    def __init__(self):
        self.cuda = SimpleNamespace(
            runtime=FakeRuntime(), Memory=lambda size: size, MemoryPointer=lambda m, o: m
        )

    @staticmethod
    def ndarray(shape, dtype, memptr):
        array = np.zeros(shape, dtype)
        return SimpleNamespace(
            array=array, shape=shape, data=SimpleNamespace(ptr=array.ctypes.data)
        )


class FakeEffect:
    """Identity 'inference': copies the uploaded RGBA8 words to the output."""

    def __init__(self, failure=None, cupy=None):
        self.failure, self.cupy, self.handle, self.closed = failure, cupy, None, 0

    def load(self, frame, output, settings):
        self.frame, self.output, self.handle = frame, output, 1

    def run(self):
        if self.failure:
            self.cupy.cuda.runtime.sticky = "cudaErrorIllegalAddress"
            raise RuntimeError(self.failure)
        self.output.array[...] = self.frame.array

    def close(self):
        self.closed += 1
        self.handle = None


def fake_engine(failure=None):
    engine = object.__new__(NvidiaEngine)
    engine.cp, engine.device, engine.name = FakeCupy(), 0, "Fake NVIDIA adapter"
    engine.effect = FakeEffect(failure, engine.cp)
    engine.failed, engine.last_statistics = False, None
    engine.check_resources = lambda width, height: None
    return engine


@pytest.mark.parametrize(
    "settings",
    [HdrSettings(), HdrSettings(transfer="gamma22", exposure=-1.25), HdrSettings(exposure=2.7)],
)
def test_lookup_tables_match_the_float_chain_exactly(settings):
    rgb = np.random.default_rng(3).integers(0, 256, (37, 53, 3), np.uint8)
    codes = np.arange(256, dtype=np.uint8)[None, :, None].repeat(3, 2)
    for image in (rgb, codes):
        expected = np.rint(prepare_sdr(image, settings).transpose(1, 2, 0) * 255).astype(np.uint8)
        np.testing.assert_array_equal(sdr_lut(settings)[image], expected)
    expected = srgb_to_linear(rgb.astype(np.float32) / np.float32(255))
    actual = srgb8_to_linear(rgb)
    assert actual.dtype == np.float32
    np.testing.assert_array_equal(actual, expected)


def test_convert_uploads_every_strip_and_collects_identical_statistics(monkeypatch):
    from rtx_hdr_studio import engine as engine_module

    # Force several upload/readback strips on a small image.
    monkeypatch.setattr(engine_module, "strip_rows", lambda width, bpp=96: 7 if bpp == 8 else 5)
    settings = HdrSettings(exposure=0.5)
    rgb = np.random.default_rng(9).integers(0, 256, (31, 29, 3), np.uint8)
    engine = fake_engine()
    scrgb = engine.convert(rgb, settings, lambda _: None)
    rgba = np.empty((31, 29, 4), np.uint8)
    rgba[..., :3], rgba[..., 3] = sdr_lut(settings)[rgb], 255
    expected = packed_pq_to_scrgb(rgba.view(np.uint32)[..., 0])
    np.testing.assert_array_equal(scrgb, expected)
    assert engine.last_statistics == hdr_statistics(expected)
    assert engine.effect.closed == 1 and not engine.failed


def test_gpu_failure_keeps_the_original_nvidia_message():
    engine = fake_engine("NVIDIA inference failed (status 7).")
    with pytest.raises(RuntimeError, match="status 7"):
        engine.convert(np.zeros((4, 5, 3), np.uint8), HdrSettings(), lambda _: None)
    assert engine.failed and engine.effect.closed == 1
    synchronized = engine.cp.cuda.runtime.synchronized
    engine.close()  # Must not raise the sticky CUDA error over the original one.
    assert engine.cp.cuda.runtime.synchronized == synchronized


def test_worker_reports_the_file_name_and_original_gpu_error(tmp_path):
    from PIL import Image

    path = tmp_path / "photo.png"
    Image.new("RGB", (5, 4), "red").save(path)
    engine = fake_engine("NVIDIA inference failed (status 7).")
    with pytest.raises(RuntimeError) as raised:
        process_files(
            {
                "mode": "preview",
                "files": [str(path)],
                "settings": HdrSettings().to_dict(),
                "job_dir": str(tmp_path / "job"),
                "output_dir": str(tmp_path / "out"),
            },
            lambda _: None,
            lambda _: engine,
        )
    message = str(raised.value)
    assert "photo.png" in message and "status 7" in message
    assert "cudaError" not in message


def test_truehdr_output_is_bounded_well_inside_fp16():
    corners = [
        sum((1023 if bit else 0) << (10 * channel) for channel, bit in enumerate(bits))
        for bits in itertools.product((0, 1), repeat=3)
    ]
    # PQ decode is per-channel monotonic and the gamut matrix is linear, so the
    # extremes of the 30-bit cube are at its corners.
    scrgb = packed_pq_to_scrgb(np.array([corners], np.uint32))
    assert np.isfinite(scrgb).all() and np.abs(scrgb).max() < 300 < np.finfo(np.float16).max
    assert NvidiaEngine.output_range_trusted


def test_statistics_accumulator_matches_full_scan():
    scrgb = np.random.default_rng(1).normal(2, 3, (23, 41, 3)).astype(np.float32)
    statistics = HdrStatistics()
    for y in range(0, 23, 4):
        statistics.add(scrgb[y : y + 4])
    assert statistics.result() == hdr_statistics(scrgb)
