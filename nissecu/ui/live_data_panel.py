"""Live data monitoring panel with analog gauges and parameter table."""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton,
    QLineEdit, QFileDialog, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QRectF
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QBrush, QFontMetrics
import math

PARAMETER_CONFIG = {
    "rpm":          {"label": "RPM",       "min": 0,    "max": 8000, "units": "RPM",    "warn_high": 6500},
    "coolant_temp": {"label": "Coolant",   "min": -40,  "max": 130,  "units": "\u00b0C",     "warn_high": 105, "warn_low": -10},
    "tps":          {"label": "Throttle",  "min": 0,    "max": 100,  "units": "%"},
    "maf":          {"label": "MAF",       "min": 0,    "max": 200,  "units": "g/s"},
    "injector_pw":  {"label": "Inj PW",    "min": 0,    "max": 20,   "units": "ms"},
    "ign_timing":   {"label": "Timing",    "min": -15,  "max": 55,   "units": "\u00b0",      "warn_high": 48},
    "fuel_trim_st": {"label": "ST Trim",   "min": -25,  "max": 25,   "units": "%",      "warn_high": 15, "warn_low": -15},
    "fuel_trim_lt": {"label": "LT Trim",   "min": -25,  "max": 25,   "units": "%",      "warn_high": 15, "warn_low": -15},
    "battery_v":    {"label": "Battery",   "min": 9,    "max": 16,   "units": "V",      "warn_low": 11.5},
    "vspeed":       {"label": "Speed",     "min": 0,    "max": 250,  "units": "km/h"},
    "o2_b1s1":      {"label": "O2 B1S1",  "min": 0,    "max": 1.5,  "units": "V"},
    "o2_b2s1":      {"label": "O2 B2S1",  "min": 0,    "max": 1.5,  "units": "V"},
    "vtc_angle":    {"label": "VTC",       "min": 0,    "max": 50,   "units": "\u00b0"},
    "knock":        {"label": "Knock",     "min": 0,    "max": 10,   "units": "",       "warn_high": 1},
}


class AnalogGaugeWidget(QWidget):
    """Arc-style analog gauge drawn with QPainter."""

    ARC_START = 220
    ARC_SPAN  = 260

    def __init__(self, param_name: str, config: dict, parent=None):
        super().__init__(parent)
        self.param_name = param_name
        self.config = config
        self._value = config["min"]
        self.setMinimumSize(140, 140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_value(self, value: float):
        self._value = value
        self.update()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        side = min(w, h) - 10
        cx, cy = w / 2, h / 2

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        cfg = self.config
        mn, mx = cfg["min"], cfg["max"]
        val = max(mn, min(mx, self._value))
        t = (val - mn) / (mx - mn) if mx != mn else 0.0

        warn_h = cfg.get("warn_high")
        warn_l = cfg.get("warn_low")
        if warn_h is not None and val >= warn_h:
            arc_color = QColor("#CC2936")
        elif warn_l is not None and val <= warn_l:
            arc_color = QColor("#D4620B")
        else:
            arc_color = QColor("#2D9E5F")

        r = side / 2
        rect = QRectF(cx - r, cy - r, side, side)

        p.setBrush(QBrush(QColor("#1a1a1a")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(rect)

        pen = QPen(QColor("#333333"), max(8, side * 0.06))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int((180 - self.ARC_START) * 16), -int(self.ARC_SPAN * 16))

        span = int(t * self.ARC_SPAN)
        if span > 0:
            pen2 = QPen(arc_color, max(8, side * 0.06))
            pen2.setCapStyle(Qt.RoundCap)
            p.setPen(pen2)
            p.drawArc(rect, int((180 - self.ARC_START) * 16), -int(span * 16))

        angle_deg = self.ARC_START - t * self.ARC_SPAN
        angle_rad = math.radians(angle_deg)
        needle_len = r * 0.65
        nx = cx + needle_len * math.cos(angle_rad)
        ny = cy - needle_len * math.sin(angle_rad)
        pen3 = QPen(QColor("#ffffff"), max(2, int(side * 0.02)))
        pen3.setCapStyle(Qt.RoundCap)
        p.setPen(pen3)
        p.drawLine(int(cx), int(cy), int(nx), int(ny))

        dot_r = max(4, int(side * 0.04))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx - dot_r), int(cy - dot_r), dot_r * 2, dot_r * 2)

        val_font = QFont("Monospace", max(10, int(side * 0.14)), QFont.Bold)
        p.setFont(val_font)
        p.setPen(QPen(QColor("#ffffff")))
        val_str = f"{val:.0f}" if abs(val) >= 10 else f"{val:.1f}"
        p.drawText(rect.adjusted(0, side * 0.15, 0, 0),
                   Qt.AlignHCenter | Qt.AlignVCenter, val_str)

        lbl_font = QFont("Monospace", max(7, int(side * 0.08)))
        p.setFont(lbl_font)
        p.setPen(QPen(QColor("#888888")))
        p.drawText(rect.adjusted(0, side * 0.42, 0, 0),
                   Qt.AlignHCenter | Qt.AlignVCenter,
                   cfg.get("units", ""))

        name_font = QFont("Monospace", max(7, int(side * 0.09)), QFont.Bold)
        p.setFont(name_font)
        p.setPen(QPen(QColor("#aaaaaa")))
        p.drawText(int(cx - r), int(cy + r * 0.55), int(side),
                   int(side * 0.25), Qt.AlignHCenter, cfg.get("label", self.param_name))

        p.end()


class ParameterTableWidget(QWidget):
    """Scrollable table showing live parameters with session min/max."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mins: dict = {}
        self._maxs: dict = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Parameter", "Value", "Units", "Min", "Max"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("font-family: monospace; font-size: 10px;")
        self._table.setMinimumHeight(200)

        mono = QFont("Courier New", 9)
        self._row_map = {}
        for i, (name, cfg) in enumerate(PARAMETER_CONFIG.items()):
            self._table.insertRow(i)
            self._table.setItem(i, 0, QTableWidgetItem(cfg["label"]))
            self._table.setItem(i, 1, QTableWidgetItem("\u2014"))
            self._table.setItem(i, 2, QTableWidgetItem(cfg.get("units", "")))
            self._table.setItem(i, 3, QTableWidgetItem("\u2014"))
            self._table.setItem(i, 4, QTableWidgetItem("\u2014"))
            for col in range(5):
                item = self._table.item(i, col)
                if item:
                    item.setFont(mono)
                    item.setTextAlignment(Qt.AlignCenter)
            self._row_map[name] = i

        self._table.resizeRowsToContents()
        layout.addWidget(self._table)

    def update_values(self, values: dict):
        for name, val in values.items():
            if name not in self._row_map:
                continue
            row = self._row_map[name]
            cfg = PARAMETER_CONFIG.get(name, {})

            if name not in self._mins:
                self._mins[name] = val
                self._maxs[name] = val
            else:
                self._mins[name] = min(self._mins[name], val)
                self._maxs[name] = max(self._maxs[name], val)

            val_str = f"{val:.1f}" if isinstance(val, float) else str(val)
            min_str = f"{self._mins[name]:.1f}"
            max_str = f"{self._maxs[name]:.1f}"

            self._table.item(row, 1).setText(val_str)
            self._table.item(row, 3).setText(min_str)
            self._table.item(row, 4).setText(max_str)

            warn_h = cfg.get("warn_high")
            warn_l = cfg.get("warn_low")
            color = None
            if warn_h is not None and val >= warn_h:
                color = QColor("#FFDDDD")
            elif warn_l is not None and val <= warn_l:
                color = QColor("#FFF0DD")
            if color:
                for col in range(5):
                    item = self._table.item(row, col)
                    if item:
                        item.setBackground(QBrush(color))


class DataLogPanel(QWidget):
    """Logging controls bar."""
    log_start_requested = pyqtSignal(str, list)
    log_stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logging = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        layout.addWidget(QLabel("Log file:"))
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("nissecu_log_YYYYMMDD_HHMMSS.csv")
        layout.addWidget(self._path_edit, 1)

        browse_btn = QPushButton("Browse\u2026")
        browse_btn.clicked.connect(self._browse)
        layout.addWidget(browse_btn)

        self._toggle_btn = QPushButton("Start Logging")
        self._toggle_btn.setStyleSheet("font-weight: bold;")
        self._toggle_btn.clicked.connect(self._toggle)
        layout.addWidget(self._toggle_btn)

        self._count_label = QLabel("0 samples")
        self._count_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self._count_label)

    def _browse(self):
        from nissecu.data_logger import DataLogger
        default = DataLogger.auto_filename()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Log File", default, "CSV Files (*.csv)"
        )
        if path:
            self._path_edit.setText(path)

    def _toggle(self):
        if not self._logging:
            path = self._path_edit.text().strip()
            if not path:
                from nissecu.data_logger import DataLogger
                path = DataLogger.auto_filename()
                self._path_edit.setText(path)
            params = list(PARAMETER_CONFIG.keys())
            self._logging = True
            self._toggle_btn.setText("Stop Logging")
            self._toggle_btn.setStyleSheet("font-weight: bold; color: #CC2936;")
            self.log_start_requested.emit(path, params)
        else:
            self._logging = False
            self._toggle_btn.setText("Start Logging")
            self._toggle_btn.setStyleSheet("font-weight: bold;")
            self.log_stop_requested.emit()

    def set_logging_state(self, logging: bool, count: int = 0):
        self._logging = logging
        if logging:
            self._toggle_btn.setText("Stop Logging")
            self._toggle_btn.setStyleSheet("font-weight: bold; color: #CC2936;")
            self._count_label.setText(f"{count:,} samples")
        else:
            self._toggle_btn.setText("Start Logging")
            self._toggle_btn.setStyleSheet("font-weight: bold;")
            self._count_label.setText("0 samples")


class LiveDataPanel(QWidget):
    """Main live data panel: top gauges + parameter table + log controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logger = None
        self._setup_ui()
        self.set_connected(False)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        gauge_row = QHBoxLayout()
        self._gauges = {}
        for name in ("rpm", "coolant_temp", "tps", "maf"):
            cfg = PARAMETER_CONFIG[name]
            g = AnalogGaugeWidget(name, cfg)
            g.setFixedSize(150, 150)
            self._gauges[name] = g
            gauge_row.addWidget(g)
        layout.addLayout(gauge_row)

        self._table = ParameterTableWidget()
        layout.addWidget(self._table, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)
        self._log_panel = DataLogPanel()
        layout.addWidget(self._log_panel)

        self._overlay = QLabel("Not connected \u2014 select a port and click Connect")
        self._overlay.setAlignment(Qt.AlignCenter)
        self._overlay.setStyleSheet(
            "background: rgba(255,255,255,0.85); color: #888; font-size: 13px; border-radius: 6px;"
        )
        self._overlay.setParent(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.setGeometry(0, 0, self.width(), self.height())

    def update_data(self, values: dict):
        for name, gauge in self._gauges.items():
            if name in values:
                gauge.set_value(values[name])
        self._table.update_values(values)
        if self._logger and self._logger.is_logging():
            self._logger.log(values)
            count = self._logger.get_count()
            self._log_panel.set_logging_state(True, count)

    def set_connected(self, connected: bool):
        self._overlay.setVisible(not connected)

    def set_logger(self, logger):
        self._logger = logger

    @property
    def log_panel(self):
        return self._log_panel
