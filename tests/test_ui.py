from PySide6.QtWidgets import QApplication

from rtx_hdr_studio.settings import HdrSettings
from rtx_hdr_studio.ui.window import StudioWindow


def test_parameter_boundary_and_sdr_choice():
    app = QApplication.instance() or QApplication([])
    window = StudioWindow()
    window.show()
    app.processEvents()
    window.parameters["luminance"].spin.setValue(1000)
    window.parameters["exposure"].spin.setValue(0.5)
    window.debanding.setChecked(False)
    assert window.current_settings().luminance == 1000
    assert window.current_settings().exposure == 0.5
    assert not window.current_settings().debanding
    assert window.preset.currentText() == "Custom"
    window.display_mode.setCurrentIndex(1)
    assert not window.canvas.prefer_hdr
    assert "SDR" in window.display_status.text()
    window.apply_settings(HdrSettings())
    assert window.current_settings() == HdrSettings()
    assert not window.export_button.isEnabled()
    window.close()
    app.processEvents()


def test_cancel_before_worker_start(tmp_path):
    from rtx_hdr_studio.ui.jobs import JobRunner

    app = QApplication.instance() or QApplication([])
    scratch = tmp_path / "job" / "image-interrupted"
    scratch.mkdir(parents=True)
    (scratch / "0.bin").write_bytes(b"scratch")
    completed = tmp_path / "job" / "0-after.png"
    completed.write_bytes(b"completed cache")
    job = JobRunner({"job_dir": str(tmp_path / "job")})
    job.cancel()
    job.start()
    assert job.wait(5000)
    assert job.outcome == {"cancelled": True}
    assert not scratch.exists() and completed.exists()
    app.processEvents()
