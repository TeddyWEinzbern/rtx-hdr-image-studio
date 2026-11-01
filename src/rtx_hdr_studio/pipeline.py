"""Batch orchestration, injectable engine, and a small JSON worker protocol."""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .color import hdr_statistics, sdr_preview
from .engine import HdrEngine, NvidiaEngine
from .export import write_jxr
from .image_io import (
    image_info,
    load_image,
    preview_size,
    resize_linear,
    save_hdr_preview,
    save_sdr_preview,
)
from .job_cache import staging_prefix
from .resources import ProcessingLock, ScratchSpace, release_image
from .settings import HdrSettings

EVENT_PREFIX = "@HDRJSON:"


def process_files(
    request: dict,
    emit: Callable[[dict], None],
    engine_factory: Callable[[int], HdrEngine] = NvidiaEngine,
) -> list[dict]:
    with ProcessingLock():
        return _process_files(request, emit, engine_factory)


def _process_files(request, emit, engine_factory):
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
    staging_tag = request.get("staging_tag")
    staging_prefix(staging_tag)  # Validate before any work starts.
    engine = engine_factory(settings.device)
    try:
        results = _process_all(
            files, settings, engine, emit, job_dir, mode, output_dir, staging_tag
        )
    except BaseException:
        # Keep the original failure; a second error while closing is only logged.
        try:
            engine.close()
        except Exception:
            logging.getLogger(__name__).exception("Closing the engine after a failure failed")
        raise
    engine.close()
    return results


def _process_all(files, settings, engine, emit, job_dir, mode, output_dir, staging_tag):
    results = []
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
            with ScratchSpace(job_dir):
                data = _process_image(
                    source,
                    settings,
                    engine,
                    stage,
                    index,
                    job_dir,
                    mode,
                    output_dir,
                    staging_tag,
                )
            result = {
                "source": source,
                **data,
                "settings": settings.to_dict(),
                "gpu": engine.name,
                "seconds": round(time.perf_counter() - started, 3),
                "format": "linear scRGB FP16 RGBA JPEG XR",
                "version": __version__,
            }
            if result["output"]:
                try:
                    with (
                        Path(result["output"])
                        .with_suffix(".settings.json")
                        .open("x", encoding="utf-8") as file
                    ):
                        json.dump(result, file, indent=2)
                except OSError as error:
                    result["metadata_warning"] = str(error)
            results.append(result)
            emit({"event": "file_done", "result": result})
        except Exception as error:
            if getattr(engine, "failed", False):
                raise RuntimeError(
                    f"GPU processing failed for {Path(source).name}: {error}"
                ) from error
            # Native failures are isolated by the process boundary. Ordinary
            # per-file failures must not discard other successful batch items.
            failed = {"source": source, "error": str(error)}
            results.append(failed)
            emit({"event": "file_error", **failed})
    return results


def _process_image(
    source, settings, engine, stage, index, job_dir, mode, output_dir, staging_tag=None
):
    if check := getattr(engine, "check_resources", None):
        info = image_info(source)
        check(info["width"], info["height"])
    rgb, info = load_image(source, settings.background)
    before, after, hdr = [
        job_dir / f"{index}-{name}" for name in ("before.png", "after.png", "hdr.npy")
    ]
    stage("Building original preview")
    save_sdr_preview(before, rgb)
    scrgb = engine.convert(rgb, settings, stage)
    release_image(rgb)
    del rgb
    # Engines may collect statistics while producing the image (one pass less).
    statistics = getattr(engine, "last_statistics", None) or hdr_statistics(scrgb)
    stage("Building preview")
    # Tone-map only the bounded HDR preview rather than another full-size image.
    preview = resize_linear(scrgb, *preview_size(info["width"], info["height"]))
    save_sdr_preview(after, sdr_preview(preview, settings.luminance))
    save_hdr_preview(hdr, preview)
    output = None
    if mode == "export":
        stage("Saving and verifying JPEG XR")
        output = write_jxr(
            output_dir / f"{Path(source).stem}_HDR.jxr",
            scrgb,
            staging_tag=staging_tag,
            trusted_range=getattr(engine, "output_range_trusted", False),
        )
    return {
        "output": str(output) if output else None,
        "before": str(before),
        "after": str(after),
        "hdr_preview": str(hdr),
        "info": info,
        "statistics": statistics,
    }
