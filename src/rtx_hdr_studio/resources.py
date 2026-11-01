"""Bounded scratch storage and resource checks; no GPU context is created here."""

import ctypes as C
import os
import shutil
import tempfile
from contextvars import ContextVar
from pathlib import Path

import numpy as np

MAX_PIXELS = 943_718_400
MiB = 1024**2
GiB = 1024**3
MAP_THRESHOLD = 64 * MiB
_scratch = ContextVar("image_scratch", default=None)


def validate_size(width, height):
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise ValueError("Input exceeds the 943.72 MP limit (943,718,400 pixels).")
    if max(width, height) > (2**31 - 1) // 4:
        raise ValueError("Image dimensions exceed the SDK row-pitch range.")


def estimate_gpu_bytes(width, height):
    """Measured native TrueHDR commitment, not dedicated-memory residency."""
    return round(247 * MiB + 32.068 * width * height)


def strip_rows(width, bytes_per_pixel=96):
    return max(1, min(128, 16 * MiB // max(1, width * bytes_per_pixel)))


def memory_available():
    if os.name != "nt":
        return None  # Windows is the supported processing platform.

    class Status(C.Structure):
        _fields_ = [("length", C.c_ulong), ("load", C.c_ulong)] + [
            (name, C.c_ulonglong)
            for name in (
                "total",
                "available",
                "commit_total",
                "commit_available",
                "virtual_total",
                "virtual_available",
                "extended",
            )
        ]

    status = Status()
    status.length = C.sizeof(status)
    if not C.windll.kernel32.GlobalMemoryStatusEx(C.byref(status)):
        raise OSError("Cannot query system memory availability.")
    return status.available, status.commit_available


def require_memory(size, purpose, *, commit_size=None, reserve=512 * MiB):
    available = memory_available()
    if available and (
        size + reserve > available[0]
        or (size if commit_size is None else commit_size) + reserve > available[1]
    ):
        raise MemoryError(
            f"Insufficient RAM/commit headroom for {purpose} "
            f"(RAM ~{size / GiB:.1f} GiB, commit ~{(size if commit_size is None else commit_size) / GiB:.1f} GiB, "
            f"reserve {reserve / GiB:.1f} GiB)."
        )


class ScratchSpace:
    """Per-image mappings close before their temporary files are removed."""

    def __init__(self, directory=None):
        self.directory = directory
        self.arrays = []

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="image-", dir=self.directory)
        self.token = _scratch.set(self)
        return self

    def empty(self, shape, dtype):
        size = int(np.prod(shape, dtype=np.int64)) * np.dtype(dtype).itemsize
        if size < MAP_THRESHOLD:
            return np.empty(shape, dtype)
        if shutil.disk_usage(self.temp.name).free < size + 512 * MiB:
            raise OSError(f"Insufficient scratch disk space (~{size / GiB:.1f} GiB required).")
        path = Path(self.temp.name) / f"{len(self.arrays)}.bin"
        array = np.memmap(path, mode="w+", shape=shape, dtype=dtype)
        self.arrays.append(array)
        return array

    def __exit__(self, *_):
        _scratch.reset(self.token)
        for array in self.arrays:
            if array is not None:
                array._mmap.close()
        self.arrays.clear()
        self.temp.cleanup()

    def release(self, array):
        for index, owned in enumerate(self.arrays):
            if owned is array:
                filename = Path(owned.filename)
                owned._mmap.close()
                self.arrays[index] = None
                filename.unlink()
                return


def empty_image(shape, dtype):
    scratch = _scratch.get()
    return scratch.empty(shape, dtype) if scratch else np.empty(shape, dtype)


def release_image(array):
    if array is not None and (scratch := _scratch.get()) is not None:
        scratch.release(array)


class ProcessingLock:
    """An OS-released lock also blocks workers from other application instances."""

    def __enter__(self):
        if os.name == "nt":
            kernel = C.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [C.c_void_p, C.c_int, C.c_wchar_p]
            kernel.CreateMutexW.restype = C.c_void_p
            kernel.WaitForSingleObject.argtypes = [C.c_void_p, C.c_ulong]
            kernel.ReleaseMutex.argtypes = [C.c_void_p]
            kernel.CloseHandle.argtypes = [C.c_void_p]
            self.kernel = kernel
            self.handle = kernel.CreateMutexW(None, False, "Local\\RTXHDRImageStudioProcessing")
            if not self.handle:
                raise OSError("Cannot create the processing lock.")
            result = kernel.WaitForSingleObject(self.handle, 0)
            if result not in (0, 0x80):  # owned, or owner terminated
                kernel.CloseHandle(self.handle)
                self.handle = None
                raise RuntimeError("Another image-processing job is already running.")
        return self

    def __exit__(self, *_):
        if os.name == "nt" and self.handle:
            self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def gpu_capacity(device):
    """CUDA ordinal -> PCI bus ID -> NVML device, without creating a CUDA context."""
    if os.name != "nt":
        raise RuntimeError("GPU information requires Windows/NVIDIA drivers.")
    cuda = C.WinDLL("nvcuda.dll")
    cuda.cuInit.argtypes = [C.c_uint]
    cuda.cuDeviceGet.argtypes = [C.POINTER(C.c_int), C.c_int]
    cuda.cuDeviceGetPCIBusId.argtypes = [C.c_char_p, C.c_int, C.c_int]
    ordinal, pci = C.c_int(), C.create_string_buffer(32)
    for code in (cuda.cuInit(0), cuda.cuDeviceGet(C.byref(ordinal), device)):
        if code:
            raise RuntimeError(f"GPU {device} is unavailable (CUDA {code}).")
    if cuda.cuDeviceGetPCIBusId(pci, len(pci), ordinal.value):
        raise RuntimeError("Cannot identify the processing GPU.")
    nvml = C.CDLL("nvml.dll")
    nvml.nvmlDeviceGetHandleByPciBusId_v2.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    nvml.nvmlDeviceGetMemoryInfo.argtypes = [C.c_void_p, C.c_void_p]
    nvml.nvmlDeviceGetName.argtypes = [C.c_void_p, C.c_char_p, C.c_uint]
    if nvml.nvmlInit_v2():
        raise RuntimeError("Cannot query NVIDIA memory capacity.")
    try:
        handle, name = C.c_void_p(), C.create_string_buffer(128)
        if nvml.nvmlDeviceGetHandleByPciBusId_v2(pci, C.byref(handle)):
            raise RuntimeError("Cannot match the processing GPU to its memory information.")
        memory = (C.c_ulonglong * 3)()  # total, free, used
        if nvml.nvmlDeviceGetMemoryInfo(handle, memory):
            raise RuntimeError("GPU memory information is unavailable.")
        nvml.nvmlDeviceGetName(handle, name, len(name))
        return {
            "device": device,
            "total": memory[0],
            "free": memory[1],
            "name": name.value.decode(errors="replace"),
        }
    finally:
        nvml.nvmlShutdown()
