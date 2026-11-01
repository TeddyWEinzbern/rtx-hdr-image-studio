# Changelog

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
