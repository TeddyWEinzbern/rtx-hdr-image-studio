# Changelog

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
