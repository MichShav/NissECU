"""CSV data logger for live ECU parameters."""
import csv, time
from typing import List, Dict, Optional
from pathlib import Path

class DataLogger:
    def __init__(self, log_dir="./logs"):
        self._log_dir=Path(log_dir); self._log_dir.mkdir(parents=True,exist_ok=True)
        self._file=None; self._writer=None; self._fields=[]
        self._count=0; self._start_time=None; self._filepath=None

    def start(self, filepath, fields):
        if self.is_logging(): return False
        try:
            self._filepath=filepath; self._fields=fields
            self._file=open(filepath,"w",newline="",buffering=1)
            self._writer=csv.DictWriter(self._file,fieldnames=["timestamp"]+fields,extrasaction="ignore")
            self._writer.writeheader(); self._count=0; self._start_time=time.time(); return True
        except OSError: self._file=None; self._writer=None; return False

    def stop(self):
        if self._file: self._file.flush(); self._file.close(); self._file=None; self._writer=None

    def log(self, values):
        if not self.is_logging(): return False
        row={"timestamp":round(time.time()-self._start_time,3)}; row.update(values)
        self._writer.writerow(row); self._count+=1; return True

    def is_logging(self): return self._file is not None and not self._file.closed
    def get_count(self): return self._count
    def get_elapsed(self): return 0.0 if self._start_time is None else time.time()-self._start_time
    def get_filepath(self): return self._filepath

    @staticmethod
    def auto_filename(prefix="nissecu_log"): return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
