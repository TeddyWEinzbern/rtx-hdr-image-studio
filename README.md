# RTX HDR Image Studio

A local Windows desktop application that applies NVIDIA TrueHDR to SDR still images, previews the result in native HDR, and exports verified FP16 linear scRGB JPEG XR (`.jxr`) files.

Created with **OpenAI Codex (ChatGPT)** under the direction of **TeddyWEinzbern**. This is an independent community project. See [AUTHORS.md](AUTHORS.md).

![English interface with a synthetic gradient in SDR Split view](docs/interface.png)

## Features

- Peak luminance, contrast, saturation, middle gray, debanding, exposure, and GPU selection.
- Native Direct3D 11 FP16/scRGB HDR preview, split comparison, SDR tone-mapped fallback, and full-screen viewing.
- EXIF orientation and embedded ICC input conversion to sRGB; explicit alpha compositing.
- Full-resolution FP16 JXR export with exact decoded-sample verification and collision-safe filenames.
- Separate GPU worker process, so a native SDK failure does not take down the interface.

## Hardware and software

| Component | Requirement |
| --- | --- |
| Operating system | **Windows 11 x64**; version 24H2 or later recommended |
| Python | **CPython 3.12 x64** |
| Processing GPU | NVIDIA **GeForce RTX 20/30/40/50-series** GPU supported by NVIDIA VFX TrueHDR |
| Driver | **R580 or later**, compatible with CUDA 13 |
| Display | SDR displays support processing and export; native HDR preview requires an HDR display with **Windows HDR enabled** |

See the [NVIDIA Windows requirements](https://docs.nvidia.com/maxine/vfx/latest/WindowsVFXSDK/GetStartedonWindows.html), [TrueHDR performance examples](https://docs.nvidia.com/maxine/vfx/latest/WindowsVFXSDK/PerformanceReference.html), and [CuPy installation guide](https://docs.cupy.dev/en/stable/install.html).

## Manual installation

Use PowerShell for the commands below.

1. Install [Python 3.12 x64](https://www.python.org/downloads/) and a compatible [NVIDIA graphics driver](https://www.nvidia.com/Download/index.aspx).
2. Download and extract a source ZIP from the [Releases page](https://github.com/TeddyWEinzbern/rtx-hdr-image-studio/releases) and open its directory in PowerShell, or clone the repository:

   ```powershell
   git clone https://github.com/TeddyWEinzbern/rtx-hdr-image-studio.git
   cd rtx-hdr-image-studio
   ```

3. Create an isolated environment and install the application and GPU dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install ".[gpu]"
   ```

   The GPU dependencies are large. A separate CUDA Toolkit is not required.

4. Launch:

   ```powershell
   python -m rtx_hdr_studio
   ```

   Use `pythonw -m rtx_hdr_studio` to launch without a console window.

### Dependencies

Dependencies are declared in [pyproject.toml](pyproject.toml). Install `.[gpu]` for GPU processing or `.` for the interface and CPU-testable components. Install only one CuPy distribution in an environment.

## Usage limits

- SDR PNG, JPEG, WebP, BMP, and TIFF inputs are limited to **943.72 megapixels** (width × height ≤ 943,718,400 pixels; 30720 × 30720 at the limit). This is an application limit, not a guarantee that every size or aspect ratio can be processed. Codec limits and available GPU memory, RAM, commit headroom, and scratch disk space also apply; larger images are rejected rather than downscaled.
- Processing is serial, including across application instances in the same Windows session. Large CPU buffers use temporary files in the cache; interruption removes the active job's scratch files after the worker stops. Very large sources can require tens of GiB of RAM and scratch storage, and may be slow to decode or export.
- The upper-right GPU memory estimate applies only to the focused image. Its fixed scale is the selected GPU's dedicated VRAM capacity. Demand above capacity is expected to use shared system memory; the estimate is approximate and does not guarantee successful allocation. Extreme shapes, other GPUs/SDK versions, and other applications can change actual usage.
- Parameter changes do not regenerate the preview automatically. An outdated preview shows the previous result; exports use the current settings.
- Preview caches fit within **3840 × 2160 pixels**, preserving aspect ratio without upscaling. Inference and export retain the source dimensions.
- Existing exports are never overwritten; filename collisions receive a numeric suffix. Cancellation keeps completed exports.

## Color pipeline and limitations

Input ICC profile → sRGB RGB8 → linear-light exposure → Rec.709/gamma 2.2 input → NVIDIA TrueHDR RGB10A2 BT.2020/PQ → absolute luminance → linear scRGB → FP16 JXR.

- scRGB uses `1.0 = 80 nit`. Negative channels and values above 1 are preserved; they are needed for wide gamut and HDR. Native preview uses an FP16 swap chain with linear scRGB color space. The original side is adjusted to the Windows SDR reference-white level.
- This is an SDR enhancement tool, not a P3 container converter or HDR source editor. NVIDIA's RGB8 input path does not retain the full precision of 16-bit SDR sources. Invalid or unsupported ICC profiles produce an error.
- Windows HDR wallpaper rendering varies. In testing, a 5120×2880 JXR appeared gray while a 2560×1600 version displayed correctly; matching the image to the display resolution may help.
- Viewers, wallpaper paths, and screenshots may tone-map or lose HDR even when the exported JXR validates correctly.
- Display output depends on the panel, calibration, Windows color management, and drivers. The application does not alter system display settings.
- Target peak luminance is a processing parameter, not a guarantee of actual image or display brightness.
- Processing is local; the application contains no upload or telemetry code.

## Files and logs

Default exports: `Pictures\RTX HDR Image Studio` under the current user's home directory. Choose another output directory in the UI.

A `.settings.json` sidecar records each export's processing parameters, source path, color profile description, GPU, and statistics.

Logs and preview caches are stored in `%LOCALAPPDATA%\RTX HDR Image Studio\cache` and may contain source filenames and paths. Set `RTX_HDR_STUDIO_HOME` to use another location, and review logs before sharing them.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md), [architecture](docs/architecture.md), and [testing](docs/testing.md).

## License and attribution

Project code and documentation are available under the [MIT License](LICENSE). See [THIRD_PARTY.md](THIRD_PARTY.md) for third-party components.
