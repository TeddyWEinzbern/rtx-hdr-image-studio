"""Out-of-process decoding of user images for the GUI.

Untrusted source files are parsed by Pillow, libtiff, libwebp, libjpeg and LittleCMS.
Running that work in a helper process means a native decoder crash cannot take the
interface down, and closing the window can stop a long decode immediately instead
of waiting for a thread that cannot be interrupted (Python joins pool threads at
exit). The helper is long-lived so that start-up cost is paid once per session.

Protocol (binary pipes): one JSON request line in; one JSON header line out, then
``header["size"]`` raw bytes (C-contiguous uint8 RGB for previews).
"""

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .job_cache import create_owned_dir, decoder_root, new_job_id, remove_owned_dir
from .runtime import worker_environment


class DecoderInterrupted(RuntimeError):
    """The request was abandoned because a newer one replaced it, or on close."""


class DecoderClient:
    """Thread-safe client for one helper process; requests are serialized."""

    def __init__(self, command: Callable[[Path], list[str]] | None = None):
        self._command = command or (
            lambda scratch: [sys.executable, "-P", "-m", "rtx_hdr_studio.decoder", str(scratch)]
        )
        self._request_lock = threading.Lock()
        self._state = threading.Lock()
        self._process = None
        self._scratch = None
        self._closed = False
        self._active = None  # (path, start time) of the request in flight

    def start(self) -> None:
        """Start the helper ahead of the first request; never blocks on imports."""
        with self._state:
            if not self._closed and not self._running_locked():
                self._spawn_locked()

    def _running_locked(self):
        return self._process is not None and self._process.poll() is None

    def _spawn_locked(self):
        self._stop_locked()
        scratch = create_owned_dir(decoder_root() / new_job_id())
        try:
            self._process = subprocess.Popen(
                self._command(scratch),
                cwd=scratch,
                env=worker_environment(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except BaseException:
            remove_owned_dir(scratch, decoder_root())
            raise
        self._scratch = scratch

    def _stop_locked(self):
        process, self._process = self._process, None
        scratch, self._scratch = self._scratch, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                pass
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
        if scratch is not None:
            remove_owned_dir(scratch, decoder_root())

    def request(self, op: str, **fields) -> tuple[dict, bytearray]:
        with self._request_lock:
            with self._state:
                if self._closed:
                    raise DecoderInterrupted("Image decoding was cancelled.")
                if not self._running_locked():
                    self._spawn_locked()
                process = self._process
                self._active = (fields.get("path"), time.monotonic())
            try:
                process.stdin.write(json.dumps({"op": op, **fields}).encode() + b"\n")
                process.stdin.flush()
                line = process.stdout.readline()
                if not line:
                    raise EOFError
                header = json.loads(line)
                size = int(header.get("size", 0))
                # Writable buffer without an extra copy (QImage wraps it like NumPy data).
                payload = bytearray(size)
                view, received = memoryview(payload), 0
                while received < size:
                    count = process.stdout.readinto(view[received:])
                    if not count:
                        raise EOFError
                    received += count
                del view
            except (OSError, EOFError, ValueError) as error:
                with self._state:
                    replaced = self._process is not process
                    if not replaced:
                        self._stop_locked()
                    code = process.poll()
                if replaced or self._closed:
                    raise DecoderInterrupted("Image decoding was interrupted.") from error
                raise RuntimeError(
                    f"The image decoder stopped unexpectedly (exit code {code}). "
                    "The file may be damaged or use an unsupported feature."
                ) from error
            finally:
                with self._state:
                    self._active = None
        if "error" in header:
            raise ValueError(header["error"])
        return header, payload

    def interrupt(self, unless_path=None, min_seconds=1.0) -> bool:
        """Stop a slow request for another file; the next request restarts the helper."""
        with self._state:
            active = self._active
            if (
                active is None
                or active[0] == unless_path
                or time.monotonic() - active[1] < min_seconds
            ):
                return False
            self._stop_locked()
            return True

    def close(self) -> None:
        with self._state:
            self._closed = True
            self._stop_locked()


def _serve(requests, replies, scratch: Path) -> None:
    import numpy as np

    from .image_io import image_info, load_image
    from .resources import ScratchSpace

    for line in iter(requests.readline, b""):
        payload = b""
        try:
            request = json.loads(line)
            op = request.get("op")
            if op == "info":
                header = {"info": image_info(request["path"])}
                replies.write(json.dumps({**header, "size": 0}).encode() + b"\n")
            elif op == "preview":
                with ScratchSpace(scratch):
                    rgb, info = load_image(request["path"], request["background"], preview=True)
                    payload = memoryview(np.ascontiguousarray(rgb)).cast("B")
                    header = {"info": info, "shape": list(rgb.shape), "size": len(payload)}
                    replies.write(json.dumps(header).encode() + b"\n")
                    replies.write(payload)
                    del payload, rgb
            else:
                raise ValueError(f"Unknown decoder request: {op!r}")
        except Exception as error:
            message = str(error) or type(error).__name__
            replies.write(json.dumps({"error": message, "size": 0}).encode() + b"\n")
        replies.flush()


def main() -> int:
    scratch = Path(sys.argv[1])
    # Protect the binary protocol: anything a library prints goes to stderr.
    replies_fd = os.dup(1)
    os.dup2(2, 1)
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(0, os.O_BINARY)
        msvcrt.setmode(replies_fd, os.O_BINARY)
    sys.stdout = sys.stderr
    with os.fdopen(replies_fd, "wb") as replies:
        _serve(sys.stdin.buffer, replies, scratch)
    return 0  # The GUI closed our stdin.


if __name__ == "__main__":
    raise SystemExit(main())
