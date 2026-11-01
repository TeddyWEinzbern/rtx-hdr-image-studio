"""Coalesced background preparation. Workers never access Qt widgets or GPU contexts."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from ..color import srgb8_to_linear, srgb_to_linear
from ..image_io import image_info, load_image, resize_linear
from ..resources import ScratchSpace
from .geometry import image_placement

CPU_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="preview")
DEVICE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hdr-device")
IMAGE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="image-decode")


def source_info(source, decoder=None):
    """Header-only metadata; parsed in the decoder process when one is given."""
    if decoder is None:
        return source, image_info(source)
    header, _ = decoder.request("info", path=source)
    return source, header["info"]


class LatestTask(QObject):
    """Run one task at a time, retaining only the newest pending request."""

    completed = Signal(int, object, object)
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None, executor=CPU_POOL):
        super().__init__(parent)
        self.executor = executor
        self._generation = 0
        self._pending = None
        self._future = None
        self._closed = threading.Event()
        self.completed.connect(self._complete)

    def submit(self, function, *arguments):
        if self._closed.is_set():
            return
        self._generation += 1
        self._pending = (self._generation, function, arguments)
        if self._future is None:
            self._launch()

    def _launch(self):
        token, function, arguments = self._pending
        self._pending = None
        self._future = self.executor.submit(function, *arguments)

        def finished(future):
            try:
                value, error = future.result(), None
            except Exception as exception:
                value, error = None, str(exception)
            if not self._closed.is_set():
                try:
                    self.completed.emit(token, value, error)
                except RuntimeError:
                    pass  # The owning Qt window was already destroyed.

        self._future.add_done_callback(finished)

    def _complete(self, token, value, error):
        self._future = None
        if self._closed.is_set():
            return
        if token == self._generation:
            if error is None:
                self.ready.emit(value)
            else:
                self.failed.emit(error)
        if self._pending is not None and self._future is None:
            self._launch()

    def cancel(self):
        self._generation += 1
        self._pending = None
        if self._future is not None:
            self._future.cancel()

    def close(self):
        self._closed.set()
        self.cancel()


@dataclass
class LoadedPreview:
    source: str
    before: QImage
    after: QImage
    hdr_path: object
    info: dict


def load_preview(source, result, background, decoder=None):
    if result:
        # Our own bounded PNG caches; decoding them in-process is safe and fast.
        before, after = QImage(result["before"]), QImage(result["after"])
        if before.isNull() or after.isNull():
            raise ValueError("Preview cache is unavailable. Generate the preview again.")
        return LoadedPreview(source, before, after, result["hdr_preview"], result["info"])
    if decoder is not None:
        # Untrusted source files are decoded in a killable, crash-isolated process.
        header, payload = decoder.request("preview", path=source, background=background)
        height, width, channels = header["shape"]
        if channels != 3 or len(payload) != height * width * 3:
            raise ValueError("The image decoder returned an invalid preview.")
        pixels = np.frombuffer(payload, np.uint8)
        before = QImage(pixels.data, width, height, width * 3, QImage.Format.Format_RGB888)
        return LoadedPreview(source, before.copy(), QImage(), None, header["info"])
    with ScratchSpace():
        rgb, info = load_image(source, background, preview=True)
        height, width = rgb.shape[:2]
        before = QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
    return LoadedPreview(source, before, QImage(), None, info)


def image_to_linear(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    rgb = data[:, : image.width() * 4].reshape(image.height(), image.width(), 4)[..., :3]
    return srgb8_to_linear(rgb)  # 256-entry table; identical to the float formula.


def load_hdr(image, path):
    data = np.load(path, allow_pickle=False)
    if (
        data.ndim != 3
        or data.shape[2] != 3
        or data.dtype != np.float16
        or not np.isfinite(data).all()
    ):
        raise ValueError("Invalid HDR preview cache. Generate the preview again.")
    return image_to_linear(image), data


def prepare_sdr_frames(before, after, width, height, mode, margin):
    """Filter at the final physical display size; no QPixmap/GUI work here."""
    h, w = before.height(), before.width()
    x, y, iw, ih = image_placement(w, h, width, height, mode, margin)
    left, top = max(0, x), max(0, y)
    right, bottom = min(width, x + iw), min(height, y + ih)
    box = None
    if (left, top, right, bottom) != (x, y, x + iw, y + ih):
        box = ((left - x) * w / iw, (top - y) * h / ih, (right - x) * w / iw, (bottom - y) * h / ih)
    images = []
    for image in (before, after):
        if image.isNull():
            images.append(QImage())
            continue
        image = image.convertToFormat(QImage.Format.Format_RGB888)
        pixels = np.frombuffer(image.constBits(), np.uint8).reshape(
            image.height(), image.bytesPerLine()
        )
        pixels = pixels[:, : image.width() * 3].reshape(image.height(), image.width(), 3)
        scaled = resize_linear(pixels, right - left, bottom - top, box=box)
        rgb = np.clip(np.rint(scaled), 0, 255).astype(np.uint8)
        images.append(
            QImage(
                rgb.data,
                right - left,
                bottom - top,
                (right - left) * 3,
                QImage.Format.Format_RGB888,
            ).copy()
        )
    return left, top, right - left, bottom - top, *images


def prepare_frames(before_linear, after_linear, width, height, white, mode, margin):
    frame = np.empty((height, width, 4), dtype=np.float16)
    frame[..., :3] = srgb_to_linear(np.array([16, 21, 27], np.float32) / 255) * white
    frame[..., 3] = 1
    h, w = after_linear.shape[:2]
    x, y, iw, ih = image_placement(w, h, width, height, mode, margin)
    left, top = max(0, x), max(0, y)
    right, bottom = min(width, x + iw), min(height, y + ih)
    box = None
    if (left, top, right, bottom) != (x, y, x + iw, y + ih):
        # Resize only the visible source crop, even for very wide/tall images.
        box = ((left - x) * w / iw, (top - y) * h / ih, (right - x) * w / iw, (bottom - y) * h / ih)
    before = frame
    after = frame.copy()
    before[top:bottom, left:right, :3] = (
        resize_linear(before_linear, right - left, bottom - top, box=box) * white
    )
    after[top:bottom, left:right, :3] = resize_linear(
        after_linear, right - left, bottom - top, box=box
    )
    return before, after, top, bottom - top


class PreviewDevice(QObject):
    """One D3D11 device shared by every HDR surface; rebuilt after device loss."""

    ready = Signal()
    failed = Signal(str)
    lost = Signal()  # Surfaces must release swap chains and textures immediately.
    MAX_RECOVERIES = 3
    RECOVERY_WINDOW = 60.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resources = None
        self.requested = False
        self.error = ""
        self._closed = False
        self._recoveries = []
        self.task = LatestTask(self, DEVICE_POOL)
        self.task.ready.connect(self._ready)
        self.task.failed.connect(self._failed)

    def ensure(self):
        if not self.requested and not self.error and self.resources is None:
            from ..graphics.directx import DeviceResources

            self.requested = True
            self.task.submit(DeviceResources)

    def _ready(self, resources):
        self.resources = resources
        self.ready.emit()

    def _failed(self, error):
        self.error = error
        self.failed.emit(error)

    def retry(self):
        if self.error:
            self.error = ""
            self.requested = False

    def report_lost(self, message):
        """DXGI reported device removal/reset: release everything, then reinitialize."""
        if self._closed or self.resources is None:
            return  # Shutting down, or another surface already started the rebuild.
        now = time.monotonic()
        self._recoveries = [t for t in self._recoveries if now - t < self.RECOVERY_WINDOW]
        self._recoveries.append(now)
        logging.getLogger(__name__).warning("Graphics device lost: %s", message)
        self.lost.emit()
        resources, self.resources = self.resources, None
        resources.close()
        self.requested = False
        if len(self._recoveries) > self.MAX_RECOVERIES:
            # Avoid an endless rebuild loop; keep the SDR fallback with a reason.
            self._failed(f"The graphics device was reset repeatedly. {message}")
            return
        self.ensure()

    def close(self):
        self._closed = True
        self.task.close()
        if self.resources is not None:
            self.resources.close()
            self.resources = None
