"""Minimal D3D11 FP16/scRGB presenter. No Qt 8-bit image conversion in this path.

Vtable layouts follow Microsoft's d3d11.h, dxgi1_2.h and dxgi1_4.h.
All COM objects belong to, and are released on, the GUI thread.
"""

from __future__ import annotations

import ctypes as C
import uuid
from ctypes import wintypes as W

import numpy as np

P = C.c_void_p
U = C.c_uint32
HR = C.c_long
FP16 = 10  # DXGI_FORMAT_R16G16B16A16_FLOAT
SCRGB = 1  # DXGI_COLOR_SPACE_RGB_FULL_G10_NONE_P709


class Guid(C.Structure):
    _fields_ = [("bytes", C.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__()
        self.bytes[:] = uuid.UUID(value).bytes_le


class SampleDesc(C.Structure):
    _fields_ = [("count", U), ("quality", U)]


class SwapDesc(C.Structure):
    _fields_ = [
        ("width", U),
        ("height", U),
        ("format", U),
        ("stereo", W.BOOL),
        ("sample", SampleDesc),
        ("usage", U),
        ("buffers", U),
        ("scaling", U),
        ("effect", U),
        ("alpha", U),
        ("flags", U),
    ]


class TextureDesc(C.Structure):
    _fields_ = [
        ("width", U),
        ("height", U),
        ("mips", U),
        ("array", U),
        ("format", U),
        ("sample", SampleDesc),
        ("usage", U),
        ("bind", U),
        ("cpu_access", U),
        ("misc", U),
    ]


class Mapped(C.Structure):
    _fields_ = [("data", P), ("row_pitch", U), ("depth_pitch", U)]


def method(obj, slot, result, *arguments):
    table = C.cast(obj, C.POINTER(C.POINTER(P))).contents
    return C.WINFUNCTYPE(result, P, *arguments)(table[slot])


def check(code, operation):
    if code < 0:
        raise RuntimeError(f"{operation} failed (0x{code & 0xFFFFFFFF:08X})")


def release(obj):
    if obj:
        method(obj, 2, U)(obj)
        obj.value = None


def query(obj, iid):
    result = P()
    check(
        method(obj, 0, HR, P, P)(obj, C.byref(Guid(iid)), C.byref(result)),
        "Query DirectX interface",
    )
    return result


class Presenter:
    """Present opaque RGBA half-float pixels to one native child HWND."""

    def __init__(self, hwnd: int, width: int, height: int):
        self.device, self.context, self.swap, self.buffer = P(), P(), P(), P()
        self.width = self.height = 0
        self.frames = 0
        dxgi_device, adapter, factory, chain = P(), P(), P(), P()
        try:
            create = C.windll.d3d11.D3D11CreateDevice
            create.argtypes = [P, U, P, U, P, U, U, P, P, P]
            create.restype = HR
            level = U()
            check(
                create(
                    None,
                    1,
                    None,
                    0x20,
                    None,
                    0,
                    7,
                    C.byref(self.device),
                    C.byref(level),
                    C.byref(self.context),
                ),
                "Create Direct3D 11 device",
            )
            dxgi_device = query(self.device, "54ec77fa-1377-44e6-8c32-88fd5f44c84c")
            check(
                method(dxgi_device, 7, HR, P)(dxgi_device, C.byref(adapter)), "Get graphics adapter"
            )
            check(
                method(adapter, 6, HR, P, P)(
                    adapter, C.byref(Guid("50c83a1c-e072-4c48-87b0-3630fa36a6d0")), C.byref(factory)
                ),
                "Get DXGI factory",
            )
            description = SwapDesc(
                max(width, 1), max(height, 1), FP16, False, SampleDesc(1, 0), 0x20, 2, 0, 4, 3, 0
            )  # flip discard, opaque
            check(
                method(factory, 15, HR, P, W.HWND, P, P, P, P)(
                    factory, self.device, hwnd, C.byref(description), None, None, C.byref(chain)
                ),
                "Create HDR surface",
            )
            # Prevent automatic Alt+Enter exclusive-fullscreen handling.
            check(method(factory, 8, HR, W.HWND, U)(factory, hwnd, 2), "Set window association")
            self.swap = query(chain, "94d99bdb-f1f8-4ab0-b236-7da0170edab1")
            supported = U()
            check(
                method(self.swap, 37, HR, U, P)(self.swap, SCRGB, C.byref(supported)),
                "Check scRGB support",
            )
            if not supported.value & 1:
                raise RuntimeError(
                    "This graphics environment does not support an scRGB window surface."
                )
            check(method(self.swap, 38, HR, U)(self.swap, SCRGB), "Set scRGB color space")
            self.width, self.height = description.width, description.height
            self._get_buffer()
        except Exception:
            self.close()
            raise
        finally:
            for obj in (chain, factory, adapter, dxgi_device):
                release(obj)

    def _get_buffer(self):
        check(
            method(self.swap, 9, HR, U, P, P)(
                self.swap,
                0,
                C.byref(Guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")),
                C.byref(self.buffer),
            ),
            "Get HDR backbuffer",
        )

    def resize(self, width, height):
        width, height = max(width, 1), max(height, 1)
        if (width, height) == (self.width, self.height):
            return
        release(self.buffer)
        check(
            method(self.swap, 13, HR, U, U, U, U, U)(self.swap, 2, width, height, FP16, 0),
            "Resize HDR surface",
        )
        self.width, self.height = width, height
        self._get_buffer()

    def upload(self, rgba: np.ndarray):
        if rgba.shape != (self.height, self.width, 4) or rgba.dtype != np.float16:
            raise ValueError("HDR pixels must be FP16 RGBA matching the surface dimensions.")
        pixels = np.ascontiguousarray(rgba)
        method(self.context, 48, None, P, U, P, P, U, U)(
            self.context, self.buffer, 0, None, pixels.ctypes.data, self.width * 8, 0
        )

    def present(self):
        check(method(self.swap, 8, HR, U, U)(self.swap, 1, 0), "Present HDR frame")
        self.frames += 1

    def readback(self) -> np.ndarray:
        """Validation only: copy our own GPU backbuffer to verify no 0..1 clamp."""
        staging = P()
        try:
            desc = TextureDesc(
                self.width, self.height, 1, 1, FP16, SampleDesc(1, 0), 3, 0, 0x20000, 0
            )
            check(
                method(self.device, 5, HR, P, P, P)(
                    self.device, C.byref(desc), None, C.byref(staging)
                ),
                "Create validation texture",
            )
            method(self.context, 47, None, P, P)(self.context, staging, self.buffer)
            mapped = Mapped()
            check(
                method(self.context, 14, HR, P, U, U, U, P)(
                    self.context, staging, 0, 1, 0, C.byref(mapped)
                ),
                "Read validation texture",
            )
            try:
                result = np.empty((self.height, self.width, 4), dtype=np.float16)
                for row in range(self.height):
                    C.memmove(
                        result[row].ctypes.data,
                        mapped.data + row * mapped.row_pitch,
                        self.width * 8,
                    )
                return result
            finally:
                method(self.context, 15, None, P, U)(self.context, staging, 0)
        finally:
            release(staging)

    def close(self):
        for obj in (self.buffer, self.swap, self.context, self.device):
            release(obj)
