"""NissECU Connection Panel — serial port selection and ECU connect/disconnect."""
import logging
import serial.tools.list_ports

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QFormLayout, QSpinBox, QTextEdit,
    QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPalette, QFont

logger = logging.getLogger(__name__)


class StatusIndicator(QLabel):
    """Small colored circle showing connection state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._state = "disconnected"
        self._apply_style()

    def set_state(self, state: str):
        """State: 'disconnected', 'connecting', 'connected', 'error'."""
        self._state = state
        self._apply_style()

    def _apply_style(self):
        colors = {
            "disconnected": "#888888",
            "connecting":   "#FFA500",
            "connected":    "#22BB22",
            "error":        "#CC2936",
        }
        color = colors.get(self._state, "#888888")
        self.setStyleSheet(
            f"background-color: {color}; border-radius: 8px; border: 1px solid #555;"
        )
        self.setToolTip(self._state.capitalize())


class ConnectionPanel(QWidget):
    """
    Panel for managing the serial connection to the ECU.

    Signals
    -------
    connected(port, baud)   — emitted when user clicks Connect and port opens OK
    disconnected()          — emitted when the connection is closed
    log_message(str)        — emitted for each status/log line
    """

    connected = pyqtSignal(str, int)   # port, baud
    disconnected = pyqtSignal()
    log_message = pyqtSignal(str)

    # Baud rates supported by Consult-II / KWP2000
    BAUD_RATES = [1953, 4800, 9600, 14400, 19200, 38400, 57600, 115200]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_connected = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_ports)
        self._refresh_timer.start(3000)  # refresh port list every 3 s
        self._setup_ui()
        self._refresh_ports()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        grp = QGroupBox("Serial Connection")
        grp_layout = QFormLayout(grp)
        grp_layout.setSpacing(6)

        port_row = QHBoxLayout()
        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(140)
        port_row.addWidget(self._port_combo)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedWidth(70)
        self._refresh_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(self._refresh_btn)
        grp_layout.addRow("Port:", port_row)

        self._baud_combo = QComboBox()
        for b in self.BAUD_RATES:
            self._baud_combo.addItem(str(b), b)
        self._baud_combo.setCurrentIndex(0)
        grp_layout.addRow("Baud rate:", self._baud_combo)

        self._proto_combo = QComboBox()
        self._proto_combo.addItems(["Consult-II", "KWP2000 (ISO 14230)", "OBD-II (ISO 9141)"])
        grp_layout.addRow("Protocol:", self._proto_combo)

        root.addWidget(grp)

        btn_row = QHBoxLayout()
        self._status_indicator = StatusIndicator()
        btn_row.addWidget(self._status_indicator)

        self._status_label = QLabel("Disconnected")
        self._status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        btn_row.addWidget(self._status_label)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setFixedWidth(90)
        self._connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setFixedWidth(90)
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        btn_row.addWidget(self._disconnect_btn)

        root.addLayout(btn_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        log_label = QLabel("Connection Log")
        log_label.setStyleSheet("font-weight: bold;")
        root.addWidget(log_label)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Courier New", 8))
        self._log_view.setMinimumHeight(100)
        self._log_view.setMaximumHeight(180)
        root.addWidget(self._log_view)

        root.addStretch()

    def _refresh_ports(self):
        current = self._port_combo.currentText()
        self._port_combo.blockSignals(True)
        self._port_combo.clear()

        ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)
        for p in ports:
            label = f"{p.device}"
            if p.description and p.description != "n/a":
                label += f"  ({p.description})"
            self._port_combo.addItem(label, p.device)

        if not ports:
            self._port_combo.addItem("No ports found", "")

        idx = self._port_combo.findText(current, Qt.MatchContains)
        if idx >= 0:
            self._port_combo.setCurrentIndex(idx)

        self._port_combo.blockSignals(False)

    def _on_connect(self):
        port = self._port_combo.currentData()
        if not port:
            self._log("No port selected.")
            return
        baud = self._baud_combo.currentData()
        self._log(f"Connecting to {port} @ {baud} baud...")
        self._status_indicator.set_state("connecting")
        self._status_label.setText("Connecting...")
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)
        self._is_connected = True
        self._status_indicator.set_state("connected")
        self._status_label.setText(f"Connected: {port} @ {baud}")
        self._log(f"Connected to {port}.")
        self.connected.emit(port, baud)

    def _on_disconnect(self):
        self._is_connected = False
        self._status_indicator.set_state("disconnected")
        self._status_label.setText("Disconnected")
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._log("Disconnected.")
        self.disconnected.emit()

    def _log(self, message: str):
        self._log_view.append(message)
        logger.info(message)
        self.log_message.emit(message)

    def set_connected(self, port: str, baud: int):
        self._is_connected = True
        self._status_indicator.set_state("connected")
        self._status_label.setText(f"Connected: {port} @ {baud}")
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)
        self._log(f"Connection established: {port} @ {baud} baud.")

    def set_error(self, message: str):
        self._is_connected = False
        self._status_indicator.set_state("error")
        self._status_label.setText("Error")
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        self._log(f"Error: {message}")

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def selected_port(self) -> str:
        return self._port_combo.currentData() or ""

    @property
    def selected_baud(self) -> int:
        return self._baud_combo.currentData() or 1953

    @property
    def selected_protocol(self) -> str:
        return self._proto_combo.currentText()
