# Testing and evidence

## Version 1.2.1 validation (2026-11-02)

Version 1.2.1 fixes the findings of two code audits (security/stability/performance and correctness). It adds 92 CPU/UI tests (`test_engine.py`, `test_job_cache.py`, `test_decoder.py`, `test_composition.py`, new cases in `test_images_and_export.py`, and device-loss recovery in `test_preview_async.py`) and 2 Windows native tests (GPU-side split composition read back against the CPU reference, and device-loss fault injection).

| Check | Result |
| --- | --- |
| Non-Qt suites in a Linux container (NumPy 2.5, Pillow 12.3; a raw stand-in replaced imagecodecs for the JXR container) | 143 passed |
| `LatestTask`, `PreviewDevice` loss recovery and `JobRunner` cancellation with a minimal Qt stand-in | Passed |
| Audit reproduction: 16-bit grayscale PNG/TIFF `[0, 128, 255, 256, 16384, 32768, 65535]` | `[0, 0, 1, 1, 64, 128, 255]` (was `[0, 128, 255, 255, 255, 255, 255]`) |
| Audit reproduction: cancelled export through `JobRunner` | No `.rtx-hdr-*` file of the job left; another job's staging file untouched |
| Audit reproduction: closing during a 60 s decode | Whole process exits promptly with `DecoderInterrupted` |
| Lookup tables vs float formulas (sRGB/gamma 2.2, exposure −3…+3 in 0.05 steps) | 0 mismatches; 4K preview linearization 2391 ms → 30 ms in the container |
| GPU composition plan vs 1.2.0 CPU frame (3 modes × 6 split positions × 3 scale factors) | Bit-identical |
| Maximum \|scRGB\| over the full RGB10A2 PQ cube | 207.6 (FP16 limit 65504) |
| Windows offscreen CPU/UI suite with real Qt and imagecodecs | **215 passed**, 9 deselected |
| Real NVIDIA inference, C/Python equivalence, worker preview and verified JXR export | **5 passed**, 219 deselected |
| Windows native FP16 readback/resize, full-screen viewing, GPU composition, device-loss injection | **4 passed**, 220 deselected |
| Idle live-owner cache retention, stale dead-owner cleanup, quick-selection delayed interruption | Passed in the Windows CPU/UI suite |
| Isolated wheel and source-distribution builds | Passed |
| Ruff lint/format | Passed |

The earlier container could not install PySide6 or imagecodecs; its stand-in results above are retained as development history. The Windows results use the real dependencies: NumPy 2.3.4, Pillow 12.3.0, PySide6-Essentials 6.10.1, and imagecodecs 2026.10.10. GPU validation used the RTX 3070 Ti Laptop GPU, driver 621.01, and VFX SDK 1.3.0. Native tests ran with Windows HDR enabled. Device-loss recovery was checked by injecting a failed `Present` HRESULT into the real native surface; no system driver reset was forced. Buffer readback and automated full-screen tests do not establish physical HDR appearance.

Release validation also found and fixed two edge cases: startup cleanup must retain old caches belonging to an idle live instance, and selecting another image before the one-second decode grace period expires must schedule a later interruption check. The cache test uses a real child process, verifies its idle cache is retained, then terminates that child and verifies stale cleanup.

Reproduce the Windows checks with:

```powershell
.\.venv\Scripts\python.exe -m pip install ".[gpu,dev]"
.\.venv\Scripts\python.exe -m ruff check . ; .\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -m "not gpu and not native"
$env:RTX_HDR_RUN_GPU = "1"; .\.venv\Scripts\python.exe -m pytest -m gpu
$env:QT_QPA_PLATFORM = "windows"; $env:RTX_HDR_RUN_NATIVE = "1"; .\.venv\Scripts\python.exe -m pytest -m native
```

The audits' remaining low-priority suggestions were deliberately not changed in 1.2.1: display-state polling (`QueryDisplayConfig` every 1.5 s; measure first), pinning GitHub Actions to commit SHAs with a dependency lock file, and removing the GUI-thread QImage/QPixmap round trips on image selection (one-off cost per selection, not per frame).

## Version 1.2.0 validation (2026-11-02)

| Check | Result |
| --- | --- |
| CPU/UI suite | 123 passed |
| Real NVIDIA inference, C/Python equivalence, preview and verified JXR export | 5 passed |
| Windows native FP16 readback/resize and full-screen HDR viewing/exit | 2 passed |
| HDR400/HDR600/HDR1000/HDR1000 Highlight saturation applied in the UI | 150 for all four |
| Ruff lint/format and isolated wheel/sdist builds | Passed |
| Built package version, 26 Python modules and release-note contents | Verified |

The current source/package version is 1.2.1. The measurements below retain their original development context; the front-end pixel ceiling remains distinct from available processing resources.

## Preview anti-aliasing validation (2026-11-02)

The SDR painter previously enabled primitive-edge anti-aliasing without smooth image transforms. Merely enabling Qt's bilinear transform still left high-frequency moire. `test_resampling.py` checks the actual SDR canvas against a one-pixel checkerboard, low-pass HDR downsampling without range clipping, unscaled sample equality, cropped Fill images, strip-boundary equivalence, and reuse of final-size pixels while moving the divider/changing views.

On a 1280×1024 black/white checkerboard rendered at 281×263, interior grayscale standard deviation was 127.50 for nearest-neighbor, 43.36 for Qt's smooth transform, and 0.48 for the final Lanczos cache. The near-uniform gray target is specific to this above-Nyquist test pattern; it is not a general image-quality score.

Local median single-image float32 timings at 3840×2160 → 640×360 were 114ms for the previous bilinear path, 151ms for direct Lanczos, and 123ms for the selected area-prefilter + Lanczos path. Bounded 100MP → 2160-square resampling took 3.28s in a separate synthetic check. These timings are hardware-dependent. Expensive scaling runs off the UI thread, and split dragging does not resample. Inference and full-resolution export buffers are not filtered.

Validation: 123 CPU/UI tests and both Windows native HDR tests passed. A real 100MP pipeline run with the new preview filter completed in 24.30s with 2.95GiB peak process working set, including original-size JXR encode/decode verification. Preview generation now does more filtering work than the earlier bilinear measurement; divider repainting reuses cached results. The exported JXR remained byte-identical to the earlier full-resolution export.

Primary references: [Qt painter render hints](https://doc.qt.io/qt-6/qpainter.html#RenderHint-enum) and [Pillow resize/reducing_gap](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.resize).

## Large-image development validation (2026-11-02)

On an RTX 3070 Ti Laptop (8GiB), driver 621.01, VFX SDK 1.3.0:

| Real PNG input | Complete preview and verified original-size JXR | Pipeline time | Process peak working set |
| --- | --- | ---: | ---: |
| 10000 × 10000 (100MP) | Passed | 18.69s | 2.95GiB |
| 20000 × 20000 (400MP) | Passed | 69.52s | 10.92GiB |

The prior 100MP Python-path measurement was 30.57s and 10.27GiB on this machine. This is a local comparison, not a universal speed or memory guarantee. The final 100MP JXR was byte-identical to the prior export (SHA256 `dce2689dcd7820a9b7431b46e8f0953ca899ecab27ae2b8e6bffb7def56b13dc`).

The 30720-square front-end boundary passes header validation. The initial full pipeline attempt reached the isolated test's 2GiB commit reserve during inference; after strengthening admission to check full GPU commitment rather than only shared-memory overflow, the same input was rejected before large GPU allocations with a RAM/commit-headroom error. Full application export at 943.72MP is therefore **not claimed** on the available system resources. The earlier native SDK-only 943.72MP success is a separate result.

CPU/UI coverage includes 118 passing tests. Hardware checks compare the native engine against the Python API for four parameter sets at two odd image sizes and exercise real worker preview/export. The 400MP complete pipeline exceeds the old Python transfer boundary without splitting inference into tiles. Two Windows-platform native tests passed, covering FP16 readback/resize and full-screen HDR viewing/exit. Layout checks cover the header at normal and minimum window sizes.

For the synthetic sources, offscreen event-loop probes during original-preview loading measured 0.41s total / 35ms maximum timer interval at 100MP, and 1.60s total / 246ms maximum interval at 943.72MP. These are CPU preview responsiveness measurements, not a guarantee of physical display latency. Final resource preflight rejected the insufficient-commit 943.72MP processing request in a 0.58s isolated probe, without decoding pixels or allocating full-size GPU buffers.

## Version 1.1.2 validation (2026-11-01)

| Check | Result |
| --- | --- |
| CPU/UI suite with the offscreen platform | 103 passed |
| Dropdown interaction and geometry on the Windows platform | 12 passed |
| Native Direct3D buffer and full-screen HDR viewing | 2 passed |
| Real NVIDIA worker preview and JXR export | 1 passed |
| Ruff lint, formatting, and package builds | Passed |

Dropdown regression checks confirm that the popup stays at its final position immediately after opening and after the native animation interval, both below the control and above it near the screen bottom. Available-screen-space checks remain enabled. Status tests check the merged readiness/peak text, red outdated highlighting, matching-result recovery, and switching to an image without a preview. The README screenshot uses synthetic SDR data; it does not establish physical HDR appearance.

## Version 1.1.1 validation (2026-11-01)

| Check | Result |
| --- | --- |
| CPU/UI suite with the offscreen platform | 100 passed |
| Dropdown interaction and geometry on the Windows platform | 10 passed |
| Native Direct3D buffer and full-screen HDR viewing | 2 passed |
| Real NVIDIA worker preview and JXR export | 1 passed |
| Ruff lint, formatting, and package builds | Passed |

The native full-screen test verifies that the exit hint is suppressed after its first automatic timeout during a run. CPU/UI tests also cover early exit, re-entry, and resetting the in-memory state for a new application window. These checks do not establish physical HDR appearance. The README screenshot uses synthetic SDR data rather than user artwork.

## CPU tests

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not gpu and not native"
```

The suite checks known PQ anchors and matrix behavior, settings validation, EXIF/ICC/alpha loading, FP16 negative/highlight preservation, output collisions, original dimensions, preview caches, and batch continuation/cleanup using an injected engine. GUI tests use Qt's offscreen platform. These tests do not claim to validate real HDR appearance.

Asynchronous-preview tests cover a responsive event loop during delayed decoding, coalesced requests, stale-result rejection, off-thread device initialization and reuse, and HDR sample preservation. Controlled job events verify that processing closes only the affected source's full-screen viewer, forces Original, blocks button/direct/double-click entry, follows batch progress, and restores controls after completion or cancellation while leaving other sources usable.

## Real GPU integration

Install `.[gpu]`, then explicitly opt in:

```powershell
$env:RTX_HDR_RUN_GPU = "1"
.\.venv\Scripts\python.exe -m pytest -m gpu -v
```

The test uses synthetic input, actual NVIDIA TrueHDR, a complete worker process, preview generation, and export. The GPU and driver must be compatible; driver/SDK failures must not be interpreted as proof that all RTX hardware is unsupported.

## Native display buffer

```powershell
$env:RTX_HDR_RUN_NATIVE = "1"
$env:QT_QPA_PLATFORM = "windows"
.\.venv\Scripts\python.exe -m pytest -m native -v
```

The buffer test creates its own small Windows surface and reads back its own GPU buffer. It checks exact FP16 values including negative channels and 1000-nit values, resizing, and presentation. A second test opens the application's full-screen viewer using synthetic images, checks Original/Split/Processed output before presentation, and exercises double-click entry/exit, the one-time hint, Esc, and window deactivation. The full-screen test requires Windows HDR enabled and is skipped otherwise. These tests do not capture the desktop or change display settings, and buffer readback does not establish physical HDR appearance.

## Large-image capacity checks

`test_capacity.py` checks the exact 943,718,400-pixel header boundary without allocating a huge image, finite Pillow protection, mapped-buffer cleanup, separable filtering, memory-bar thresholds/overflow, and the Windows processing mutex. GPU tests compare native C output with the Python API over multiple parameter sets and odd dimensions, including changing dimensions on a reused engine. These tests do not claim physical HDR appearance or every possible large-image shape.

For capacity testing, run real images above 40MP, around 2^28 pixels, and toward 30720-square in isolated workers with RAM/commit reserves and timeouts. Check original-size JXR decode equality, bounded previews, cancellation cleanup and post-job resource release. The maximum accepted pixel count is a front-end policy; resource checks can reject smaller inputs. Check the upper-right estimate while switching focus during a batch: it must follow the selected image without adding the active image or entire queue. A second job must be rejected, including from another application instance. Check long filenames, minimum window size and high-DPI scaling.

## Manual checks before release

Open every dropdown at 100%, 150%, and 200% display scaling. Its popup must match the control's width and left edge, rounded border, font, and row height. Check first and last selections: the popup must open at its final calculated position below or above the control, staying inside the available screen. It must not jump after opening or after an animation delay. Long lists must scroll. Check arrow keys/Enter, mouse selection, Esc cancellation, outside-click dismissal, reopening, and secondary displays. The dropdown arrow must be included in installed packages and remain visible without an SVG plugin. Preview status must combine readiness and image peak; a parameter change must keep the peak visible, append (Outdated), and color the full status red. Regenerating with matching settings or selecting an image without a preview must clear the outdated highlight.

Generate a large preview and monitor the GUI while PNG/HDR data and the initial D3D device are prepared: window movement, cancel, and closing must remain responsive. Rapidly select different images and resize/full-screen/close during preparation; old results must not overwrite the current image or reopen a closed surface. In a batch, verify that only the currently processed image loses mode/full-screen controls, that a matching full-screen view closes, and that the lock advances and clears on failure/cancellation. Include initial HDR startup, repeated regeneration, SDR fallback, and a near-40MP source. Record event-loop latency separately from total time until the HDR frame is ready.

Check bright selected rows in every dropdown and the image queue, and the active preview button after clicking modes or selecting an unprocessed image. Resize between the minimum window size and a wide screen: the three preview buttons must remain at the left with equal, stable widths; Fullscreen and its scaling selector must remain aligned on the right. Check full-screen Keep aspect ratio, Fill, Stretch, and No scaling in SDR and HDR. In Split view, drag horizontally with the left button: the original/processed boundary must follow, stay within the image when dragging beyond its edges, stop moving on release, and leave the main preview's divider unchanged. Dragging letterboxing, right-button dragging, and dragging Original/Processed views must not move the divider. Dragging must not restore the exit hint or interfere with double-click/Esc exit. No scaling must retain physical pixel dimensions on high-DPI displays, and fall back to aspect-ratio fit when either source dimension exceeds the screen.

On an HDR-enabled Windows display, generate a preview, compare both sides, move the divider, select Original/Processed, switch between automatic HDR and SDR, resize the window, and cancel a job. Check fallback on a non-HDR display if available. Re-run after changes to native COM layouts, GPU ownership, or color math.

Open Fullscreen using the blue button and by double-clicking the image in each comparison/display mode. Confirm the image fits without stretching and retains its current comparison state. A centered hint must appear until it completes a three-second display, then stay hidden on later entries during the same run, including after selecting another image. Exiting early must show it again on the next entry. Restarting must reset it without a saved preference. Mouse movement and single clicks must never restore it, including over the native HDR child surface. There must be no exit button. Check image double-click and Esc exit, Alt+Tab and another-window activation, repeated entry/exit, and closing the main window. Returning to the application must not reopen the preview or steal focus. Confirm Processed and Split view are disabled for an unprocessed source, enabled after generation, and disabled again when selecting another source without a result. Check different display scaling factors and opening on a secondary display. For a large landscape and portrait source, verify SDR and HDR caches stay within 3840 pixels wide and 2160 pixels high; exports retain the original dimensions.

Wallpaper results are separate from preview/buffer validation. Development A/B testing on one system found that a manually screen-sized image worked where the larger image did not. This project documents that observation and leaves image sizing to the user. Do not describe it as a universal Windows limit or a fixed export bug.

Do not upload private images, absolute local-path logs, caches, or generated sidecars as test evidence. Repository tests generate their own data in temporary directories.
