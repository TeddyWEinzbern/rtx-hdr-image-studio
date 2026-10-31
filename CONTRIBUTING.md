# Contributing

Use English for code identifiers, comments, documentation, issue reports, and the interface. Use Python 3.12 and keep the processing layer independent of Qt and GPU imports at module import time.

Install development dependencies manually in your environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -m "not gpu and not native"
.\.venv\Scripts\python.exe -m build
```

Install the `gpu` extra separately for RTX tests. See [testing](docs/testing.md). Report the OS, Python version, GPU model, driver version, processing settings, and the actual failure. Review logs for private paths and use a shareable synthetic image when possible.

Keep output dimensions unchanged. Do not add installers, automatic package downloads, telemetry, or changes to system HDR/ACM/wallpaper settings. Validate input settings before GPU initialization. Preserve native SDK output lifetime synchronization, full linear HDR range, subprocess cancellation, and non-overwriting export behavior.

Add tests for behavioral changes, especially color conversion, validation, export integrity, and cleanup after failure. Do not make CI depend on an NVIDIA GPU. Declare AI assistance in your contribution when applicable. By contributing, you agree that your project-authored changes are distributed under the repository's MIT License.
