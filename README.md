# NissECU

**NissECU** is an open-source ECU programming and tuning suite for Nissan and Infiniti vehicles equipped with the **VQ35DE** engine (Nissan 350Z / Infiniti G35). It communicates with the ECU over the OBD-II K-Line interface using the Nissan Consult-II and KWP2000 (ISO 14230) protocols, and targets **SH7055** and **SH7058** Renesas microcontrollers.

> **Use at your own risk. Always keep a verified stock ROM backup before flashing.**

---

## Features

| Tab | Capability |
|-----|------------|
| **Connection** | Serial port auto-scan, baud rate selection, Consult-II / KWP2000 protocol selector, connection log |
| **Live Data** | 14 real-time parameters with analog arc gauges, tabular min/max tracking, inline CSV session logging |
| **Map Editor** | Editable 16×16 and 8×8 fuel/ignition/VTC tables with HSV colour gradient and embedded matplotlib 3D surface / 2D heatmap |
| **ROM** | Full 512 KB / 1 MB ROM dump and flash via background worker threads; hex viewer; MD5 checksum display; three-step flash confirmation dialog |
| **Data Logger** | CSV logging with live tail preview, configurable row count, auto-timestamped filenames |

### Protocol Support
- **Nissan Consult-II** — framed serial at 1953–115200 baud; 17 VQ35DE-specific register addresses
- **KWP2000 / ISO 14230** — session management, memory R/W, DTC read/clear, SID 0x27 security access
- **SID 0x27 Seed-to-Key** — two on-ROM bit-shift algorithms (`enc1`, `enc2`) with ROM constant search
- **ROM Reflash** — block-based erase / write / verify with battery voltage pre-check; 8 × 64 KB default block map

---

## Built From

NissECU was developed from work originating in the
[**J2EOverlay**](https://github.com/MichShav/J2EOverlay) project by [@MichShav](https://github.com/MichShav).
J2EOverlay provided the foundational ECU programmer architecture, protocol framing, and GUI scaffolding that NissECU extends into a standalone tuning application.

---

## Requirements

- Python 3.9+
- PyQt5 >= 5.15
- pyserial >= 3.5
- numpy >= 1.21
- matplotlib >= 3.7
- scipy >= 1.10

Install all dependencies:

```bash
pip install -r requirements.txt
```

---

## Installation

```bash
git clone https://github.com/MichShav/NissECU.git
cd NissECU
pip install -r requirements.txt
python nissecu_gui.py
```

No build step is required. The application runs directly from source.

---

## Hardware

Any OBD-II K-Line adapter presenting as a virtual COM port is supported (e.g. FTDI-based Consult cables, ISO 9141-2 K+L adapters). **CAN-only ELM327 adapters will not work** — K-Line physical access is required.

---

## Project Structure

```
nissecu_gui.py          # Entry point
nissecu/
  __init__.py
  data_logger.py        # CSV session logger
  protocol/
    consult2.py         # Nissan Consult-II framing + VQ35DE register map
    kwp2000.py          # KWP2000 / ISO 14230 session layer
    sid27.py            # Seed-to-key algorithms and ROM constant search
    reflash.py          # Block erase / write / verify engine
    kline.py            # K-Line physical interface (serial)
  core/
    rom.py              # NissanROM: read/write tables, diff, validate
    maps.py             # MapDefinition, DefinitionManager, MapReader/Writer
    checksum.py         # ROM checksum verify and fix
    scaling.py          # Physical unit conversions
    binary_diff.py      # Patch generation and application
  ui/
    main_window.py      # ECUProgrammerWindow (QMainWindow)
    connection_panel.py # Serial port UI
    live_data_panel.py  # Gauges and parameter table
    map_editor.py       # Editable map table + matplotlib canvas
    rom_panel.py        # ROM dump/flash + hex viewer
    logger_panel.py     # CSV log viewer with live tail
    background_worker.py# ROMDumpWorker, ROMFlashWorker, LiveDataWorker (QThread)
    dialogs.py          # ConfirmFlashDialog, ECUIdDialog, KeySearchDialog
```

---

## Disclaimer

Flashing ECU firmware carries real risk. An interrupted or corrupt flash can permanently disable the ECU and may require bench recovery. The authors accept no liability for damaged hardware, voided warranties, or any other consequence arising from the use of this software.

---

## License

Copyright (c) 2024 MichShav

This project is released under the **NissECU Non-Commercial Source License** — see [LICENSE](LICENSE) for full terms.

Short summary: you may view, fork, modify, and distribute the source for **personal and non-commercial use only**. Commercial use, resale, or incorporation into a paid product or service is not permitted without explicit written permission from the author.
