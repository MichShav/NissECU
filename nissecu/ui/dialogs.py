"""NissECU UI Dialogs — ConfirmFlashDialog, ECUIdDialog, KeySearchDialog."""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QLineEdit, QPushButton, QDialogButtonBox, QGroupBox,
    QProgressBar, QListWidget, QWidget, QStackedWidget,
    QFrame, QFormLayout
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor


class ConfirmFlashDialog(QDialog):
    """Three-step flash confirmation: checkbox -> type FLASH -> countdown."""

    def __init__(self, rom_info: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm ROM Flash")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._confirmed = False
        self._countdown = 5
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._step = 0  # 0=warning, 1=type-confirm, 2=countdown
        self._rom_info = rom_info
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Warning header
        warn = QLabel("\u26a0  WARNING: FLASHING THE ECU ROM")
        warn.setStyleSheet("font-size: 14px; font-weight: bold; color: #CC2936;")
        layout.addWidget(warn)

        # ROM info
        info = QLabel(
            f"File: {self._rom_info.get('filename', '?')}\n"
            f"Size: {self._rom_info.get('size_kb', '?')} KB\n"
            f"Modified blocks: {self._rom_info.get('modified_blocks', '?')}\n"
            f"Checksum: {chr(10003) + ' Valid' if self._rom_info.get('checksum_ok') else chr(10007) + ' INVALID'}"
        )
        info.setStyleSheet(
            "font-family: monospace; background: #f5f5f5; padding: 8px; border-radius: 3px;"
        )
        layout.addWidget(info)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # Stacked pages
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Page 0: risks checkbox
        page0 = QWidget()
        p0l = QVBoxLayout(page0)
        p0l.addWidget(QLabel(
            "This operation will overwrite the ECU's firmware.\n"
            "An interrupted flash can permanently disable the ECU,\n"
            "requiring bench recovery. Ensure:\n\n"
            "  \u2022 Battery charger is connected (10A+)\n"
            "  \u2022 Ignition is ON, engine is OFF\n"
            "  \u2022 Cable is firmly connected\n"
            "  \u2022 Laptop is plugged in"
        ))
        self._checkbox = QCheckBox("I understand the risks and have a stock ROM backup")
        self._checkbox.stateChanged.connect(self._on_checkbox)
        p0l.addWidget(self._checkbox)
        self._next_btn = QPushButton("Next \u2192")
        self._next_btn.setEnabled(False)
        self._next_btn.clicked.connect(self._go_step1)
        p0l.addWidget(self._next_btn, 0, Qt.AlignRight)
        self._stack.addWidget(page0)

        # Page 1: type FLASH
        page1 = QWidget()
        p1l = QVBoxLayout(page1)
        p1l.addWidget(QLabel("Type  FLASH  in the box below to continue:"))
        self._type_edit = QLineEdit()
        self._type_edit.setPlaceholderText("FLASH")
        self._type_edit.setAlignment(Qt.AlignCenter)
        self._type_edit.setStyleSheet(
            "font-size: 18px; font-weight: bold; letter-spacing: 4px;"
        )
        self._type_edit.textChanged.connect(self._on_type_changed)
        p1l.addWidget(self._type_edit)
        self._flash_btn = QPushButton("Confirm \u2014 starting in 5s")
        self._flash_btn.setEnabled(False)
        self._flash_btn.clicked.connect(self._go_step2)
        p1l.addWidget(self._flash_btn, 0, Qt.AlignRight)
        self._stack.addWidget(page1)

        # Page 2: countdown
        page2 = QWidget()
        p2l = QVBoxLayout(page2)
        self._countdown_label = QLabel("Starting flash in 5 seconds...")
        self._countdown_label.setAlignment(Qt.AlignCenter)
        self._countdown_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #CC2936;"
        )
        p2l.addWidget(self._countdown_label)
        self._cancel_btn2 = QPushButton("Cancel")
        self._cancel_btn2.clicked.connect(self.reject)
        p2l.addWidget(self._cancel_btn2, 0, Qt.AlignCenter)
        self._confirm_btn = QPushButton("FLASH NOW")
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.setStyleSheet(
            "background: #CC2936; color: white; font-weight: bold; padding: 8px 20px;"
        )
        self._confirm_btn.clicked.connect(self._do_confirm)
        p2l.addWidget(self._confirm_btn, 0, Qt.AlignCenter)
        self._stack.addWidget(page2)

        # Cancel button at bottom
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn, 0, Qt.AlignRight)

    def _on_checkbox(self, state):
        self._next_btn.setEnabled(state == Qt.Checked)

    def _go_step1(self):
        self._stack.setCurrentIndex(1)

    def _on_type_changed(self, text):
        ok = text.strip() == "FLASH"
        self._flash_btn.setEnabled(ok)

    def _go_step2(self):
        self._stack.setCurrentIndex(2)
        self._countdown = 5
        self._timer.start(1000)

    def _tick(self):
        self._countdown -= 1
        self._countdown_label.setText(
            f"Starting flash in {self._countdown} seconds..."
        )
        if self._countdown <= 0:
            self._timer.stop()
            self._countdown_label.setText("Ready to flash.")
            self._confirm_btn.setEnabled(True)

    def _do_confirm(self):
        self._confirmed = True
        self.accept()

    def is_confirmed(self) -> bool:
        return self._confirmed


class ECUIdDialog(QDialog):
    """Display ECU identification info."""

    def __init__(self, ecu_info: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ECU Identification")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        fields = [
            ("ECU ID",      ecu_info.get("ecuid", "N/A")),
            ("Part Number",  ecu_info.get("part_number", "N/A")),
            ("FID String",   ecu_info.get("fid_string", "N/A")),
            ("CPU",          ecu_info.get("cpu", "N/A")),
            ("ROM Size",     f"{ecu_info.get('rom_size_kb', '?')} KB"),
        ]
        mono = QFont("Courier New", 10)
        for label, value in fields:
            val_lbl = QLabel(str(value))
            val_lbl.setFont(mono)
            val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(f"{label}:", val_lbl)

        layout.addLayout(form)
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn, 0, Qt.AlignRight)


class KeySearchDialog(QDialog):
    """Progress dialog for seed/key constant search in ROM."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Searching for Key Constant...")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Scanning ROM for seed/key algorithm constant..."))

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        layout.addWidget(self._progress)

        self._status = QLabel("Searching...")
        layout.addWidget(self._status)

        self._results = QListWidget()
        self._results.setVisible(False)
        layout.addWidget(self._results)

        self._close_btn = QPushButton("Close")
        self._close_btn.setEnabled(False)
        self._close_btn.clicked.connect(self.accept)
        layout.addWidget(self._close_btn, 0, Qt.AlignRight)

    def set_progress(self, current: int, total: int):
        pct = int(current / total * 100) if total > 0 else 0
        self._progress.setValue(pct)
        self._status.setText(f"Searched {current:,} / {total:,} locations...")

    def set_result(self, candidates: list):
        self._progress.setValue(100)
        if candidates:
            self._status.setText(f"Found {len(candidates)} candidate(s):")
            self._results.setVisible(True)
            for addr, const in candidates:
                self._results.addItem(f"  0x{addr:06X}  \u2192  key_constant = 0x{const:08X}")
        else:
            self._status.setText("No candidates found. Try with a known seed/key pair.")
        self._close_btn.setEnabled(True)
