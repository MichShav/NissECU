"""Background QThread workers for long-running ECU operations."""
from PyQt5.QtCore import QThread, pyqtSignal
import logging, time

logger = logging.getLogger(__name__)


class ROMDumpWorker(QThread):
    """Worker thread for ROM dump \u2014 keeps GUI responsive during multi-minute reads."""
    progress = pyqtSignal(int, int)     # bytes_done, total_bytes
    finished = pyqtSignal(bool, bytes)  # success, data
    error = pyqtSignal(str)

    def __init__(self, reflasher, rom_size=0x100000, parent=None):
        super().__init__(parent)
        self.reflasher = reflasher
        self.rom_size = rom_size
        self._cancelled = False

    def run(self):
        try:
            data = self.reflasher.dump_rom(
                rom_size=self.rom_size,
                progress_callback=lambda done, total: self.progress.emit(done, total)
            )
            if data:
                self.finished.emit(True, data)
            else:
                self.finished.emit(False, b"")
        except Exception as exc:
            logger.exception("ROM dump failed")
            self.error.emit(str(exc))
            self.finished.emit(False, b"")

    def cancel(self):
        self._cancelled = True


class ROMFlashWorker(QThread):
    """Worker thread for ROM flash."""
    progress = pyqtSignal(str, int, int)  # phase, block_num, total_blocks
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, reflasher, rom_data: bytes, key_func,
                 original_rom=None, verify=True, parent=None):
        super().__init__(parent)
        self.reflasher = reflasher
        self.rom_data = rom_data
        self.key_func = key_func
        self.original_rom = original_rom
        self.verify = verify
        self._cancelled = False

    def run(self):
        try:
            self.reflasher.flash_rom(
                rom_data=self.rom_data,
                key_func=self.key_func,
                original_rom=self.original_rom,
                verify=self.verify,
                progress_callback=lambda phase, blk, tot: self.progress.emit(phase, blk, tot)
            )
            self.finished.emit(True)
        except Exception as exc:
            logger.exception("ROM flash failed")
            self.error.emit(str(exc))
            self.finished.emit(False)

    def cancel(self):
        self._cancelled = True


class LiveDataWorker(QThread):
    """Background polling worker for live ECU parameters via Consult-II."""
    data_ready = pyqtSignal(dict)  # {param_name: float_value}
    error = pyqtSignal(str)

    def __init__(self, consult, param_names=None, interval_ms=100, parent=None):
        super().__init__(parent)
        self.consult = consult
        self.param_names = param_names
        self.interval_ms = interval_ms
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            try:
                frame = self.consult.read_live_data(self.param_names)
                if frame is not None:
                    self.data_ready.emit(frame.values)
            except Exception as exc:
                logger.warning(f"Live data read error: {exc}")
                self.error.emit(str(exc))
            self.msleep(self.interval_ms)

    def stop(self):
        self._running = False
        self.wait(2000)
