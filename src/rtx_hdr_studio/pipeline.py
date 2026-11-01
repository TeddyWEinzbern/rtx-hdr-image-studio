"""Batch orchestration, injectable engine, and a small JSON worker protocol."""

import json
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .color import hdr_statistics, sdr_preview
from .engine import HdrEngine, NvidiaEngine
from .export import write_jxr
from .image_io import load_image, save_hdr_preview, save_sdr_preview
from .settings import HdrSettings

EVENT_PREFIX = "@HDRJSON:"


def process_files(
    request: dict,
    emit: Callable[[dict], None],
    engine_factory: Callable[[int], HdrEngine] = NvidiaEngine,
) -> list[dict]:
    settings = HdrSettings.from_dict(request["settings"])
    mode = request["mode"]
    if mode not in ("preview", "export"):
        raise ValueError("Job mode must be preview or export.")
    files = request["files"]
    if not isinstance(files, list) or not files or not all(isinstance(p, str) for p in files):
        raise ValueError("A job requires a non-empty list of input paths.")
    job_dir = Path(request["job_dir"])
    job_dir.mkdir(parents=True, exist_ok=True)
    output_dir = Path(request["output_dir"])
    engine = engine_factory(settings.device)
    results = []
    try:
        for index, source in enumerate(files):
            started = time.perf_counter()

            def stage(message: str) -> None:
                emit(
                    {
                        "event": "progress",
                        "index": index,
                        "source": source,
                        "total": len(files),
                        "filename": Path(source).name,
                        "message": message,
                    }
                )

            try:
                stage("Reading image")
                rgb, info = load_image(source, settings.background)
                scrgb = engine.convert(rgb, settings, stage)
                before, after, hdr = [
                    job_dir / f"{index}-{name}" for name in ("before.png", "after.png", "hdr.npy")
                ]
                stage("Building preview")
                save_sdr_preview(before, rgb)
                save_sdr_preview(after, sdr_preview(scrgb, settings.luminance))
                save_hdr_preview(hdr, scrgb)
                output = None
                if mode == "export":
                    stage("Saving and verifying JPEG XR")
                    output = write_jxr(output_dir / f"{Path(source).stem}_HDR.jxr", scrgb)
                result = {
                    "source": source,
                    "output": str(output) if output else None,
                    "before": str(before),
                    "after": str(after),
                    "hdr_preview": str(hdr),
                    "info": info,
                    "statistics": hdr_statistics(scrgb),
                    "settings": settings.to_dict(),
                    "gpu": engine.name,
                    "seconds": round(time.perf_counter() - started, 3),
                    "format": "linear scRGB FP16 RGBA JPEG XR",
                    "version": __version__,
                }
                if output:
                    try:
                        with output.with_suffix(".settings.json").open(
                            "x", encoding="utf-8"
                        ) as file:
                            json.dump(result, file, indent=2)
                    except OSError as error:
                        result["metadata_warning"] = str(error)
                results.append(result)
                emit({"event": "file_done", "result": result})
            except Exception as error:
                # Native failures are isolated by the process boundary. Ordinary
                # per-file failures must not discard other successful batch items.
                failed = {"source": source, "error": str(error)}
                results.append(failed)
                emit({"event": "file_error", **failed})
    finally:
        engine.close()
    return results
