"""Small owned-buffer adapter to the installed NVIDIA VFX 1.3 C API."""

import ctypes as C
from pathlib import Path


class ImageDescriptor(C.Structure):
    # NvCVImage ABI, initialized by NvCVImage_Init rather than by field assignment.
    _fields_ = [
        ("width", C.c_uint),
        ("height", C.c_uint),
        ("pitch", C.c_int),
        ("format", C.c_int),
        ("component", C.c_int),
        ("pixel_bytes", C.c_ubyte),
        ("component_bytes", C.c_ubyte),
        ("components", C.c_ubyte),
        ("planar", C.c_ubyte),
        ("gpu", C.c_ubyte),
        ("colorspace", C.c_ubyte),
        ("reserved", C.c_ubyte * 2),
        ("pixels", C.c_void_p),
        ("delete_ptr", C.c_void_p),
        ("delete_proc", C.c_void_p),
        ("buffer_bytes", C.c_ulonglong),
    ]


class NativeVfx:
    def __init__(self, package):
        if package.get_sdk_version() != "1.3.0":
            raise RuntimeError("The installed NVIDIA VFX SDK must be version 1.3.0.")
        libs = Path(package.__file__).parent / "libs"
        self.vfx = C.CDLL(str(libs / "NVVideoEffects.dll"))
        self.image = C.CDLL(str(libs / "NVCVImage.dll"))
        for name, signature in {
            "NvVFX_CreateEffect": [C.c_char_p, C.POINTER(C.c_void_p)],
            "NvVFX_SetU32": [C.c_void_p, C.c_char_p, C.c_uint],
            "NvVFX_SetImage": [C.c_void_p, C.c_char_p, C.POINTER(ImageDescriptor)],
            "NvVFX_SetCudaStream": [C.c_void_p, C.c_char_p, C.c_void_p],
            "NvVFX_Load": [C.c_void_p],
            "NvVFX_Run": [C.c_void_p, C.c_int],
            "NvVFX_DestroyEffect": [C.c_void_p],
        }.items():
            function = getattr(self.vfx, name)
            function.argtypes, function.restype = signature, C.c_int
        self.image.NvCVImage_Init.argtypes = [
            C.POINTER(ImageDescriptor),
            C.c_uint,
            C.c_uint,
            C.c_int,
            C.c_void_p,
            C.c_int,
            C.c_int,
            C.c_uint,
            C.c_uint,
        ]
        self.image.NvCVImage_Init.restype = C.c_int
        self.handle = C.c_void_p()

    @staticmethod
    def check(status, operation):
        if status:
            raise RuntimeError(f"NVIDIA {operation} failed (status {status}).")

    def load(self, frame, output, settings):
        self.check(self.vfx.NvVFX_CreateEffect(b"TrueHDR", C.byref(self.handle)), "create")
        for key, value in {
            "Contrast": settings.contrast,
            "Saturation": settings.saturation,
            "MiddleGray": settings.middle_gray,
            "Luminance": settings.luminance,
            "DebandingOff": int(not settings.debanding),
        }.items():
            self.check(self.vfx.NvVFX_SetU32(self.handle, key.encode(), value), key)
        self.descriptors = []
        height, width = frame.shape
        for array, fmt, component, selector in (
            (frame, 6, 1, b"SrcImage0"),
            (output, 13, 11, b"DstImage0"),
        ):
            desc = ImageDescriptor()
            self.check(
                self.image.NvCVImage_Init(
                    C.byref(desc), width, height, width * 4, array.data.ptr, fmt, component, 0, 1
                ),
                "image layout",
            )
            self.descriptors.append(desc)
            self.check(self.vfx.NvVFX_SetImage(self.handle, selector, C.byref(desc)), "set image")
        self.check(self.vfx.NvVFX_SetCudaStream(self.handle, b"CudaStream", None), "stream")
        self.check(self.vfx.NvVFX_Load(self.handle), "load")

    def run(self):
        self.check(self.vfx.NvVFX_Run(self.handle, 0), "inference")

    def close(self):
        if self.handle:
            self.vfx.NvVFX_DestroyEffect(self.handle)
            self.handle = C.c_void_p()
        self.descriptors = []
