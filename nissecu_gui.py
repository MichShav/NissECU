#!/usr/bin/env python3
"""NissECU GUI — Launch the PyQt5 ECU Programmer interface."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from nissecu.ui.main_window import ECUProgrammerWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("NissECU")
    app.setApplicationVersion("0.2.0")
    for name in ["Segoe UI","Ubuntu","DejaVu Sans"]:
        f = QFont(name,9)
        if f.exactMatch(): app.setFont(f); break
    ECUProgrammerWindow().show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
