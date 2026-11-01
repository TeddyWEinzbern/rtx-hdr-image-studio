# Changelog

## 1.2.1 - 2026-11-02

Security, stability, and performance fixes from the 2026-11-02 code audits.

- Security: restrict Pillow's content sniffing to the PNG, JPEG, WebP, BMP, and TIFF decoders, so a renamed EPS/PSD/FITS/PDF file can no longer reach Ghostscript or other high-risk decoders. Upgrade Pillow to 12.3.0 (CVE-2026-25990, CVE-2026-42311, CVE-2026-40192 and related fixes).
- Fix unsigned 16-bit grayscale PNG/TIFF input being clipped to white: values are now scaled from the full 0–65535 range in previews and processing. Signed-integer and floating-point images are rejected with a clear message instead of being clipped.
- Decode source images in killable helper processes. A native decoder crash no longer closes the window, a slow decode of an image you have moved away from is abandoned, and closing the window no longer leaves the process running until a large decode finishes.
- Delete preview/job caches that are no longer referenced, all of a session's caches on exit, and crash leftovers older than 24 hours at start-up (previously every preview and export left ~60 MiB or more behind permanently). Caches with a live recorded owner are retained even after a day of inactivity.
- Remove unfinished `.rtx-hdr-*` export files from the output folder after a cancelled or terminated export; files of other jobs and finished exports are untouched.
- Native HDR preview uploads each frame pair to the GPU once; repaints, including every mouse move while dragging the divider, are GPU copies plus a small divider/hint upload instead of a full FP16 frame copy and upload (about 63 MiB per repaint at 4K).
- Recover the native HDR preview after a graphics driver reset or device removal by rebuilding the shared Direct3D device, instead of staying in SDR fallback until restart; repeated losses keep the SDR fallback with an explanation.
- Report the original NVIDIA error with the file name when GPU processing fails, instead of a secondary CUDA synchronization error.
- Prepare TrueHDR input and linearize preview originals with exact 256-entry lookup tables (byte-identical results; 4K preview linearization drops from seconds to tens of milliseconds). Collect HDR statistics during conversion and skip the redundant export range scan for NVIDIA output, saving two full passes over large images.
- Start worker and decoder processes with `python -P`; rotate `application.log` at 1 MiB with three backups.
- Credit Claude AI (Anthropic) alongside OpenAI Codex (ChatGPT) in the AI disclosure.

## 1.2.0 - 2026-11-02

- Set saturation to 150 for HDR400, HDR600, HDR1000, and HDR1000 Highlight presets.
- Fix pixelated SDR downscaling and improve HDR/cache resampling with scale-aware Lanczos-3 and area prefiltering. Prepare final-size SDR images in the background and reuse them for divider/view changes; preserve the no-scaling path.
- Raise the application input limit to 943,718,400 pixels and call NVIDIA's C API directly, bypassing the Python binding's large-image input-transfer failure.
- Add a focused-image GPU memory estimate at the previewer's upper right, with fixed dedicated-VRAM capacity, pressure colors and shared-memory overflow.
- Prevent simultaneous processing jobs across application instances in the same Windows session.
- Reduce large-image memory pressure with strip-based color preparation/readback, mapped scratch storage, bounded resampling/statistics, preview-resolution tone mapping and mapped exact JXR verification. Check RAM/commit/disk headroom and clean interrupted scratch storage after the worker stops.
- Keep header metadata queries independent of PNG decoding, and use reduced JPEG decoding and a single original-preview decode thread.

## 1.1.2 - 2026-11-01

- Calculate the dropdown's final position before display, retaining screen-space checks for opening above or below and shortening long lists. Skip the native opening animation to prevent it from moving the popup back to a previous position.
- Merge readiness, image peak, and outdated-preview status into one line. Outdated previews retain their peak reading, append `(Outdated)`, and highlight the full status in red.
- Remove the separate peak panel, refresh the synthetic README screenshot, and remove the README's current-source-version paragraph.

## 1.1.1 - 2026-11-01

- Show the full-screen exit hint until it has disappeared automatically once per application run. Early exit keeps the hint available; restarting resets it without saving a preference.
- Fix dropdown borders, arrows, rounded popups, matching fonts and row heights, and alignment below or above the control. Preserve mouse and keyboard selection, scrolling, and Esc/outside-click dismissal.
- Simplify interface descriptions, use equal-width Original / Processed / Split view buttons, and consolidate the FP16 linear scRGB JXR format description below the application title.
- Package the dropdown arrow with both the wheel and source distribution.
- Refresh the README interface screenshot using synthetic SDR data and document the final validation results.

## 1.1.0 - 2026-11-01

- Add full-screen SDR/native HDR viewing with double-click, Esc, focus-loss exit, adjustable split comparison, and aspect-ratio fit, Fill, Stretch, and physical-pixel No scaling modes.
- Increase preview cache bounds to 3840 × 2160 while retaining full source dimensions for inference and export.
- Move preview decoding, HDR preparation, frame resizing, and device initialization off the GUI thread; reuse rendering resources and discard stale background results.
- Restrict preview/full-screen controls only for the image currently being processed. Switch successful new previews to Split view.
- Add brighter selection highlights, compact preview controls, and HDR400, HDR600, HDR1000, and HDR1000 Highlight presets.

## 1.0.0

- Initial public release. See [the original release notes](docs/releases/v1.0.0.md).
