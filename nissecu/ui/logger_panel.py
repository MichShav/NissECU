"""NissECU Logger Panel — CSV log file viewer with live tail preview."""
from __future__ import annotations

import csv
import logging
import os
from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QFrame, QSizePolicy, QSpinBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont

log = logging.getLogger(__name__)

_PREVIEW_ROWS = 50


class LoggerPanel(QWidget):
    """
    CSV logging panel.

    Start/Stop logging is controlled here. DataLogger is provided by the
    main window via set_logger().
    """

    log_start_requested = pyqtSignal(str, list)
    log_stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logger = None
        self._logging = False
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_timer.setInterval(1000)
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        file_box = QGroupBox("Log File")
        file_layout = QHBoxLayout(file_box)
        file_layout.addWidget(QLabel("Path:"))
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("nissecu_log_YYYYMMDD_HHMMSS.csv")
        file_layout.addWidget(self._path_edit, 1)
        browse_btn = QPushButton("Browse\u2026")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._on_browse)
        file_layout.addWidget(browse_btn)
        root.addWidget(file_box)

        ctrl_row = QHBoxLayout()
        self._start_btn = QPushButton("Start Logging")
        self._start_btn.setStyleSheet("font-weight: bold; min-width: 120px;")
        self._start_btn.clicked.connect(self._on_toggle)
        ctrl_row.addWidget(self._start_btn)
        ctrl_row.addWidget(QLabel("  Preview rows:"))
        self._rows_spin = QSpinBox()
        self._rows_spin.setRange(10, 500)
        self._rows_spin.setValue(_PREVIEW_ROWS)
        self._rows_spin.setFixedWidth(70)
        ctrl_row.addWidget(self._rows_spin)
        ctrl_row.addStretch()
        self._count_label = QLabel("0 samples logged")
        self._count_label.setStyleSheet("color: #555; font-size: 10px;")
        ctrl_row.addWidget(self._count_label)
        root.addLayout(ctrl_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        preview_box = QGroupBox("Live Preview (last rows)")
        preview_layout = QVBoxLayout(preview_box)
        self._table = QTableWidget(0, 0)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setFont(QFont("Courier New", 8))
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_layout.addWidget(self._table)
        root.addWidget(preview_box, 1)

        open_row = QHBoxLayout()
        open_row.addWidget(QLabel("View existing log:"))
        self._open_log_btn = QPushButton("Open CSV\u2026")
        self._open_log_btn.setFixedWidth(100)
        self._open_log_btn.clicked.connect(self._on_open_existing)
        open_row.addWidget(self._open_log_btn)
        open_row.addStretch()
        root.addLayout(open_row)

        self._status_label = QLabel("Not logging.")
        self._status_label.setStyleSheet("color: #888; font-size: 10px;")
        root.addWidget(self._status_label)

    def set_logger(self, logger):
        self._logger = logger

    def set_connected(self, connected: bool):
        self._start_btn.setEnabled(connected or not self._logging)

    def update_count(self, count: int):
        self._count_label.setText(f"{count:,} samples logged")

    def _on_browse(self):
        from nissecu.data_logger import DataLogger
        default = DataLogger.auto_filename() if hasattr(DataLogger, "auto_filename") else "log.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Log File", default, "CSV Files (*.csv)"
        )
        if path:
            self._path_edit.setText(path)

    def _on_toggle(self):
        if not self._logging:
            self._start_logging()
        else:
            self._stop_logging()

    def _start_logging(self):
        path = self._path_edit.text().strip()
        if not path:
            from nissecu.data_logger import DataLogger
            path = DataLogger.auto_filename() if hasattr(DataLogger, "auto_filename") else "nissecu_log.csv"
            self._path_edit.setText(path)
        if self._logger is not None:
            try:
                self._logger.start(path)
            except Exception as exc:
                self._status_label.setText(f"Error: {exc}")
                return
        self._logging = True
        self._start_btn.setText("Stop Logging")
        self._start_btn.setStyleSheet("font-weight: bold; color: #CC2936; min-width: 120px;")
        self._preview_timer.start()
        self._status_label.setText(f"Logging to: {os.path.basename(path)}")
        self.log_start_requested.emit(path, [])

    def _stop_logging(self):
        if self._logger is not None:
            try:
                self._logger.stop()
            except Exception:
                pass
        self._logging = False
        self._start_btn.setText("Start Logging")
        self._start_btn.setStyleSheet("font-weight: bold; min-width: 120px;")
        self._preview_timer.stop()
        self._status_label.setText("Logging stopped.")
        self.log_stop_requested.emit()
        self._refresh_preview()

    def _refresh_preview(self):
        path = self._path_edit.text().strip()
        if not path or not os.path.isfile(path):
            return
        max_rows = self._rows_spin.value()
        try:
            rows, headers = self._tail_csv(path, max_rows)
        except Exception as exc:
            log.warning("Preview refresh failed: %s", exc)
            return
        if not headers:
            return
        if self._table.columnCount() != len(headers):
            self._table.setColumnCount(len(headers))
            self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(rows))
        for r, row_data in enumerate(rows):
            for c, val in enumerate(row_data):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(r, c, item)
        if self._logger is not None and hasattr(self._logger, "get_count"):
            self._count_label.setText(f"{self._logger.get_count():,} samples logged")

    def _on_open_existing(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Log File", "", "CSV Files (*.csv);;All files (*)"
        )
        if not path:
            return
        self._path_edit.setText(path)
        self._refresh_preview()
        self._status_label.setText(f"Viewing: {os.path.basename(path)}")

    @staticmethod
    def _tail_csv(path: str, n: int):
        headers: List[str] = []
        rows: List[List[str]] = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0:
                    headers = row
                else:
                    rows.append(row)
        return rows[-n:], headers
