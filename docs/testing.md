# Testing and evidence

## CPU tests

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not gpu and not native"
```

The suite checks known PQ anchors and matrix behavior, settings validation, EXIF/ICC/alpha loading, FP16 negative/highlight preservation, output collisions, original dimensions, preview caches, and batch continuation/cleanup using an injected engine. GUI tests use Qt's offscreen platform. These tests do not claim to validate real HDR appearance.

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
.\.venv\Scripts\python.exe -m pytest -m native -v
```

The test creates its own small Windows surface and reads back its own GPU buffer. It checks exact FP16 values including negative channels and 1000-nit values, resizing, and presentation. It does not capture the desktop or change display settings.

## Manual checks before release

On an HDR-enabled Windows display, generate a preview, compare both sides, move the divider, select Original/Processed, switch between automatic HDR and SDR, resize the window, and cancel a job. Check fallback on a non-HDR display if available. Re-run after changes to native COM layouts, GPU ownership, or color math.

Wallpaper results are separate from preview/buffer validation. Development A/B testing on one system found that a manually screen-sized image worked where the larger image did not. This project documents that observation and leaves image sizing to the user. Do not describe it as a universal Windows limit or a fixed export bug.

Do not upload private images, absolute local-path logs, caches, or generated sidecars as test evidence. Repository tests generate their own data in temporary directories.
