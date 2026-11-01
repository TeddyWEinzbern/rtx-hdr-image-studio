"""Qt worker lifecycle and cancellation; GPU work lives in a separate process."""

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..pipeline import EVENT_PREFIX
from ..runtime import worker_environment


class JobRunner(QThread):
    event = Signal(dict)

    def __init__(self, request: dict, parent=None):
        super().__init__(parent)
        self.request = request
        self.outcome: dict = {}
        self.log_path = Path(request["job_dir"]) / "worker.log"
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._process = None

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()

    def run(self) -> None:
        final = None
        try:
            directory = Path(self.request["job_dir"])
            directory.mkdir(parents=True, exist_ok=True)
            request_path = directory / "request.json"
            request_path.write_text(json.dumps(self.request), encoding="utf-8")
            if self._cancelled.is_set():
                return
            with self._lock:
                self._process = subprocess.Popen(
                    [sys.executable, "-m", "rtx_hdr_studio.worker", str(request_path)],
                    cwd=directory,
                    env=worker_environment(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            if self._cancelled.is_set():
                self.cancel()
            with self.log_path.open("w", encoding="utf-8") as log:
                for line in self._process.stdout:
                    log.write(line)
                    log.flush()
                    if line.startswith(EVENT_PREFIX):
                        try:
                            event = json.loads(line[len(EVENT_PREFIX) :])
                        except ValueError:
                            continue
                        self.event.emit(event)
                        if event.get("event") in ("finished", "error"):
                            final = event
            code = self._process.wait()
            self.outcome = final or {
                "event": "error",
                "message": f"Worker exited unexpectedly ({code}). See the job log.",
            }
        except Exception as error:
            self.outcome = {"event": "error", "message": str(error)}
        finally:
            # Also reap the process if opening/writing a log or protocol parsing failed.
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                self._process.wait()
            # Terminated workers cannot run their mapping cleanup. This job's
            # unique directory is owned by the runner; leave completed caches.
            directory = Path(self.request["job_dir"])
            for scratch in directory.glob("image-*"):
                if scratch.is_dir() and not scratch.is_symlink():
                    shutil.rmtree(scratch, ignore_errors=True)
            if self._cancelled.is_set():
                self.outcome = {"cancelled": True}
