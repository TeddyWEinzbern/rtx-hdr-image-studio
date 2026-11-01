"""Out-of-process source decoding (Qt-free)."""

import subprocess
import sys
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from PIL import Image

from rtx_hdr_studio.decoder import DecoderClient, DecoderInterrupted
from rtx_hdr_studio.image_io import image_info, load_image
from rtx_hdr_studio.job_cache import decoder_root
from rtx_hdr_studio.runtime import worker_environment


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RTX_HDR_STUDIO_HOME", str(tmp_path / "data"))
    return tmp_path


def test_helper_returns_the_same_pixels_and_metadata_as_in_process_decoding(home):
    path = home / "photo.png"
    rgb = np.random.default_rng(2).integers(0, 256, (90, 160, 3), np.uint8)
    Image.fromarray(rgb).save(path)
    client = DecoderClient()
    try:
        header, payload = client.request("preview", path=str(path), background="white")
        expected, info = load_image(path, "white", preview=True)
        assert header["shape"] == [90, 160, 3] and header["info"] == info
        np.testing.assert_array_equal(
            np.frombuffer(payload, np.uint8).reshape(90, 160, 3), expected
        )
        header, payload = client.request("info", path=str(path))
        assert header["info"] == image_info(path) and len(payload) == 0
    finally:
        client.close()
    assert not any(decoder_root().iterdir())  # Scratch directory removed.


def test_decode_errors_are_reported_and_the_helper_keeps_running(home):
    bad = home / "broken.png"
    bad.write_bytes(b"not an image")
    good = home / "good.png"
    Image.new("RGB", (4, 3), "red").save(good)
    client = DecoderClient()
    try:
        with pytest.raises(ValueError, match="not a readable"):
            client.request("info", path=str(bad))
        process = client._process
        assert client.request("info", path=str(good))[0]["info"]["width"] == 4
        assert client._process is process
    finally:
        client.close()


def test_a_crashed_helper_is_reported_and_replaced(home):
    good = home / "good.png"
    Image.new("RGB", (4, 3), "red").save(good)
    client = DecoderClient()
    try:
        client.start()
        client._process.kill()  # Stand-in for a native decoder crash.
        client._process.wait()
        # The dead helper is detected before use and transparently restarted.
        assert client.request("info", path=str(good))[0]["info"]["height"] == 3
        crash = "import sys; sys.stdin.readline(); sys.exit(3)"
        crashing = DecoderClient(lambda _scratch: [sys.executable, "-c", crash])
        with pytest.raises(RuntimeError, match="stopped unexpectedly"):
            crashing.request("info", path=str(good))
        crashing.close()
    finally:
        client.close()


SLOW_HELPER = "import sys, time; sys.stdin.readline(); time.sleep(60)"


def test_interrupt_abandons_a_slow_request_for_another_file(home):
    client = DecoderClient(lambda _scratch: [sys.executable, "-c", SLOW_HELPER])
    pool = ThreadPoolExecutor(1)
    try:
        future = pool.submit(client.request, "preview", path="a.png", background="black")
        deadline = time.monotonic() + 10
        while client._active is None:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert not client.interrupt(unless_path="a.png", min_seconds=0)
        assert not client.interrupt(unless_path="b.png", min_seconds=30)
        assert client.interrupt(unless_path="b.png", min_seconds=0)
        with pytest.raises(DecoderInterrupted):
            future.result(10)
    finally:
        client.close()
        pool.shutdown()


def test_closing_stops_in_flight_decoding_so_the_process_can_exit(home):
    """AUD-002: measure the whole process, not only the end of the event loop."""
    script = textwrap.dedent(
        f"""
        import sys, threading, time
        from concurrent.futures import ThreadPoolExecutor
        from rtx_hdr_studio.decoder import DecoderClient
        client = DecoderClient(lambda _scratch: [sys.executable, "-c", {SLOW_HELPER!r}])
        pool = ThreadPoolExecutor(1)  # Like IMAGE_POOL: joined at interpreter exit.
        future = pool.submit(client.request, "preview", path="x.png", background="black")
        while client._active is None:
            time.sleep(0.01)
        time.sleep(0.2)
        client.close()  # What StudioWindow.closeEvent does.
        print(type(future.exception(10)).__name__, flush=True)
        """
    )
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=50,
        env=worker_environment(),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "DecoderInterrupted"
    assert time.monotonic() - started < 20  # The helper would have slept for 60 s.


def test_requests_after_close_are_refused(home):
    client = DecoderClient()
    client.close()
    with pytest.raises(DecoderInterrupted):
        client.request("info", path="x.png")
    client.start()
    assert client._process is None


def test_concurrent_requests_are_serialized(home):
    paths = []
    for index in range(6):
        path = home / f"{index}.png"
        Image.new("RGB", (index + 1, 2), "blue").save(path)
        paths.append(str(path))
    client = DecoderClient()
    widths, lock = [], threading.Lock()

    def work(path):
        width = client.request("info", path=path)[0]["info"]["width"]
        with lock:
            widths.append(width)

    try:
        threads = [threading.Thread(target=work, args=(path,)) for path in paths]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert sorted(widths) == [1, 2, 3, 4, 5, 6]
    finally:
        client.close()
