"""Runtime paths and DLL discovery. Never downloads or installs dependencies."""

import os
import site
import sys
import tempfile
from pathlib import Path

_dll_handles: list = []


def data_root() -> Path:
    override = os.environ.get("RTX_HDR_STUDIO_HOME")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    return base / "RTX HDR Image Studio"


def cache_dir() -> Path:
    path = data_root() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir() -> Path:
    return Path.home() / "Pictures" / "RTX HDR Image Studio"


def configure_gpu() -> None:
    """Discover DLLs already installed by the user's package manager."""
    os.environ.setdefault("CUPY_CACHE_DIR", str(cache_dir() / "cupy"))
    if os.name == "nt" and not _dll_handles:
        roots = [Path(path) for path in site.getsitepackages()]
        roots += [Path(path) for path in sys.path if path]
        for root in dict.fromkeys(roots):
            for folder in (root / "nvidia").glob("*/bin"):
                _dll_handles.append(os.add_dll_directory(str(folder)))


def worker_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    # Also supports a source checkout launched with `python -m`.
    paths = [path for path in sys.path if path]
    environment["PYTHONPATH"] = os.pathsep.join(paths)
    return environment
