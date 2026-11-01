# RTX HDR Image Studio

A local Windows desktop application that applies NVIDIA TrueHDR to SDR still images, previews the result in native HDR, and exports verified FP16 linear scRGB JPEG XR (`.jxr`) files.

Created with **OpenAI Codex (ChatGPT)** under the direction of **TeddyWEinzbern**. This is an independent community project. See [AUTHORS.md](AUTHORS.md).

![English interface with a generated gradient and SDR comparison](docs/interface.png)

## Features

- English GUI with drag-and-drop, batch processing, presets, and cancellation.
- Peak luminance, contrast, saturation, middle gray, debanding, exposure, and GPU selection.
- Native Direct3D 11 FP16/scRGB HDR preview, split comparison, and SDR tone-mapped fallback.
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

## Use

1. Choose **Add images**, or drop PNG/JPEG/WebP/BMP/TIFF files into the window.
2. Choose a preset or adjust the parameters.
3. Choose **Generate preview**. Drag the divider or choose Original/Processed.
4. Leave **Automatic HDR** selected for native HDR, or select **SDR tone-mapped**.
5. Choose **Export JXR** to export the queue with the current settings.

Parameter changes do not automatically re-run inference; an outdated preview is labeled. Preview caches use a maximum dimension of 1600 pixels, while inference and export preserve the source dimensions.

| Parameter | Range | Default |
| --- | --- | --- |
| Peak luminance | 400–2000 nit | 650 |
| Contrast | 0–200 | 100 |
| Saturation | 0–200 | 100 |
| Middle gray | 10–100 | 50 |
| Debanding | On/off | On |
| Input exposure | -3 to +3 EV | 0 |
| Input transfer | sRGB / gamma 2.2 | sRGB |
| Alpha background | Black / white | Black |
| GPU index | 0–15 | 0 |

For multiple GPUs, enter the CUDA device index. Target peak does not determine actual display brightness. Presets are JSON files. A `.settings.json` sidecar records each export's processing parameters, source path, color profile description, GPU, and statistics.

Shortcuts: **Ctrl+O** adds images, **Ctrl+R** generates a preview, and **Ctrl+E** exports the queue. Repeated filenames gain a numeric suffix. Cancel stops the worker and keeps completed files.

## Color pipeline and limitations

Input ICC profile → sRGB RGB8 → linear-light exposure → Rec.709/gamma 2.2 input → NVIDIA TrueHDR RGB10A2 BT.2020/PQ → absolute luminance → linear scRGB → FP16 JXR.

- scRGB uses `1.0 = 80 nit`. Negative channels and values above 1 are preserved; they are needed for wide gamut and HDR. Native preview uses an FP16 swap chain with linear scRGB color space. The original side is adjusted to the Windows SDR reference-white level.
- This is an SDR enhancement tool, not a P3 container converter or HDR source editor. NVIDIA's RGB8 input path does not retain the full precision of 16-bit SDR sources. Invalid or unsupported ICC profiles produce an error.
- Windows HDR wallpaper rendering varies. In testing, a 5120×2880 JXR appeared gray while a 2560×1600 version displayed correctly; matching the image to the display resolution may help.
- Viewers, wallpaper paths, and screenshots may tone-map or lose HDR even when the exported JXR validates correctly.
- Display output depends on the panel, calibration, Windows color management, and drivers. The application does not alter system display settings.
- Processing is local; the application contains no upload or telemetry code.

## Files and logs

Default exports: `Pictures\RTX HDR Image Studio` under the current user's home directory. Choose another output directory in the UI.

Logs and preview caches are stored in `%LOCALAPPDATA%\RTX HDR Image Studio\cache` and may contain source filenames and paths. Set `RTX_HDR_STUDIO_HOME` to use another location, and review logs before sharing them.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md), [architecture](docs/architecture.md), and [testing](docs/testing.md).

## License and attribution

Project code and documentation are available under the [MIT License](LICENSE). See [THIRD_PARTY.md](THIRD_PARTY.md) for third-party components.
