# Testing and evidence

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

## Manual checks before release

Open every dropdown at 100%, 150%, and 200% display scaling. Its popup must match the control's width and left edge, rounded border, font, and row height. Check first and last selections: the popup must open at its final calculated position below or above the control, staying inside the available screen. It must not jump after opening or after an animation delay. Long lists must scroll. Check arrow keys/Enter, mouse selection, Esc cancellation, outside-click dismissal, reopening, and secondary displays. The dropdown arrow must be included in installed packages and remain visible without an SVG plugin. Preview status must combine readiness and image peak; a parameter change must keep the peak visible, append (Outdated), and color the full status red. Regenerating with matching settings or selecting an image without a preview must clear the outdated highlight.

Generate a large preview and monitor the GUI while PNG/HDR data and the initial D3D device are prepared: window movement, cancel, and closing must remain responsive. Rapidly select different images and resize/full-screen/close during preparation; old results must not overwrite the current image or reopen a closed surface. In a batch, verify that only the currently processed image loses mode/full-screen controls, that a matching full-screen view closes, and that the lock advances and clears on failure/cancellation. Include initial HDR startup, repeated regeneration, SDR fallback, and a near-40MP source. Record event-loop latency separately from total time until the HDR frame is ready.

Check bright selected rows in every dropdown and the image queue, and the active preview button after clicking modes or selecting an unprocessed image. Resize between the minimum window size and a wide screen: the three preview buttons must remain at the left with equal, stable widths; Fullscreen and its scaling selector must remain aligned on the right. Check full-screen Keep aspect ratio, Fill, Stretch, and No scaling in SDR and HDR. In Split view, drag horizontally with the left button: the original/processed boundary must follow, stay within the image when dragging beyond its edges, stop moving on release, and leave the main preview's divider unchanged. Dragging letterboxing, right-button dragging, and dragging Original/Processed views must not move the divider. Dragging must not restore the exit hint or interfere with double-click/Esc exit. No scaling must retain physical pixel dimensions on high-DPI displays, and fall back to aspect-ratio fit when either source dimension exceeds the screen.

On an HDR-enabled Windows display, generate a preview, compare both sides, move the divider, select Original/Processed, switch between automatic HDR and SDR, resize the window, and cancel a job. Check fallback on a non-HDR display if available. Re-run after changes to native COM layouts, GPU ownership, or color math.

Open Fullscreen using the blue button and by double-clicking the image in each comparison/display mode. Confirm the image fits without stretching and retains its current comparison state. A centered hint must appear until it completes a three-second display, then stay hidden on later entries during the same run, including after selecting another image. Exiting early must show it again on the next entry. Restarting must reset it without a saved preference. Mouse movement and single clicks must never restore it, including over the native HDR child surface. There must be no exit button. Check image double-click and Esc exit, Alt+Tab and another-window activation, repeated entry/exit, and closing the main window. Returning to the application must not reopen the preview or steal focus. Confirm Processed and Split view are disabled for an unprocessed source, enabled after generation, and disabled again when selecting another source without a result. Check different display scaling factors and opening on a secondary display. For a large landscape and portrait source, verify SDR and HDR caches stay within 3840 pixels wide and 2160 pixels high; exports retain the original dimensions.

Wallpaper results are separate from preview/buffer validation. Development A/B testing on one system found that a manually screen-sized image worked where the larger image did not. This project documents that observation and leaves image sizing to the user. Do not describe it as a universal Windows limit or a fixed export bug.

Do not upload private images, absolute local-path logs, caches, or generated sidecars as test evidence. Repository tests generate their own data in temporary directories.
