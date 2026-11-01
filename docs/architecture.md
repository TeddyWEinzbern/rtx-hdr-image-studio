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

`LatestTask` runs widget-free work in bounded background pools. Each task retains one running request and only its newest pending replacement, with generation checks before publishing results on the GUI thread. PNG decoding uses QImage; HDR loading/validation, float32 original linearization, and full-frame resizing happen in background jobs. The GUI commits QPixmaps and presents already prepared frames. Data and frame jobs are cancelled logically on replacement or shutdown, so stale work cannot reactivate an old image or a closed window.

`PreviewDevice` initializes a D3D11 device in a separate background pool, then transfers exclusive immediate-context use to the GUI thread. Main and full-screen surfaces share those device resources, while owning separate HWND swap chains. Updating image content suspends a surface without destroying its presenter. Closing surfaces releases swap chains first; closing their owner releases the shared device after all surfaces and preview tasks are stopped. Pending initialization discarded after shutdown releases its own unused resources.

Progress messages include the source path. The window tracks the current processing source independently of the selected source. Only the active source is forced to Original, barred from mode/full-screen changes, and removed from full-screen viewing. The queue remains usable during a batch; completed and not-yet-processed sources retain their normal controls. Terminal file events and job cancellation/failure release that restriction.

Preview caches fit inside 3840 × 2160 without upscaling. The full-screen button and image double-click open a separate comparison canvas with a snapshot of the current images, mode, and divider position. A centered exit hint is painted into the SDR canvas or alpha-blended into the FP16 HDR frame in linear light at the display's SDR white level. This avoids stacking a raster widget above the native child HWND or applying SDR opacity effects to the HDR image. A one-shot timer hides the hint after three seconds and signals the owner to suppress it for the rest of the current run. Closing early leaves the hint eligible on the next entry. The owner keeps this state in memory only; a new application run resets it. Mouse activity does not restart it. Image double-click, Esc, window/application deactivation, and owner shutdown close the viewer and release its timers and native renderer. Generated-view buttons are enabled only when the selected image has a processed preview.

Exports preserve source dimensions and pixel format policy. Filename collision handling and same-directory staging avoid partial or overwritten output. Metadata sidecars are best-effort and do not invalidate an already successful JXR export. Logs/caches live outside the installed package and are never installed into the repository.

Full-screen Fill uses centered aspect-preserving cover geometry shared by SDR and HDR. HDR frame preparation resizes only the visible source crop, avoiding oversized intermediate buffers for extreme aspect ratios. Divider dragging is clamped to the visible image area. Successful file events mark that source for a one-time switch to Split view after its new preview loads; completion of another source leaves the selected view untouched. Starting another processing pass discards any pending switch for that source.

Qt SDR drawing, native HDR composition, and image hit testing share physical-pixel placement calculations. Full-screen scaling can fit with aspect ratio, stretch, or retain the preview's pixel dimensions; actual-size images that exceed either screen dimension fall back to fit. This avoids treating Qt logical pixels as image pixels at high display scaling factors. Preview buttons reflect the effective visible mode, including Original when no generated result is available.

In full-screen Split view, a left-button drag starting inside the image updates the viewer's divider without changing the main canvas or restarting the hint timer. The divider is constrained to the displayed image, including letterboxed actual-size previews. The native child forwards press, move, release, and double-click events to the same controller used by the SDR canvas.

Dropdowns retain Qt's selection handling and calculate a final popup rectangle before showing the list. The opening call temporarily disables Qt's combo animation and paints only after final placement, then restores the previous application animation flag. Available screen space determines whether the list opens below or above, and constrains its width and height if necessary. The preview status combines HDR/SDR readiness with the selected result's image peak; settings mismatch appends (Outdated) and applies a red text style. There is no separate image-peak panel.
