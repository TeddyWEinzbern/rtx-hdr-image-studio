"""Read-only Windows display status, including SDR ACM versus active HDR."""

from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass


class Luid(C.Structure):
    _fields_ = [("low", W.DWORD), ("high", W.LONG)]


class Source(C.Structure):
    _fields_ = [("adapter", Luid), ("id", W.UINT), ("mode", W.UINT), ("flags", W.UINT)]


class Target(C.Structure):
    _fields_ = [
        ("adapter", Luid),
        ("id", W.UINT),
        ("mode", W.UINT),
        ("technology", W.UINT),
        ("rotation", W.UINT),
        ("scaling", W.UINT),
        ("refresh_numerator", W.UINT),
        ("refresh_denominator", W.UINT),
        ("scanline", W.UINT),
        ("available", W.BOOL),
        ("flags", W.UINT),
    ]


class DisplayPath(C.Structure):
    _fields_ = [("source", Source), ("target", Target), ("flags", W.UINT)]


class Header(C.Structure):
    _fields_ = [("type", W.UINT), ("size", W.UINT), ("adapter", Luid), ("id", W.UINT)]


class SourceName(C.Structure):
    _fields_ = [("header", Header), ("name", W.WCHAR * 32)]


class ColorInfo(C.Structure):
    _fields_ = [("header", Header), ("flags", W.UINT), ("encoding", W.UINT), ("bits", W.UINT)]


class ColorInfo2(C.Structure):
    _fields_ = ColorInfo._fields_ + [("mode", W.UINT)]


class WhiteLevel(C.Structure):
    _fields_ = [("header", Header), ("level", W.ULONG)]


class MonitorInfo(C.Structure):
    _fields_ = [
        ("size", W.DWORD),
        ("monitor", W.RECT),
        ("work", W.RECT),
        ("flags", W.DWORD),
        ("name", W.WCHAR * 32),
    ]


@dataclass(frozen=True)
class DisplayInfo:
    name: str = ""
    hdr_active: bool = False
    hdr_supported: bool = False
    color_mode: str = "unknown"
    sdr_white_nits: float = 203.0
    bits: int = 0
    error: str = ""


def _device_info(cls, kind, endpoint):
    value = cls()
    value.header = Header(kind, C.sizeof(cls), endpoint.adapter, endpoint.id)
    code = C.windll.user32.DisplayConfigGetDeviceInfo(C.byref(value))
    return value if code == 0 else None


def query_display(hwnd: int) -> DisplayInfo:
    """Query the monitor containing most of this window. Never changes OS settings."""
    user32 = C.windll.user32
    user32.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]
    user32.MonitorFromWindow.restype = W.HMONITOR
    user32.GetMonitorInfoW.argtypes = [W.HMONITOR, C.c_void_p]
    monitor = user32.MonitorFromWindow(hwnd, 2)
    info = MonitorInfo()
    info.size = C.sizeof(info)
    if not user32.GetMonitorInfoW(monitor, C.byref(info)):
        return DisplayInfo(error="Unable to read the window display.")
    for _ in range(3):  # A monitor can be disconnected between these two calls.
        path_count, mode_count = W.UINT(), W.UINT()
        code = user32.GetDisplayConfigBufferSizes(2, C.byref(path_count), C.byref(mode_count))
        if code:
            return DisplayInfo(name=info.name, error=f"Display status query failed ({code})")
        paths = (DisplayPath * path_count.value)()
        modes = C.create_string_buffer(64 * mode_count.value)
        code = user32.QueryDisplayConfig(
            2, C.byref(path_count), paths, C.byref(mode_count), modes, None
        )
        if code == 122:
            continue
        if code:
            return DisplayInfo(name=info.name, error=f"Display status query failed ({code})")
        for path in paths[: path_count.value]:
            source = _device_info(SourceName, 1, path.source)
            if source is None or source.name != info.name:
                continue
            white = _device_info(WhiteLevel, 11, path.target)
            white_nits = white.level * 0.08 if white and white.level else 203.0
            # Win11 24H2 explicitly distinguishes SDR, WCG/ACM and HDR.
            color = _device_info(ColorInfo2, 15, path.target)
            if color:
                mode = {0: "SDR", 1: "ACM", 2: "HDR"}.get(color.mode, "unknown")
                return DisplayInfo(
                    info.name, mode == "HDR", bool(color.flags & 16), mode, white_nits, color.bits
                )
            # Older Windows uses wideColorEnforced to identify SDR WCG mode.
            old = _device_info(ColorInfo, 9, path.target)
            if old:
                hdr = bool(old.flags & 2) and not bool(old.flags & 4)
                mode = "HDR" if hdr else ("ACM" if old.flags & 4 else "SDR")
                return DisplayInfo(
                    info.name,
                    hdr,
                    bool(old.flags & 1) and mode != "ACM",
                    mode,
                    white_nits,
                    old.bits,
                )
        break
    return DisplayInfo(name=info.name, error="Unable to determine the display HDR state.")
