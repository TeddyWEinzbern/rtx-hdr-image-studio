"""Ownership and cleanup of per-job cache directories and export staging files.

Every job directory and staging file carries a random 32-hex-digit identifier that
the GUI creates before the worker starts. Cleanup only ever removes paths with an
identifier this process owns, or stale cache directories whose recorded owner has
exited. An idle live instance may still be displaying an old cached preview.
"""

import os
import re
import shutil
import time
import uuid
from pathlib import Path

from .runtime import cache_dir

JOB_ID = re.compile(r"[0-9a-f]{32}")
STAGING_PREFIX = ".rtx-hdr-"
STALE_SECONDS = 24 * 60 * 60
OWNER_FILE = "owner.pid"


def new_job_id() -> str:
    return uuid.uuid4().hex


def jobs_root() -> Path:
    return cache_dir() / "jobs"


def decoder_root() -> Path:
    return cache_dir() / "decode"


def create_owned_dir(path: Path) -> Path:
    """Record the GUI owner before another instance can consider this cache stale."""
    path.mkdir(parents=True)
    (path / OWNER_FILE).write_text(str(os.getpid()), encoding="ascii")
    return path


def _owner_running(path: Path) -> bool:
    try:
        pid = int((path / OWNER_FILE).read_text(encoding="ascii"))
        if not 0 < pid <= 0xFFFFFFFF:
            return True  # An unreadable owner is not evidence of a dead instance.
    except FileNotFoundError:
        return False  # Legacy cache without an owner marker.
    except (OSError, ValueError):
        return True
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes as C

        kernel = C.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [C.c_ulong, C.c_int, C.c_ulong]
        kernel.OpenProcess.restype = C.c_void_p
        kernel.WaitForSingleObject.argtypes = [C.c_void_p, C.c_ulong]
        kernel.WaitForSingleObject.restype = C.c_ulong
        kernel.CloseHandle.argtypes = [C.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE only.
        if not handle:
            return C.get_last_error() != 87  # Only invalid PID establishes absence.
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def staging_prefix(tag: str | None) -> str:
    if tag is None:
        return STAGING_PREFIX
    if not isinstance(tag, str) or not JOB_ID.fullmatch(tag):
        raise ValueError("The export staging tag must be 32 lowercase hexadecimal digits.")
    return f"{STAGING_PREFIX}{tag}-"


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def remove_owned_dir(path, root: Path | None = None) -> bool:
    """Remove ``root/<job id>`` only; never follow links or touch other paths."""
    path = Path(path)
    root = jobs_root() if root is None else root
    if not (_same(path.parent, root) and JOB_ID.fullmatch(path.name)):
        return False
    if path.is_symlink() or path.is_junction() or not path.is_dir():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def _last_activity(path: Path) -> float:
    latest = path.stat().st_mtime
    with os.scandir(path) as entries:
        for entry in entries:
            try:
                latest = max(latest, entry.stat(follow_symlinks=False).st_mtime)
            except OSError:
                pass
    return latest


def purge_stale(root: Path | None = None, max_age: float = STALE_SECONDS, now=None) -> int:
    """Remove old crash leftovers while preserving directories of live owners."""
    root = jobs_root() if root is None else root
    now = time.time() if now is None else now
    removed = 0
    try:
        candidates = list(root.iterdir())
    except OSError:
        return 0
    for path in candidates:
        try:
            if (
                JOB_ID.fullmatch(path.name)
                and not path.is_symlink()
                and not path.is_junction()
                and path.is_dir()
                and now - _last_activity(path) > max_age
                and not _owner_running(path)
                and remove_owned_dir(path, root)
            ):
                removed += 1
        except OSError:
            continue
    return removed


def purge_all_stale(max_age: float = STALE_SECONDS) -> None:
    for root in (jobs_root(), decoder_root()):
        purge_stale(root, max_age)


def remove_staging_files(output_dir, tag) -> list[Path]:
    """Remove unpublished export staging files that belong to one job tag."""
    if not isinstance(tag, str) or not JOB_ID.fullmatch(tag) or not output_dir:
        return []
    removed = []
    try:
        candidates = list(Path(output_dir).glob(f"{STAGING_PREFIX}{tag}-*"))
    except OSError:
        return []
    for path in candidates:
        try:
            if path.is_file() and not path.is_symlink():
                path.unlink()
                removed.append(path)
        except OSError:
            continue
    return removed
