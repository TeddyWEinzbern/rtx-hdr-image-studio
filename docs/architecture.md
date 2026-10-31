# Architecture

The package uses the `src/` layout so tests do not accidentally import an unrelated checkout. Installation uses declarative `pyproject.toml` metadata; there is no custom setup code or dependency installer.

| Module | Responsibility |
| --- | --- |
| `settings.py` | Immutable settings; strict validation and JSON boundary |
| `color.py` | Transfer functions, PQ decoding, primaries conversion, tone mapping, statistics |
| `image_io.py` | EXIF/ICC/alpha input handling and reduced preview caches |
| `engine.py` | NVIDIA adapter, delayed GPU imports, DLPack ownership/synchronization |
| `export.py` | Exact FP16 verification and collision-safe publication |
| `pipeline.py` | Per-file orchestration; engine injection for CPU tests; batch failure isolation |
| `worker.py` | Subprocess JSON protocol and top-level failure reporting |
| `runtime.py` | User-data directories and discovery of already-installed CUDA DLLs |
| `graphics/` | Read-only Windows display detection and native D3D11 FP16 presentation |
| `ui/` | English Qt window, parameter controls, comparison canvas, subprocess lifecycle |

The GUI never performs inference on its event-loop thread. `JobRunner` starts the same Python environment as a subprocess and passes a JSON request file. Structured progress uses the `@HDRJSON:` prefix; all other output goes to a local job log. The GUI finishes a job only after the thread has exited. Cancellation terminates and reaps the worker; window shutdown waits for cleanup.

The pipeline accepts an `HdrEngine` protocol and factory, allowing deterministic CPU-only tests without pretending to validate NVIDIA inference. The adapter synchronizes the CUDA producer, imports the raw SDK-owned DLPack capsule, and completes a host copy before the next effect run or close.

Native preview uses a separate opaque child HWND. FP16 linear scRGB values are uploaded directly to a D3D11 flip-model swap chain. The CPU prepares scaled comparison frames in linear light; export never uses those scaled buffers. A display-state timer distinguishes HDR from SDR/ACM and adjusts the original side to the system SDR white level. Rendering failures fall back to the standard Qt SDR preview.

Exports preserve source dimensions and pixel format policy. Filename collision handling and same-directory staging avoid partial or overwritten output. Metadata sidecars are best-effort and do not invalidate an already successful JXR export. Logs/caches live outside the installed package and are never installed into the repository.
