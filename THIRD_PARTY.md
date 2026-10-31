# Third-party components

The MIT License covers project-authored source and documentation. It does not replace dependency licenses. Dependencies are obtained by the user through their package manager and are not bundled in this repository.

| Component | Purpose | Upstream |
| --- | --- | --- |
| NVIDIA nvidia-vfx / Maxine | TrueHDR inference | [NVIDIA VFX Python](https://docs.nvidia.com/maxine/vfx-python/latest/index.html) |
| NVIDIA CUDA runtime / NVRTC | CUDA runtime support | [NVIDIA CUDA](https://developer.nvidia.com/cuda-toolkit) |
| CuPy | CUDA array interchange and host copy | [CuPy](https://cupy.dev/) |
| CUDA Pathfinder | CUDA library discovery | [NVIDIA CUDA Python](https://nvidia.github.io/cuda-python/) |
| PySide6 / Qt / Shiboken | GUI and native child windows | [Qt for Python](https://doc.qt.io/qtforpython-6/) |
| NumPy | Color processing and arrays | [NumPy](https://numpy.org/) |
| Pillow / LittleCMS | Input images, ICC conversion, and preview filtering | [Pillow](https://python-pillow.github.io/) |
| imagecodecs / jxrlib | JPEG XR encoding and decoding | [imagecodecs](https://github.com/cgohlke/imagecodecs) |
| pytest / Ruff / build / setuptools | Development and packaging | Respective package distributions |

Review each installed distribution's license files and upstream terms, especially NVIDIA runtime/SDK terms and Qt/PySide licensing, before redistributing a compiled or bundled application. This source release does not grant redistribution rights to proprietary dependencies. Windows Direct3D, DXGI, WIC, and display APIs are provided by Windows; no Windows system DLLs are redistributed here.

The display presenter and color pipeline were adapted from this project's earlier local prototype, also developed with Codex. No user artwork, NVIDIA screenshots, private logs, copied system fonts, or SDK sample assets are included.
