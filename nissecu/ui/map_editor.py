"""NissECU Map Editor Panel — editable 2D table + embedded matplotlib 3D/2D view."""
from __future__ import annotations

import colorsys
import logging
import struct
from typing import Optional

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QPushButton,
    QSplitter, QGroupBox, QMessageBox, QSizePolicy, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QBrush

try:
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    _MATPLOTLIB_OK = True
except ImportError:
    _MATPLOTLIB_OK = False

log = logging.getLogger(__name__)

_BUILTIN_MAPS = {
    "Fuel Map (16\u00d716)": {
        "offset": 0x10A00, "rows": 16, "cols": 16,
        "cell_bytes": 2, "scale": 0.01221, "units": "ms",
        "row_label": "Load", "col_label": "RPM",
    },
    "Ignition Map (16\u00d716)": {
        "offset": 0x11200, "rows": 16, "cols": 16,
        "cell_bytes": 1, "scale": 0.375, "units": "\u00b0BTDC",
        "row_label": "Load", "col_label": "RPM",
    },
    "Idle Fuel Map (8\u00d78)": {
        "offset": 0x13000, "rows": 8, "cols": 8,
        "cell_bytes": 2, "scale": 0.01221, "units": "ms",
        "row_label": "IAT", "col_label": "ECT",
    },
    "VTC Advance Map (16\u00d716)": {
        "offset": 0x14800, "rows": 16, "cols": 16,
        "cell_bytes": 1, "scale": 0.375, "units": "\u00b0",
        "row_label": "Load", "col_label": "RPM",
    },
}


class MapTableWidget(QTableWidget):
    """Editable table widget that shows a 2-D map with HSV colour gradient."""

    cell_edited = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Optional[np.ndarray] = None
        self._units: str = ""
        self._dirty: bool = False
        self.setFont(QFont("Courier New", 9))
        self.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.AnyKeyPressed)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.itemChanged.connect(self._on_item_changed)

    def set_map(self, data: np.ndarray, units: str = ""):
        self._data = data.copy().astype(float)
        self._units = units
        self._dirty = False
        rows, cols = data.shape
        self.blockSignals(True)
        self.setRowCount(rows)
        self.setColumnCount(cols)
        self.setHorizontalHeaderLabels([str(i) for i in range(cols)])
        self.setVerticalHeaderLabels([str(i) for i in range(rows)])
        self._populate()
        self.blockSignals(False)

    def get_map(self) -> Optional[np.ndarray]:
        if self._data is None:
            return None
        rows, cols = self._data.shape
        out = np.zeros((rows, cols), dtype=np.float32)
        for r in range(rows):
            for c in range(cols):
                item = self.item(r, c)
                if item is None:
                    continue
                try:
                    out[r, c] = float(item.text())
                except ValueError:
                    out[r, c] = self._data[r, c]
        return out

    def revert(self):
        if self._data is None:
            return
        self.blockSignals(True)
        self._populate()
        self._dirty = False
        self.blockSignals(False)
        self.cell_edited.emit()

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def _populate(self):
        if self._data is None:
            return
        mn, mx = float(self._data.min()), float(self._data.max())
        rows, cols = self._data.shape
        for r in range(rows):
            for c in range(cols):
                val = float(self._data[r, c])
                item = QTableWidgetItem(f"{val:.3f}")
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(QBrush(self._value_color(val, mn, mx)))
                self.setItem(r, c, item)

    @staticmethod
    def _value_color(val: float, mn: float, mx: float) -> QColor:
        if mx == mn:
            return QColor("#2D9E5F")
        t = (val - mn) / (mx - mn)
        hue = (1.0 - t) * 120.0 / 360.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.92)
        return QColor(int(r * 255), int(g * 255), int(b * 255))

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._data is None:
            return
        try:
            float(item.text())
        except ValueError:
            return
        self._dirty = True
        current = self.get_map()
        if current is None:
            return
        mn, mx = float(current.min()), float(current.max())
        rows, cols = current.shape
        self.blockSignals(True)
        for r in range(rows):
            for c in range(cols):
                it = self.item(r, c)
                if it:
                    it.setBackground(QBrush(self._value_color(current[r, c], mn, mx)))
        self.blockSignals(False)
        self.cell_edited.emit()


class MatplotlibCanvas(QWidget):
    """Embedded matplotlib figure for 3D surface or 2D heatmap."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode_3d = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if _MATPLOTLIB_OK:
            self._fig = Figure(figsize=(5, 4), tight_layout=True)
            self._canvas = FigureCanvas(self._fig)
            self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout.addWidget(self._canvas)
        else:
            layout.addWidget(QLabel("matplotlib not installed."))
            self._fig = None
            self._canvas = None

        self.setMinimumHeight(250)

    def plot(self, data: np.ndarray, units: str = ""):
        if not _MATPLOTLIB_OK or self._fig is None:
            return
        self._fig.clear()
        if self._mode_3d:
            self._plot_surface(data, units)
        else:
            self._plot_heatmap(data, units)
        self._canvas.draw()

    def set_mode_3d(self, three_d: bool):
        self._mode_3d = three_d

    def _plot_surface(self, data: np.ndarray, units: str):
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
        ax = self._fig.add_subplot(111, projection="3d")
        rows, cols = data.shape
        X, Y = np.meshgrid(range(cols), range(rows))
        surf = ax.plot_surface(X, Y, data, cmap="RdYlGn_r", alpha=0.85, linewidth=0)
        self._fig.colorbar(surf, ax=ax, shrink=0.5, label=units)
        ax.set_xlabel("Col")
        ax.set_ylabel("Row")
        ax.set_zlabel(units)
        ax.tick_params(labelsize=7)

    def _plot_heatmap(self, data: np.ndarray, units: str):
        ax = self._fig.add_subplot(111)
        im = ax.imshow(data, cmap="RdYlGn_r", aspect="auto", origin="lower")
        self._fig.colorbar(im, ax=ax, label=units)
        ax.set_xlabel("Col")
        ax.set_ylabel("Row")
        ax.tick_params(labelsize=7)


class MapEditorPanel(QWidget):
    """Top-level map editor: selector, table, chart, save/revert buttons."""

    map_modified = pyqtSignal(str, np.ndarray)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rom_data: Optional[bytearray] = None
        self._current_map_name: str = ""
        self._current_def: Optional[dict] = None
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Map:"))
        self._map_combo = QComboBox()
        self._map_combo.setMinimumWidth(200)
        for name in _BUILTIN_MAPS:
            self._map_combo.addItem(name)
        self._map_combo.currentIndexChanged.connect(self._on_map_selected)
        toolbar.addWidget(self._map_combo)

        self._view_btn = QPushButton("Switch to 2D Heatmap")
        self._view_btn.clicked.connect(self._toggle_view)
        toolbar.addWidget(self._view_btn)
        toolbar.addStretch()

        self._save_btn = QPushButton("Apply Changes")
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet("font-weight: bold; color: #1a6e35;")
        self._save_btn.clicked.connect(self._on_save)
        toolbar.addWidget(self._save_btn)

        self._revert_btn = QPushButton("Revert")
        self._revert_btn.setEnabled(False)
        self._revert_btn.clicked.connect(self._on_revert)
        toolbar.addWidget(self._revert_btn)

        root.addLayout(toolbar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        splitter = QSplitter(Qt.Horizontal)

        table_box = QGroupBox("Map Table")
        table_layout = QVBoxLayout(table_box)
        self._table = MapTableWidget()
        self._table.cell_edited.connect(self._on_cell_edited)
        table_layout.addWidget(self._table)
        splitter.addWidget(table_box)

        chart_box = QGroupBox("Chart")
        chart_layout = QVBoxLayout(chart_box)
        self._chart = MatplotlibCanvas()
        chart_layout.addWidget(self._chart)
        splitter.addWidget(chart_box)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self._status_label = QLabel("Load a ROM file in the ROM tab first.")
        self._status_label.setStyleSheet("color: #888; font-size: 10px;")
        root.addWidget(self._status_label)

    def set_rom(self, rom_data):
        self._rom_data = bytearray(rom_data)
        self._status_label.setText(
            f"ROM loaded ({len(self._rom_data) // 1024} KB) \u2014 select a map to edit."
        )
        self._load_current_map()

    def get_patched_rom(self) -> Optional[bytearray]:
        return self._rom_data

    def _on_map_selected(self, _index: int):
        self._load_current_map()

    def _toggle_view(self):
        is3d = "2D" not in self._view_btn.text()
        self._chart.set_mode_3d(not is3d)
        self._view_btn.setText("Switch to 2D Heatmap" if not is3d else "Switch to 3D Surface")
        self._refresh_chart()

    def _on_cell_edited(self):
        dirty = self._table.is_dirty
        self._save_btn.setEnabled(dirty)
        self._revert_btn.setEnabled(dirty)
        self._refresh_chart()

    def _on_save(self):
        if self._rom_data is None or self._current_def is None:
            return
        data = self._table.get_map()
        if data is None:
            return
        self._write_map_to_rom(data)
        self._save_btn.setEnabled(False)
        self._revert_btn.setEnabled(False)
        self._status_label.setText(
            f"Map '{self._current_map_name}' applied \u2014 use ROM tab to flash."
        )
        self.map_modified.emit(self._current_map_name, data)

    def _on_revert(self):
        self._table.revert()
        self._save_btn.setEnabled(False)
        self._revert_btn.setEnabled(False)
        self._refresh_chart()

    def _load_current_map(self):
        name = self._map_combo.currentText()
        self._current_map_name = name
        self._current_def = _BUILTIN_MAPS.get(name)
        if self._rom_data is None:
            self._status_label.setText("Load a ROM file in the ROM tab first.")
            return
        if self._current_def is None:
            return
        data = self._read_map_from_rom()
        if data is not None:
            self._table.set_map(data, self._current_def.get("units", ""))
            self._chart.plot(data, self._current_def.get("units", ""))
            self._status_label.setText(f"Loaded '{name}' \u2014 double-click a cell to edit.")
        self._save_btn.setEnabled(False)
        self._revert_btn.setEnabled(False)

    def _read_map_from_rom(self) -> Optional[np.ndarray]:
        d = self._current_def
        if d is None or self._rom_data is None:
            return None
        offset = d["offset"]
        rows, cols = d["rows"], d["cols"]
        cell_bytes = d["cell_bytes"]
        scale = d["scale"]
        total = rows * cols * cell_bytes
        if offset + total > len(self._rom_data):
            log.warning("Map '%s' at 0x%X overflows ROM", self._current_map_name, offset)
            return None
        raw = self._rom_data[offset: offset + total]
        out = np.zeros((rows, cols), dtype=np.float32)
        fmt = ">H" if cell_bytes == 2 else ">B"
        for i in range(rows * cols):
            r, c = divmod(i, cols)
            (raw_val,) = struct.unpack_from(fmt, raw, i * cell_bytes)
            out[r, c] = raw_val * scale
        return out

    def _write_map_to_rom(self, data: np.ndarray):
        d = self._current_def
        if d is None or self._rom_data is None:
            return
        offset = d["offset"]
        rows, cols = d["rows"], d["cols"]
        cell_bytes = d["cell_bytes"]
        scale = d["scale"]
        fmt = ">H" if cell_bytes == 2 else ">B"
        for r in range(rows):
            for c in range(cols):
                raw_val = int(round(float(data[r, c]) / scale))
                raw_val = max(0, min(raw_val, 0xFFFF if cell_bytes == 2 else 0xFF))
                pos = offset + (r * cols + c) * cell_bytes
                struct.pack_into(fmt, self._rom_data, pos, raw_val)

    def _refresh_chart(self):
        data = self._table.get_map()
        if data is not None and self._current_def is not None:
            self._chart.plot(data, self._current_def.get("units", ""))
