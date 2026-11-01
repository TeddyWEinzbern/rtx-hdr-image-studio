import os
import subprocess
import sys
import textwrap
import time

import numpy as np
import pytest

from rtx_hdr_studio import job_cache
from rtx_hdr_studio.export import write_jxr
from rtx_hdr_studio.runtime import worker_environment


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RTX_HDR_STUDIO_HOME", str(tmp_path / "data"))
    return tmp_path


def make_job(age=0.0):
    path = job_cache.jobs_root() / job_cache.new_job_id()
    (path / "image-scratch").mkdir(parents=True)
    (path / "0-hdr.npy").write_bytes(b"cache")
    then = time.time() - age
    for item in (path / "image-scratch", path / "0-hdr.npy", path):
        os.utime(item, (then, then))
    return path


def test_only_owned_job_directories_are_removed(home):
    owned = make_job()
    assert job_cache.remove_owned_dir(owned) and not owned.exists()
    foreign = job_cache.jobs_root() / "not-a-job"
    foreign.mkdir()
    outside = home / job_cache.new_job_id()
    outside.mkdir()
    assert not job_cache.remove_owned_dir(foreign) and foreign.exists()
    assert not job_cache.remove_owned_dir(outside) and outside.exists()


def test_startup_purge_keeps_recent_directories_of_other_instances(home):
    stale, recent = make_job(age=3 * 86400), make_job(age=60)
    busy = make_job(age=3 * 86400)
    (busy / "1-before.png").write_bytes(b"written just now by a running instance")
    job_cache.purge_all_stale()
    assert not stale.exists() and recent.exists() and busy.exists()


def test_startup_purge_preserves_an_idle_live_owner_then_removes_its_crash_cache(home):
    directory = job_cache.jobs_root() / job_cache.new_job_id()
    script = (
        "import sys, time; from pathlib import Path; "
        "from rtx_hdr_studio.job_cache import create_owned_dir; "
        "create_owned_dir(Path(sys.argv[1])); print('READY', flush=True); time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(directory)],
        stdout=subprocess.PIPE,
        text=True,
        env=worker_environment(),
    )
    try:
        assert process.stdout.readline().strip() == "READY"
        then = time.time() - 3 * 86400
        for path in (directory / job_cache.OWNER_FILE, directory):
            os.utime(path, (then, then))
        job_cache.purge_all_stale()
        assert directory.exists()  # An idle live GUI can still reference old previews.
    finally:
        process.kill()
        process.wait(timeout=10)
    job_cache.purge_all_stale()
    assert not directory.exists()


def test_staging_tag_is_validated_and_names_the_temporary_file():
    tag = job_cache.new_job_id()
    assert job_cache.staging_prefix(tag) == f".rtx-hdr-{tag}-"
    assert job_cache.staging_prefix(None) == ".rtx-hdr-"
    for invalid in ("../x", "*", "ABC", ""):
        with pytest.raises(ValueError):
            job_cache.staging_prefix(invalid)


def test_only_this_jobs_unpublished_staging_files_are_removed(tmp_path):
    mine, other = job_cache.new_job_id(), job_cache.new_job_id()
    staged = tmp_path / f".rtx-hdr-{mine}-abc123"
    foreign = tmp_path / f".rtx-hdr-{other}-def456"
    legacy = tmp_path / ".rtx-hdr-xyz"
    published = tmp_path / "photo_HDR.jxr"
    for path in (staged, foreign, legacy, published):
        path.write_bytes(b"data")
    assert job_cache.remove_staging_files(tmp_path, mine) == [staged]
    assert not staged.exists() and foreign.exists() and legacy.exists() and published.exists()
    assert job_cache.remove_staging_files(tmp_path, "*") == []


def test_export_uses_the_job_staging_tag_and_leaves_nothing_behind(tmp_path):
    tag = job_cache.new_job_id()
    path = write_jxr(tmp_path / "a.jxr", np.ones((3, 4, 3), np.float32), staging_tag=tag)
    assert path.exists() and sorted(p.name for p in tmp_path.iterdir()) == ["a.jxr"]


def test_terminated_export_staging_file_is_removed_after_the_worker_is_reaped(tmp_path):
    """AUD-003: a worker killed between staging and publication."""
    tag = job_cache.new_job_id()
    out = tmp_path / "out"
    out.mkdir()
    child = textwrap.dedent(
        f"""
        import sys, time
        import numpy as np
        from rtx_hdr_studio import export
        def pause(_fd):
            print("STAGED", flush=True)
            time.sleep(60)
        export.os.fsync = pause
        export.write_jxr(export.Path(sys.argv[1]) / "photo_HDR.jxr",
                         np.zeros((30, 40, 3), np.float32), staging_tag="{tag}")
        """
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child, str(out)],
        stdout=subprocess.PIPE,
        text=True,
        env=worker_environment(),
    )
    try:
        assert process.stdout.readline().strip() == "STAGED"
        assert len(list(out.glob(f".rtx-hdr-{tag}-*"))) == 1
    finally:
        process.kill()
        process.wait()
    removed = job_cache.remove_staging_files(out, tag)
    assert len(removed) == 1 and list(out.iterdir()) == []
