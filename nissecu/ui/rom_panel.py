"""NissECU ROM Panel — read/write ROM, hex viewer, .bin file I/O."""
from __future__ import annotations

import hashlib
import logging
import os
import struct
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QGroupBox, QSplitter, QFrame, QMessageBox,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QBrush

log = logging.getLogger(__name__)

_HEX_COLS = 16
_HEX_MAX_ROWS = 4096


class HexViewerWidget(QWidget):
    """Hex viewer: address | hex bytes | ASCII columns."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Optional[bytes] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Address", "Hex", "ASCII"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setFont(QFont("Courier New", 9))
        self._table.setAlternatingRowColors(True)
        self._table.setMinimumHeight(200)
        layout.addWidget(self._table)

    def load(self, data: bytes):
        self._data = data
        n = min(len(data), _HEX_COLS * _HEX_MAX_ROWS)
        rows = (n + _HEX_COLS - 1) // _HEX_COLS
        self._table.setRowCount(rows)
        for r in range(rows):
            chunk = data[r * _HEX_COLS: r * _HEX_COLS + _HEX_COLS]
            addr_item = QTableWidgetItem(f"{r * _HEX_COLS:08X}")
            addr_item.setForeground(QBrush(QColor("#555555")))
            self._table.setItem(r, 0, addr_item)
            self._table.setItem(r, 1, QTableWidgetItem(" ".join(f"{b:02X}" for b in chunk)))
            self._table.setItem(r, 2, QTableWidgetItem(
                "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
            ))
        if len(data) > n:
            extra = QTableWidgetItem(f"... {(len(data) - n) // 1024} KB not shown ...")
            extra.setForeground(QBrush(QColor("#888888")))
            r2 = self._table.rowCount()
            self._table.setRowCount(r2 + 1)
            self._table.setItem(r2, 1, extra)
        self._table.resizeRowsToContents()

    def clear(self):
        self._data = None
        self._table.setRowCount(0)


class ROMPanel(QWidget):
    """Panel for ROM dump / flash with hex viewer."""

    rom_loaded = pyqtSignal(bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rom_data: Optional[bytearray] = None
        self._backup_saved: bool = False
        self._worker = None
        self._reflasher = None
        self._setup_ui()
        self._set_connected(False)

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        toolbar = QHBoxLayout()
        self._read_btn = QPushButton("Read ROM from ECU")
        self._read_btn.clicked.connect(self._on_read_rom)
        toolbar.addWidget(self._read_btn)
        self._open_btn = QPushButton("Open .bin\u2026")
        self._open_btn.clicked.connect(self._on_open_file)
        toolbar.addWidget(self._open_btn)
        self._save_btn = QPushButton("Save .bin\u2026")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save_file)
        toolbar.addWidget(self._save_btn)
        toolbar.addStretch()
        self._write_btn = QPushButton("Write ROM to ECU")
        self._write_btn.setStyleSheet("font-weight: bold; color: #CC2936;")
        self._write_btn.setEnabled(False)
        self._write_btn.clicked.connect(self._on_write_rom)
        toolbar.addWidget(self._write_btn)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        toolbar.addWidget(self._cancel_btn)
        root.addLayout(toolbar)

        prog_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        prog_row.addWidget(self._progress, 1)
        self._prog_label = QLabel("Idle")
        self._prog_label.setStyleSheet("font-size: 10px; color: #666;")
        prog_row.addWidget(self._prog_label)
        root.addLayout(prog_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        splitter = QSplitter(Qt.Vertical)
        info_box = QGroupBox("ROM Info")
        info_layout = QHBoxLayout(info_box)
        self._info_label = QLabel("No ROM loaded.")
        self._info_label.setFont(QFont("Courier New", 9))
        self._info_label.setWordWrap(True)
        info_layout.addWidget(self._info_label)
        splitter.addWidget(info_box)

        hex_box = QGroupBox("Hex Viewer")
        hex_layout = QVBoxLayout(hex_box)
        self._hex_viewer = HexViewerWidget()
        hex_layout.addWidget(self._hex_viewer)
        splitter.addWidget(hex_box)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888; font-size: 10px;")
        root.addWidget(self._status_label)

    def set_reflasher(self, reflasher):
        self._reflasher = reflasher
        self._update_write_btn()

    def load_rom_data(self, data):
        self._rom_data = bytearray(data)
        self._refresh_from_rom()

    def _set_connected(self, connected: bool):
        self._read_btn.setEnabled(connected)
        if not connected:
            self._write_btn.setEnabled(False)

    def set_connected(self, connected: bool):
        self._set_connected(connected)

    def _on_read_rom(self):
        if self._reflasher is None:
            QMessageBox.warning(self, "Not Connected", "Connect to ECU first.")
            return
        from nissecu.ui.background_worker import ROMDumpWorker
        self._worker = ROMDumpWorker(self._reflasher)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_dump_finished)
        self._worker.error.connect(self._on_error)
        self._read_btn.setEnabled(False)
        self._write_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._progress.setValue(0)
        self._prog_label.setText("Reading ROM\u2026")
        self._worker.start()

    def _on_open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ROM .bin", "", "Binary files (*.bin);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
            self._rom_data = bytearray(data)
            self._refresh_from_rom()
            self._status_label.setText(f"Opened: {os.path.basename(path)}")
            self._backup_saved = True
            self._update_write_btn()
            self.rom_loaded.emit(bytes(self._rom_data))
        except OSError as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))

    def _on_save_file(self):
        if not self._rom_data:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ROM .bin", "rom_backup.bin", "Binary files (*.bin)"
        )
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(self._rom_data)
            self._backup_saved = True
            self._update_write_btn()
            self._status_label.setText(f"Saved: {os.path.basename(path)}")
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _on_write_rom(self):
        if not self._backup_saved:
            QMessageBox.warning(self, "No Backup", "Save a ROM backup (.bin) before flashing.")
            return
        if self._reflasher is None:
            QMessageBox.warning(self, "Not Connected", "Connect to ECU first.")
            return
        from nissecu.ui.dialogs import ConfirmFlashDialog
        rom_info = {
            "filename": "ROM in memory",
            "size_kb": len(self._rom_data) // 1024 if self._rom_data else 0,
            "modified_blocks": "?",
            "checksum_ok": True,
        }
        dlg = ConfirmFlashDialog(rom_info, parent=self)
        if dlg.exec_() != dlg.Accepted or not dlg.is_confirmed():
            return
        from nissecu.ui.background_worker import ROMFlashWorker
        self._worker = ROMFlashWorker(
            self._reflasher, bytes(self._rom_data), key_func=None
        )
        self._worker.progress.connect(self._on_flash_progress)
        self._worker.finished.connect(self._on_flash_finished)
        self._worker.error.connect(self._on_error)
        self._write_btn.setEnabled(False)
        self._read_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._prog_label.setText("Flashing ROM\u2026")
        self._worker.start()

    def _on_cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._prog_label.setText("Cancelling\u2026")

    def _on_progress(self, done: int, total: int):
        pct = int(done / total * 100) if total > 0 else 0
        self._progress.setValue(pct)
        self._prog_label.setText(f"Reading\u2026 {done // 1024}/{total // 1024} KB")

    def _on_flash_progress(self, phase: str, blk: int, total: int):
        pct = int(blk / total * 100) if total > 0 else 0
        self._progress.setValue(pct)
        self._prog_label.setText(f"{phase} block {blk}/{total}")

    def _on_dump_finished(self, success: bool, data: bytes):
        self._cancel_btn.setEnabled(False)
        self._read_btn.setEnabled(True)
        if success and data:
            self._rom_data = bytearray(data)
            self._refresh_from_rom()
            self._save_btn.setEnabled(True)
            self._prog_label.setText(f"ROM read OK \u2014 {len(data) // 1024} KB")
            self._progress.setValue(100)
            self.rom_loaded.emit(data)
        else:
            self._prog_label.setText("ROM read failed.")
            self._progress.setValue(0)

    def _on_flash_finished(self, success: bool):
        self._cancel_btn.setEnabled(False)
        self._write_btn.setEnabled(True)
        self._read_btn.setEnabled(True)
        if success:
            self._prog_label.setText("Flash complete.")
            self._progress.setValue(100)
            QMessageBox.information(self, "Flash Complete", "ROM written and verified successfully.")
        else:
            self._prog_label.setText("Flash failed \u2014 see log.")
            self._progress.setValue(0)

    def _on_error(self, msg: str):
        self._cancel_btn.setEnabled(False)
        self._read_btn.setEnabled(True)
        self._prog_label.setText(f"Error: {msg}")
        QMessageBox.critical(self, "Operation Failed", msg)

    def _refresh_from_rom(self):
        if not self._rom_data:
            return
        size = len(self._rom_data)
        ecuid = self._extract_ecuid()
        self._info_label.setText(
            f"Size:  {size // 1024} KB  ({size:,} bytes)\n"
            f"ECUID: {ecuid or '(not found)'}\n"
            f"MD5:   {hashlib.md5(self._rom_data).hexdigest()}"
        )
        self._hex_viewer.load(bytes(self._rom_data))
        self._save_btn.setEnabled(True)
        self._update_write_btn()

    def _update_write_btn(self):
        self._write_btn.setEnabled(
            bool(self._rom_data) and self._backup_saved and self._reflasher is not None
        )

    def _extract_ecuid(self) -> str:
        if not self._rom_data:
            return ""
        chunk = bytes(self._rom_data[:0x200])
        printable = "".join(chr(b) if 0x20 <= b < 0x7F else " " for b in chunk)
        parts = [p.strip() for p in printable.split() if len(p.strip()) >= 6]
        return parts[0] if parts else ""
