"""NissECU Main Window — ECUProgrammerWindow (QMainWindow, QTabWidget)."""
from __future__ import annotations

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel,
    QMessageBox, QAction,
)
from PyQt5.QtCore import Qt

from nissecu.ui.connection_panel import ConnectionPanel
from nissecu.ui.live_data_panel import LiveDataPanel
from nissecu.ui.map_editor import MapEditorPanel
from nissecu.ui.rom_panel import ROMPanel
from nissecu.ui.logger_panel import LoggerPanel
from nissecu.ui.background_worker import LiveDataWorker
from nissecu.data_logger import DataLogger

log = logging.getLogger(__name__)

_TAB_CONNECTION = 0
_TAB_LIVE_DATA  = 1
_TAB_MAP_EDITOR = 2
_TAB_ROM        = 3
_TAB_LOGGER     = 4

_LIVE_POLL_INTERVAL_MS = 100


class ECUProgrammerWindow(QMainWindow):
    """
    Top-level application window.

    Owns ConnectionPanel, LiveDataPanel, MapEditorPanel, ROMPanel, LoggerPanel,
    DataLogger, and LiveDataWorker.  KLineInterface and ConsultII are created
    after the user clicks Connect in ConnectionPanel.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NissECU \u2014 VQ35DE ECU Programmer")
        self.resize(1100, 720)

        self._kline = None
        self._consult = None
        self._reflasher = None
        self._live_worker: Optional[LiveDataWorker] = None
        self._data_logger = DataLogger()

        self._setup_ui()
        self._setup_menu()
        self._update_status("Disconnected", ok=False)

    def _setup_ui(self):
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self.setCentralWidget(self._tabs)

        self._conn_panel = ConnectionPanel()
        self._conn_panel.connected.connect(self._on_connected)
        self._conn_panel.disconnected.connect(self._on_disconnected)
        self._tabs.addTab(self._conn_panel, "Connection")

        self._live_panel = LiveDataPanel()
        self._live_panel.set_logger(self._data_logger)
        self._live_panel.log_panel.log_start_requested.connect(self._on_log_start)
        self._live_panel.log_panel.log_stop_requested.connect(self._on_log_stop)
        self._tabs.addTab(self._live_panel, "Live Data")

        self._map_panel = MapEditorPanel()
        self._map_panel.map_modified.connect(self._on_map_modified)
        self._tabs.addTab(self._map_panel, "Map Editor")

        self._rom_panel = ROMPanel()
        self._rom_panel.rom_loaded.connect(self._on_rom_loaded)
        self._tabs.addTab(self._rom_panel, "ROM")

        self._logger_panel = LoggerPanel()
        self._logger_panel.set_logger(self._data_logger)
        self._logger_panel.log_start_requested.connect(self._on_log_start)
        self._logger_panel.log_stop_requested.connect(self._on_log_stop)
        self._tabs.addTab(self._logger_panel, "Data Logger")

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._status_main = QLabel("Disconnected")
        self._status_log = QLabel("")
        self._statusbar.addWidget(self._status_main, 1)
        self._statusbar.addPermanentWidget(self._status_log)

    def _setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        open_act = QAction("&Open ROM .bin\u2026", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._rom_panel._on_open_file)
        file_menu.addAction(open_act)
        save_act = QAction("&Save ROM .bin\u2026", self)
        save_act.setShortcut("Ctrl+S")
        save_act.triggered.connect(self._rom_panel._on_save_file)
        file_menu.addAction(save_act)
        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        ecu_menu = menubar.addMenu("&ECU")
        read_act = QAction("&Read ROM from ECU", self)
        read_act.triggered.connect(lambda: (
            self._tabs.setCurrentIndex(_TAB_ROM),
            self._rom_panel._on_read_rom()
        ))
        ecu_menu.addAction(read_act)
        ecu_menu.addSeparator()
        ecu_id_act = QAction("Show ECU &Identification\u2026", self)
        ecu_id_act.triggered.connect(self._show_ecu_id)
        ecu_menu.addAction(ecu_id_act)

        help_menu = menubar.addMenu("&Help")
        about_act = QAction("&About NissECU", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _on_connected(self, port: str, baud: int):
        log.info("GUI: connecting to %s @ %d baud", port, baud)
        try:
            from nissecu.protocol.kline import KLineInterface
            self._kline = KLineInterface(port=port, baudrate=baud)
            self._kline.open()
        except Exception as exc:
            log.exception("KLine open failed")
            self._conn_panel.set_error(str(exc))
            self._update_status(f"Error: {exc}", ok=False)
            return

        try:
            from nissecu.protocol.consult2 import ConsultII
            self._consult = ConsultII(self._kline)
            self._consult.initialize()
        except Exception as exc:
            log.warning("ConsultII init failed: %s", exc)
            self._consult = None

        if self._consult is not None:
            try:
                ecu_id = self._consult.read_ecu_id()
                if ecu_id:
                    self._show_ecu_id_data(ecu_id)
            except Exception:
                pass

        self._live_panel.set_connected(True)
        self._rom_panel.set_connected(True)
        self._logger_panel.set_connected(True)

        if self._consult is not None:
            try:
                from nissecu.protocol.reflash import ECUReflasher
                self._reflasher = ECUReflasher(session=self._consult)
                self._rom_panel.set_reflasher(self._reflasher)
            except Exception as exc:
                log.warning("Reflasher init failed: %s", exc)

        self._start_live_worker()
        self._update_status(f"Connected: {port} @ {baud}", ok=True)

    def _on_disconnected(self):
        self._stop_live_worker()
        if self._kline is not None:
            try:
                self._kline.close()
            except Exception:
                pass
            self._kline = None
        self._consult = None
        self._reflasher = None
        self._rom_panel.set_reflasher(None)
        self._rom_panel.set_connected(False)
        self._live_panel.set_connected(False)
        self._logger_panel.set_connected(False)
        self._update_status("Disconnected", ok=False)

    def _start_live_worker(self):
        if self._live_worker is not None or self._consult is None:
            return
        self._live_worker = LiveDataWorker(
            self._consult, param_names=None, interval_ms=_LIVE_POLL_INTERVAL_MS
        )
        self._live_worker.data_ready.connect(self._on_live_data)
        self._live_worker.error.connect(lambda msg: log.debug("Live data: %s", msg))
        self._live_worker.start()

    def _stop_live_worker(self):
        if self._live_worker is None:
            return
        self._live_worker.stop()
        self._live_worker = None

    def _on_live_data(self, values: dict):
        self._live_panel.update_data(values)
        if self._data_logger.is_logging():
            self._data_logger.log(values)
            self._logger_panel.update_count(self._data_logger.get_count())

    def _on_rom_loaded(self, data: bytes):
        self._map_panel.set_rom(data)

    def _on_map_modified(self, map_name: str, data):
        patched = self._map_panel.get_patched_rom()
        if patched is not None:
            self._rom_panel.load_rom_data(patched)

    def _on_log_start(self, path: str, param_names: list):
        from nissecu.ui.live_data_panel import PARAMETER_CONFIG
        fields = param_names if param_names else list(PARAMETER_CONFIG.keys())
        ok = self._data_logger.start(path, fields)
        if ok:
            self._status_log.setText(f"Logging \u2192 {path}")

    def _on_log_stop(self):
        self._data_logger.stop()
        self._status_log.setText("")

    def _show_ecu_id(self):
        if self._consult is None:
            QMessageBox.information(self, "Not Connected", "Connect to ECU first.")
            return
        try:
            self._show_ecu_id_data(self._consult.read_ecu_id())
        except Exception as exc:
            QMessageBox.warning(self, "ECU ID Error", str(exc))

    def _show_ecu_id_data(self, ecu_id):
        from nissecu.ui.dialogs import ECUIdDialog
        info = ecu_id if isinstance(ecu_id, dict) else {"ecuid": str(ecu_id)}
        ECUIdDialog(info, parent=self).exec_()

    def _show_about(self):
        QMessageBox.about(
            self, "About NissECU",
            "<b>NissECU v0.2.0</b><br>"
            "ECU programmer for Nissan G35 / 350Z (VQ35DE)<br><br>"
            "Protocol: Nissan Consult-II / KWP2000 (ISO 14230)<br>"
            "Interface: OBD-II K-Line adapter<br><br>"
            "<i>Use at your own risk. Always keep a stock ROM backup.</i>"
        )

    def _update_status(self, msg: str, ok: bool):
        self._status_main.setText(msg)
        self._status_main.setStyleSheet(
            f"color: {'#1a6e35' if ok else '#CC2936'}; font-weight: bold;"
        )

    def closeEvent(self, event):
        self._stop_live_worker()
        if self._data_logger.is_logging():
            self._data_logger.stop()
        if self._kline is not None:
            try:
                self._kline.close()
            except Exception:
                pass
        event.accept()
