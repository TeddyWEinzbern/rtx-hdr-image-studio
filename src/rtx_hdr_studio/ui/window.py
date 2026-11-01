"""English desktop interface; delegates color, files, and GPU work to other layers."""

import json
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QPalette,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..image_io import SUPPORTED
from ..runtime import cache_dir, output_dir
from ..settings import HdrSettings
from .canvas import CompareCanvas
from .controls import Parameter
from .dropdown import Dropdown
from .fullscreen import FullscreenPreview
from .jobs import JobRunner
from .preview_tasks import LatestTask, PreviewDevice, load_preview

PRESETS = {
    "NVIDIA default": HdrSettings(),
    "HDR400": HdrSettings(luminance=400, middle_gray=50),
    "HDR600": HdrSettings(luminance=640, middle_gray=80),
    "HDR1000": HdrSettings(luminance=1000, middle_gray=100),
    "HDR1000 Highlight": HdrSettings(luminance=1000, middle_gray=80),
}
STYLE = """
QWidget { color: #e6eaf1; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QWidget#root { background: #14181e; }
QScrollArea, QListWidget { background: #1c222b; border: 1px solid #333c49; border-radius: 8px; }
QWidget#settings { background: #1c222b; }
QPushButton { background: #2b3542; border: 1px solid #435064; border-radius: 6px; padding: 8px 12px; }
QPushButton:hover { background: #3a495a; }
QPushButton:checked { background: #8bd89a; color: #12251a; border-color: #b7e6c0; font-weight: 600; }
QPushButton:checked:hover { background: #b7e6c0; color: #12251a; }
QPushButton:disabled { color: #75808d; background: #202731; }
QPushButton#primary { background: #8bd89a; color: #12251a; font-weight: 600; }
QPushButton#fullscreen { background: #75b9e8; color: #102536; border-color: #92ceef; font-weight: 600; }
QPushButton#fullscreen:hover { background: #9ad1f2; }
QPushButton#fullscreen:disabled { color: #75808d; background: #202731; border-color: #435064; }
QDoubleSpinBox, QLineEdit { background: #11171f; padding: 5px; border: 1px solid #46546a; border-radius: 5px; }
QComboBox { background: #11171f; min-height: 20px; padding: 5px 8px 5px 10px; border: 1px solid #46546a; border-radius: 5px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 26px; border: none; background: transparent; }
QComboBox::down-arrow { image: url("@dropdown-arrow@"); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: #11171f; color: #e6eaf1; border: 1px solid #46546a; border-radius: 5px; padding: 4px; font: 13px "Segoe UI"; selection-background-color: #8bd89a; selection-color: #12251a; outline: 0; }
QComboBox QAbstractItemView::item { padding: 0 6px; border-radius: 3px; }
QComboBox QAbstractItemView::item:selected { background: #8bd89a; color: #12251a; }
QLabel#title { font-size: 24px; font-weight: 600; }
QLabel#muted { color: #a6b1c1; }
QLabel#notice { background: #202935; padding: 10px; border-radius: 6px; }
QListWidget::item { padding: 10px; border-radius: 5px; }
QListWidget::item:selected { background: #8bd89a; color: #12251a; }
QSlider::groove:horizontal { height: 4px; background: #3b4655; }
QSlider::sub-page:horizontal { background: #8bd89a; }
QSlider::handle:horizontal { background: #b7e6c0; width: 12px; margin: -5px 0; border-radius: 5px; }
QProgressBar { background: #283241; border: none; height: 5px; }
QProgressBar::chunk { background: #8bd89a; }
""".replace("@dropdown-arrow@", (Path(__file__).parent / "icons" / "chevron-down.png").as_posix())


class StudioWindow(QMainWindow):
    def __init__(self, initial_files=()):
        super().__init__()
        self.setWindowTitle(f"RTX HDR Image Studio {__version__}")
        self.setMinimumSize(1060, 740)
        self.resize(1320, 880)
        self.setAcceptDrops(True)
        self.files: list[str] = []
        self.results: dict[str, dict] = {}
        self.outputs: dict[str, str] = {}
        self.job: JobRunner | None = None
        self.processing_source = None
        self._split_on_load = set()
        self.loading_preview = False
        self._displayed_source = None
        self._closing = False
        self.preview_device = PreviewDevice(self)
        self.preview_loader = LatestTask(self)
        self.preview_loader.ready.connect(self._preview_loaded)
        self.preview_loader.failed.connect(self._preview_failed)
        self.fullscreen_preview: FullscreenPreview | None = None
        self._fullscreen_hint_seen = False
        self.destination = output_dir()
        self.last_log: Path | None = None
        self._applying = False
        self._build()
        self.setStyleSheet(STYLE)
        self.apply_settings(HdrSettings())
        if QApplication.platformName() == "windows":
            QTimer.singleShot(0, self.preview_device.ensure)
        for shortcut, action in (
            ("Ctrl+O", self.choose_files),
            ("Ctrl+R", self.preview),
            ("Ctrl+E", self.export),
        ):
            QShortcut(QKeySequence(shortcut), self, action)
        if initial_files:
            QTimer.singleShot(0, lambda: self.add_files(initial_files))

    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 18, 18, 18)
        heading = QLabel("RTX HDR Image Studio")
        heading.setObjectName("title")
        outer.addWidget(heading)
        subtitle = QLabel("NVIDIA TrueHDR | HDR preview | FP16 linear scRGB JXR")
        subtitle.setObjectName("muted")
        outer.addWidget(subtitle)
        toolbar = QHBoxLayout()
        self.add_button = self.button("Add images", self.choose_files, toolbar)
        self.preview_button = self.button("Generate preview", self.preview, toolbar)
        self.export_button = self.button("Export JXR", self.export, toolbar)
        self.export_button.setObjectName("primary")
        self.open_button = self.button("Open result", self.open_result, toolbar)
        self.cancel_button = self.button("Cancel", self.cancel, toolbar)
        self.cancel_button.hide()
        toolbar.addStretch()
        self.button("Help / About", self.show_help, toolbar)
        outer.addLayout(toolbar)
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.queue = QListWidget()
        self.queue.setAccessibleName("Image queue")
        self.queue.setFixedWidth(190)
        self.queue.currentRowChanged.connect(self.select_file)
        left.addWidget(self.queue)
        self.clear_button = self.button("Clear queue", self.clear_files, left)
        body.addLayout(left)
        center = QVBoxLayout()
        self.image_title = QLabel("No image")
        center.addWidget(self.image_title)
        self.image_info = QLabel()
        self.image_info.setWordWrap(True)
        center.addWidget(self.image_info)
        self.canvas = CompareCanvas(device=self.preview_device)
        self.canvas.fullscreen_requested.connect(self.show_fullscreen_preview)
        center.addWidget(self.canvas, 1)
        preview_controls = QHBoxLayout()
        preview_views = QVBoxLayout()
        views = QHBoxLayout()
        self.view_group = QButtonGroup(self)
        self.view_buttons = {}
        for title, mode in (
            ("Original", "before"),
            ("Processed", "after"),
            ("Split view", "split"),
        ):
            self.view_buttons[mode] = self.button(
                title, lambda checked=False, m=mode: self.set_view(m), views
            )
            self.view_buttons[mode].setCheckable(True)
            self.view_buttons[mode].setFixedWidth(100)
            self.view_buttons[mode].setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            self.view_group.addButton(self.view_buttons[mode])
        views.addStretch()
        preview_views.addLayout(views)
        fullscreen_controls = QVBoxLayout()
        self.fullscreen_button = self.button(
            "Fullscreen", self.show_fullscreen_preview, fullscreen_controls
        )
        self.fullscreen_button.setObjectName("fullscreen")
        self.fullscreen_button.setToolTip("View fullscreen, or double-click the image")
        self.fullscreen_button.setFixedWidth(160)
        self.fullscreen_scale = Dropdown()
        self.fullscreen_scale.setAccessibleName("Fullscreen scaling mode")
        self.fullscreen_scale.addItem("Keep aspect ratio", "fit")
        self.fullscreen_scale.addItem("Fill", "fill")
        self.fullscreen_scale.addItem("Stretch", "stretch")
        self.fullscreen_scale.addItem("No scaling", "actual")
        self.fullscreen_scale.setFixedWidth(160)
        self.fullscreen_scale.setToolTip(
            "Fill keeps the aspect ratio and crops centrally to fill the screen. "
            "No scaling uses one preview pixel per physical screen pixel; "
            "images larger than the screen fit while keeping their aspect ratio."
        )
        fullscreen_controls.addWidget(self.fullscreen_scale)
        display = QHBoxLayout()
        self.display_mode = Dropdown()
        self.display_mode.setAccessibleName("Preview display mode")
        self.display_mode.addItem("Automatic HDR", True)
        self.display_mode.addItem("SDR tone-mapped", False)
        self.display_mode.currentIndexChanged.connect(
            lambda: self.canvas.set_hdr_preference(self.display_mode.currentData())
        )
        display.addWidget(self.display_mode)
        self.display_status = QLabel()
        self.display_status.setWordWrap(True)
        display.addWidget(self.display_status, 1)
        preview_views.addLayout(display)
        preview_controls.addLayout(preview_views, 1)
        preview_controls.addLayout(fullscreen_controls)
        preview_controls.setAlignment(fullscreen_controls, Qt.AlignmentFlag.AlignTop)
        center.addLayout(preview_controls)
        self.notice = QLabel()
        self.notice.setObjectName("notice")
        self.notice.setWordWrap(True)
        center.addWidget(self.notice)
        self.canvas.display_changed.connect(self.update_notice)
        body.addLayout(center, 1)
        self.settings_panel = QScrollArea()
        self.settings_panel.setFixedWidth(295)
        self.settings_panel.setWidgetResizable(True)
        self.settings_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("settings")
        right = QVBoxLayout(content)
        self.preset = Dropdown()
        self.preset.setAccessibleName("HDR preset")
        self.preset.addItems([*PRESETS, "Custom"])
        self.preset.currentTextChanged.connect(self.choose_preset)
        right.addWidget(self.preset)
        self.parameters = {}
        for name, title, low, high, suffix, help_text in (
            (
                "luminance",
                "Peak luminance",
                400,
                2000,
                " nit",
                "NVIDIA target peak; actual image and display peaks may differ.",
            ),
            ("contrast", "Contrast", 0, 200, "", "NVIDIA contrast enhancement."),
            ("saturation", "Saturation", 0, 200, "", "NVIDIA color saturation enhancement."),
            ("middle_gray", "Middle gray", 10, 100, "", "NVIDIA middle-gray reference."),
            (
                "exposure",
                "Exposure",
                -3,
                3,
                " EV",
                "Exposure applied in linear light before inference.",
            ),
        ):
            control = Parameter(
                title,
                low,
                high,
                suffix=suffix,
                decimals=2 if name == "exposure" else 0,
                help_text=help_text,
            )
            control.changed.connect(self.parameter_changed)
            self.parameters[name] = control
            right.addWidget(control)
        self.debanding = QCheckBox("NVIDIA debanding")
        self.debanding.stateChanged.connect(self.parameter_changed)
        right.addWidget(self.debanding)
        self.transfer = Dropdown()
        self.transfer.addItem("Standard sRGB", "srgb")
        self.transfer.addItem("Gamma 2.2 encoded", "gamma22")
        self.transfer.currentIndexChanged.connect(self.parameter_changed)
        right.addWidget(self.transfer)
        self.background = Dropdown()
        self.background.addItem("Alpha on black", "black")
        self.background.addItem("Alpha on white", "white")
        self.background.currentIndexChanged.connect(self.parameter_changed)
        right.addWidget(self.background)
        self.device = Parameter(
            "GPU index", 0, 15, help_text="CUDA device index; leave at 0 for a single GPU."
        )
        self.device.changed.connect(self.parameter_changed)
        right.addWidget(self.device)
        presets = QHBoxLayout()
        self.button("Save preset", self.save_preset, presets)
        self.button("Load preset", self.load_preset, presets)
        right.addLayout(presets)
        self.button("Reset", lambda: self.apply_settings(HdrSettings()), right)
        right.addWidget(QLabel("Output directory"))
        self.output_field = QLineEdit(str(self.destination))
        self.output_field.setReadOnly(True)
        right.addWidget(self.output_field)
        self.button("Choose directory", self.choose_output, right)
        self.button("Open output directory", self.open_output, right)
        right.addStretch()
        self.settings_panel.setWidget(content)
        body.addWidget(self.settings_panel)
        outer.addLayout(body, 1)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(5)
        self.progress.setTextVisible(False)
        outer.addWidget(self.progress)
        footer = QHBoxLayout()
        self.status = QLabel("Ready")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.log_button = self.button("Open job log", self.open_log, footer)
        self.log_button.setEnabled(False)
        outer.addLayout(footer)
        self.set_busy(False)

    @staticmethod
    def button(text, action, layout):
        button = QPushButton(text)
        button.clicked.connect(action)
        layout.addWidget(button)
        return button

    def current_settings(self) -> HdrSettings:
        return HdrSettings(
            **{key: control.value() for key, control in self.parameters.items()},
            debanding=self.debanding.isChecked(),
            transfer=self.transfer.currentData(),
            background=self.background.currentData(),
            device=self.device.value(),
        )

    def apply_settings(self, settings: HdrSettings):
        self._applying = True
        for key, control in self.parameters.items():
            control.set_value(getattr(settings, key))
        self.device.set_value(settings.device)
        self.debanding.setChecked(settings.debanding)
        self.transfer.setCurrentIndex(self.transfer.findData(settings.transfer))
        self.background.setCurrentIndex(self.background.findData(settings.background))
        self.preset.setCurrentText(
            next((name for name, value in PRESETS.items() if value == settings), "Custom")
        )
        self._applying = False
        self.update_notice()

    def choose_preset(self, name):
        if not self._applying and name in PRESETS:
            self.apply_settings(PRESETS[name])

    def parameter_changed(self, *_):
        if not self._applying:
            self.preset.blockSignals(True)
            self.preset.setCurrentText("Custom")
            self.preset.blockSignals(False)
            self.update_notice()

    def selected_file(self):
        index = self.queue.currentRow()
        return self.files[index] if 0 <= index < len(self.files) else None

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add SDR images", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"
        )
        self.add_files(paths)

    def add_files(self, paths):
        if self.job:
            return
        for raw in paths:
            path = Path(raw).resolve()
            if (
                path.is_file()
                and path.suffix.lower() in SUPPORTED
                and str(path).casefold() not in {p.casefold() for p in self.files}
            ):
                self.files.append(str(path))
                self.queue.addItem(path.name)
                self.queue.item(self.queue.count() - 1).setToolTip(str(path))
        if self.queue.currentRow() < 0 and self.files:
            self.queue.setCurrentRow(0)
        self.set_busy(False)

    def clear_files(self):
        self.preview_loader.cancel()
        self.loading_preview = False
        self._displayed_source = None
        self.files.clear()
        self.results.clear()
        self._split_on_load.clear()
        self.outputs.clear()
        self.queue.clear()
        self.canvas.set_images(QPixmap())
        self.image_title.setText("No image")
        self.image_info.clear()
        self.set_busy(False)
        self.update_notice()

    def select_file(self, _index):
        source = self.selected_file()
        if not source:
            return
        if self._displayed_source != source:
            self.canvas.set_images(QPixmap())
        self.loading_preview = True
        self.canvas.set_hdr_suspended(source == self.processing_source)
        if source == self.processing_source:
            self.canvas.mode = "before"
        self.image_title.setText(Path(source).name)
        self.image_title.setToolTip(source)
        self.preview_loader.submit(
            load_preview, source, self.results.get(source), self.background.currentData()
        )
        self.update_notice()

    def _preview_loaded(self, preview):
        if self._closing or preview.source != self.selected_file():
            return
        self.loading_preview = False
        self._displayed_source = preview.source
        if (
            preview.source in self._split_on_load
            and not self._selected_processing()
            and not preview.after.isNull()
        ):
            self.canvas.mode = "split"
            self._split_on_load.discard(preview.source)
        self.canvas.set_images(
            QPixmap.fromImage(preview.before), QPixmap.fromImage(preview.after), preview.hdr_path
        )
        info = preview.info
        self.image_info.setText(f"{info['width']} x {info['height']} | {info['input_profile']}")
        self.open_button.setEnabled(preview.source in self.outputs and self.job is None)
        self.update_notice()

    def _preview_failed(self, error):
        if self._closing:
            return
        self.loading_preview = False
        self.canvas.set_images(QPixmap())
        self.image_info.setText(error)
        self.update_notice()

    def set_view(self, mode):
        if self._selected_processing() or self.loading_preview:
            return
        self.canvas.mode = mode
        self.canvas.update()
        self._sync_view_buttons()

    def _sync_view_buttons(self):
        has_image = not self.canvas.before.isNull()
        has_result = not self.canvas.after.isNull()
        current = self.canvas.mode if has_result else "before"
        self.view_group.setExclusive(False)
        for mode, button in self.view_buttons.items():
            enabled = (
                has_image
                and not self._selected_processing()
                and not self.loading_preview
                and (mode == "before" or has_result)
            )
            button.setEnabled(enabled)
            button.setChecked(has_image and mode == current)
        self.view_group.setExclusive(True)

    def show_fullscreen_preview(self):
        if (
            self._selected_processing()
            or self.loading_preview
            or self.canvas.before.isNull()
            or self.fullscreen_preview is not None
        ):
            return
        self.fullscreen_preview = FullscreenPreview(
            self.canvas,
            self,
            self.fullscreen_scale.currentData(),
            show_hint=not self._fullscreen_hint_seen,
        )
        self.fullscreen_preview.source = self.selected_file()
        self.fullscreen_preview.hint_finished.connect(self._fullscreen_hint_finished)
        self.fullscreen_preview.closed.connect(self._fullscreen_closed)
        self.fullscreen_preview.showFullScreen()

    def _fullscreen_closed(self):
        self.fullscreen_preview = None

    def _fullscreen_hint_finished(self):
        self._fullscreen_hint_seen = True

    def _selected_processing(self):
        return self.processing_source is not None and self.processing_source == self.selected_file()

    def _set_processing_source(self, source):
        self.processing_source = source
        self._split_on_load.discard(source)
        if (
            source is not None
            and self.fullscreen_preview is not None
            and self.fullscreen_preview.source == source
        ):
            self.fullscreen_preview.close()
        selected = self._selected_processing()
        if selected:
            self.canvas.mode = "before"
            self.canvas.update()
        self.canvas.set_hdr_suspended(selected)
        self.update_notice()

    def update_notice(self):
        canvas = self.canvas
        self.fullscreen_button.setEnabled(
            not canvas.before.isNull()
            and not self._selected_processing()
            and not self.loading_preview
        )
        self._sync_view_buttons()
        display = canvas.display_info
        if self.loading_preview:
            self.display_status.setText("Preparing preview...")
        elif canvas.hdr_loading:
            self.display_status.setText("Preparing HDR preview...")
        elif canvas.hdr_active:
            self.display_status.setText(f"HDR | {display.bits}-bit")
        elif canvas.hdr_error:
            self.display_status.setText("SDR fallback")
        elif not canvas.prefer_hdr:
            self.display_status.setText("SDR preview")
        elif display.hdr_active:
            self.display_status.setText("HDR Ready")
        else:
            self.display_status.setText("SDR preview")
        note = ""
        result = self.results.get(self.selected_file())
        if result:
            if result["settings"] != self.current_settings().to_dict():
                note = "Preview outdated"
            else:
                note = f"Peak: {result['statistics']['peak_luminance_nits']:.0f} nit"
        self.notice.setText(note)
        self.notice.setVisible(bool(note))
        self.display_status.setToolTip(
            f"{display.name}\nMode: {display.color_mode}\n"
            f"SDR white: {display.sdr_white_nits:.0f} nit\n{canvas.hdr_error or display.error}"
        )

    def preview(self):
        if not self.job and self.selected_file():
            self.start_job("preview", [self.selected_file()])

    def export(self):
        if not self.job and self.files:
            self.start_job("export", self.files.copy())

    def start_job(self, mode, files):
        request = {
            "mode": mode,
            "files": files,
            "settings": self.current_settings().to_dict(),
            "output_dir": str(self.destination),
            "job_dir": str(cache_dir() / "jobs" / uuid.uuid4().hex),
        }
        runner = JobRunner(request, self)
        self.job = runner
        self._set_processing_source(files[0])
        self.last_log = runner.log_path
        runner.event.connect(self.job_event)
        runner.finished.connect(self.job_finished)
        self.set_busy(True)
        self.status.setText("Starting NVIDIA TrueHDR...")
        self.log_button.setEnabled(True)
        runner.start()

    def set_busy(self, busy):
        for widget in (self.add_button, self.clear_button, self.settings_panel):
            widget.setEnabled(not busy)
        self.preview_button.setEnabled(not busy and bool(self.files))
        self.export_button.setEnabled(not busy and bool(self.files))
        self.open_button.setEnabled(not busy and self.selected_file() in self.outputs)
        self.cancel_button.setVisible(busy)
        self.progress.setRange(0, 0 if busy else 100)
        if not busy:
            self.progress.setValue(100 if self.results else 0)

    def job_event(self, event):
        kind = event.get("event")
        if kind == "progress":
            source = event.get("source")
            if source is None and self.job is not None:
                files = self.job.request["files"]
                index = event.get("index", -1)
                if 0 <= index < len(files):
                    source = files[index]
            if source is not None and source != self.processing_source:
                self._set_processing_source(source)
            self.status.setText(
                f"{event['index'] + 1}/{event['total']} | {event['filename']} | {event['message']}"
            )
        elif kind == "file_done":
            result = event["result"]
            self.results[result["source"]] = result
            self._split_on_load.add(result["source"])
            if result["output"]:
                self.outputs[result["source"]] = result["output"]
            if result["source"] == self.processing_source:
                self._set_processing_source(None)
            if result["source"] == self.selected_file():
                self.select_file(self.queue.currentRow())
        elif kind == "file_error":
            if event["source"] == self.processing_source:
                self._set_processing_source(None)
            self.status.setText(f"Failed: {Path(event['source']).name}: {event['error']}")

    def job_finished(self):
        runner = self.job
        outcome = runner.outcome
        self.job = None
        self._set_processing_source(None)
        runner.deleteLater()
        self.set_busy(False)
        if outcome.get("cancelled"):
            self.status.setText("Cancelled")
        elif outcome.get("event") == "error":
            self.status.setText("Processing failed")
            QMessageBox.warning(self, "Processing failed", outcome["message"])
        else:
            results = outcome.get("results", [])
            good = [r for r in results if "error" not in r]
            failed = [r for r in results if "error" in r]
            exported = sum(bool(r["output"]) for r in good)
            self.status.setText(
                f"Completed: {len(good)} | Exported: {exported} | Failed: {len(failed)}"
            )
            if failed:
                QMessageBox.warning(
                    self,
                    "Some images failed",
                    "\n\n".join(f"{Path(r['source']).name}: {r['error']}" for r in failed[:5]),
                )
        self.update_notice()

    def cancel(self):
        if self.job:
            self.job.cancel()
            self.status.setText("Stopping the GPU worker...")

    def choose_output(self):
        chosen = QFileDialog.getExistingDirectory(self, "Output directory", str(self.destination))
        if chosen:
            self.destination = Path(chosen)
            self.output_field.setText(chosen)

    def open_output(self):
        self.destination.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.destination)))

    def open_result(self):
        output = self.outputs.get(self.selected_file())
        if output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(output))

    def open_log(self):
        if self.last_log and self.last_log.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_log)))

    def save_preset(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save preset", "hdr-preset.json", "JSON (*.json)"
        )
        if path:
            try:
                Path(path).write_text(
                    json.dumps(
                        {"schema_version": 1, "settings": self.current_settings().to_dict()},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as error:
                QMessageBox.warning(self, "Cannot save preset", str(error))

    def load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load preset", "", "JSON (*.json)")
        if path:
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError("A preset must contain a JSON object.")
                if data.get("schema_version") != 1:
                    raise ValueError("Unsupported preset schema version.")
                self.apply_settings(HdrSettings.from_dict(data["settings"]))
            except (OSError, ValueError, TypeError, KeyError) as error:
                QMessageBox.warning(self, "Cannot load preset", str(error))

    def show_help(self):
        QMessageBox.information(
            self,
            "About RTX HDR Image Studio",
            f"RTX HDR Image Studio {__version__}\nMIT License\n\n"
            "Created with OpenAI Codex (ChatGPT), an AI coding assistant, under human direction.\n\n"
            "1. Add SDR images and adjust the NVIDIA parameters.\n"
            "2. Generate a preview; drag the comparison divider.\n"
            "Use Fullscreen or double-click the image to enlarge it. Double-click or press Esc to return.\n"
            "3. Export the queue to verified FP16 scRGB JXR.\n\n"
            "Ctrl+O: add | Ctrl+R: preview | Ctrl+E: export\n\n"
            "Windows wallpaper resizing may lose HDR. Prepare suitable input dimensions yourself. "
            "This tool preserves export dimensions and does not change display or wallpaper settings.\n\n"
            "Third-party dependencies, including NVIDIA software, retain their own licenses.",
        )

    def dragEnterEvent(self, event):
        if not self.job and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self.job:
            self.job.cancel()
            if not self.job.wait(5000):
                self.status.setText("Waiting for the GPU worker to stop...")
                event.ignore()
                return
        self._closing = True
        self.preview_loader.close()
        if self.fullscreen_preview is not None:
            self.fullscreen_preview.close()
        self.canvas.shutdown()
        self.preview_device.close()
        event.accept()


def run(initial_files=()) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("RTX HDR Image Studio")
    app.setOrganizationName("RTX HDR Image Studio")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#1c222b"),
        (QPalette.ColorRole.WindowText, "#e6eaf1"),
        (QPalette.ColorRole.Base, "#14181e"),
        (QPalette.ColorRole.Text, "#e6eaf1"),
        (QPalette.ColorRole.Button, "#2b3542"),
        (QPalette.ColorRole.ButtonText, "#e6eaf1"),
        (QPalette.ColorRole.Highlight, "#8bd89a"),
        (QPalette.ColorRole.HighlightedText, "#12251a"),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    window = StudioWindow(initial_files)
    geometry = app.primaryScreen().availableGeometry()
    window.resize(min(1320, geometry.width() - 30), min(880, geometry.height() - 40))
    window.show()
    return app.exec()
