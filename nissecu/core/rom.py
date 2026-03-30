"""
nissecu.core.rom — NissanROM: ROM image parser and editor for SH7055/SH7058 ECUs.

Supports 512 KB and 1 MB ROM images used in Nissan/Infiniti G35, 350Z and related
vehicles.  Provides byte-level read/write, table helpers, flash-block management,
ROM diffing, ASCII string scanning, ECUID extraction, and basic validation.
"""

from __future__ import annotations

import hashlib
import re
import string
import struct
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROM_SIZE_512K: int = 0x80000   # 512 KB
ROM_SIZE_1M:   int = 0x100000  # 1 MB

# Flash block layout for SH7058 (16 blocks)
# Each tuple: (index, start, end)  — end is exclusive
SH7058_FLASH_BLOCKS: List[Tuple[int, int, int]] = [
    (0,  0x000000, 0x001000),
    (1,  0x001000, 0x002000),
    (2,  0x002000, 0x003000),
    (3,  0x003000, 0x004000),
    (4,  0x004000, 0x005000),
    (5,  0x005000, 0x006000),
    (6,  0x006000, 0x007000),
    (7,  0x007000, 0x008000),
    (8,  0x008000, 0x018000),
    (9,  0x018000, 0x028000),
    (10, 0x028000, 0x038000),
    (11, 0x038000, 0x048000),
    (12, 0x048000, 0x058000),
    (13, 0x058000, 0x068000),
    (14, 0x068000, 0x078000),
    (15, 0x078000, 0x080000),
]

# Flash block layout for SH7055 (13 blocks)
SH7055_FLASH_BLOCKS: List[Tuple[int, int, int]] = [
    (0,  0x000000, 0x001000),
    (1,  0x001000, 0x002000),
    (2,  0x002000, 0x003000),
    (3,  0x003000, 0x004000),
    (4,  0x004000, 0x006000),
    (5,  0x006000, 0x008000),
    (6,  0x008000, 0x010000),
    (7,  0x010000, 0x020000),
    (8,  0x020000, 0x030000),
    (9,  0x030000, 0x040000),
    (10, 0x040000, 0x050000),
    (11, 0x050000, 0x060000),
    (12, 0x060000, 0x080000),
]

# Known FID/CPU-string offsets for each MCU type
_FID_OFFSETS_BY_MCU = {
    "SH7058":      [0x7FB80, 0x7FBC0, 0x7FC00],
    "SH7055_035":  [0x7FB80, 0x7FC00],
    "SH7055_018":  [0x7DB80, 0x7DC00],
}

# Nissan part number pattern: 23710-XXXXX  (ASCII in ROM)
_NISSAN_PART_RE = re.compile(rb'2371[0-9]-[A-Z0-9]{5}')

# Broader Nissan part number: any NNNNN-XXXXX five-digit prefix
_NISSAN_PART_BROAD_RE = re.compile(rb'[2-9]\d{4}-[A-Z0-9]{5}')


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MCUType(Enum):
    SH7055_035UM = auto()   # SH7055 with 035UM mask
    SH7055_018UM = auto()   # SH7055 with 018UM mask
    SH7058       = auto()   # SH7058


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FlashBlock:
    index:    int
    start:    int
    end:      int           # exclusive
    size:     int
    data:     bytearray
    modified: bool = False

    def __repr__(self) -> str:
        mod = " [MODIFIED]" if self.modified else ""
        return (
            f"FlashBlock(#{self.index} "
            f"0x{self.start:06X}\u20130x{self.end - 1:06X} "
            f"{self.size // 1024}KB{mod})"
        )


@dataclass
class ROMMetadata:
    filename:     str
    filesize:     int
    mcu_type:     Optional[MCUType]
    sha256:       str
    reset_vector: int
    ecuid:        Optional[str]
    fid_string:   Optional[str]
    cpu_string:   Optional[str]


# ---------------------------------------------------------------------------
# NissanROM
# ---------------------------------------------------------------------------

class NissanROM:
    """
    In-memory representation of a Nissan/Infiniti SH7055/SH7058 ROM image.

    Typical usage::

        rom = NissanROM.from_file("rom.bin")
        meta = rom.metadata
        val = rom.read_u16(0x12345)
        rom.write_u16(0x12345, val + 2)
        rom.save("rom_modified.bin")
    """

    def __init__(self, data: bytes, filename: str = "<unknown>"):
        if len(data) not in (ROM_SIZE_512K, ROM_SIZE_1M):
            raise ValueError(
                f"Unsupported ROM size {len(data)} bytes. "
                f"Expected {ROM_SIZE_512K} (512 KB) or {ROM_SIZE_1M} (1 MB)."
            )
        self._data: bytearray = bytearray(data)
        self._filename = filename
        self._original: bytes = bytes(data)  # kept for diff / modified tracking

    @classmethod
    def from_file(cls, filepath: str | Path) -> "NissanROM":
        """Load a ROM image from *filepath*."""
        p = Path(filepath)
        data = p.read_bytes()
        return cls(data, filename=p.name)

    @property
    def size(self) -> int:
        return len(self._data)

    def _check_bounds(self, address: int, n: int = 1) -> None:
        if address < 0 or address + n > len(self._data):
            raise ValueError(
                f"Address 0x{address:06X}+{n} out of range "
                f"(ROM size 0x{len(self._data):06X})"
            )

    def read_byte(self, address: int) -> int:
        self._check_bounds(address)
        return self._data[address]

    def write_byte(self, address: int, value: int) -> None:
        self._check_bounds(address)
        self._data[address] = value & 0xFF

    def read_bytes(self, address: int, length: int) -> bytes:
        self._check_bounds(address, length)
        return bytes(self._data[address: address + length])

    def write_bytes(self, address: int, data: bytes) -> None:
        self._check_bounds(address, len(data))
        self._data[address: address + len(data)] = data

    def read_u16(self, address: int) -> int:
        self._check_bounds(address, 2)
        return struct.unpack_from(">H", self._data, address)[0]

    def write_u16(self, address: int, value: int) -> None:
        self._check_bounds(address, 2)
        struct.pack_into(">H", self._data, address, value & 0xFFFF)

    def read_u32(self, address: int) -> int:
        self._check_bounds(address, 4)
        return struct.unpack_from(">I", self._data, address)[0]

    def write_u32(self, address: int, value: int) -> None:
        self._check_bounds(address, 4)
        struct.pack_into(">I", self._data, address, value & 0xFFFFFFFF)

    def read_s8(self, address: int) -> int:
        v = self.read_byte(address)
        return v if v < 128 else v - 256

    def read_s16(self, address: int) -> int:
        self._check_bounds(address, 2)
        return struct.unpack_from(">h", self._data, address)[0]

    def read_table_2d(
        self,
        address: int,
        length: int,
        cell_size: int = 1,
        signed: bool = False,
    ) -> List[int]:
        """Read a 1-D array of *length* cells from *address*."""
        fmt_char = {(1, False): "B", (1, True): "b",
                    (2, False): "H", (2, True): "h"}[(cell_size, signed)]
        total = length * cell_size
        self._check_bounds(address, total)
        return list(struct.unpack_from(f">{length}{fmt_char}", self._data, address))

    def read_table_3d(
        self,
        address: int,
        rows: int,
        cols: int,
        cell_size: int = 1,
        signed: bool = False,
    ) -> List[List[int]]:
        """Read a 2-D table of *rows* x *cols* cells and return a list of rows."""
        flat = self.read_table_2d(address, rows * cols, cell_size, signed)
        return [flat[r * cols: (r + 1) * cols] for r in range(rows)]

    def write_table_3d(
        self,
        address: int,
        table: List[List[int]],
        cell_size: int = 1,
        signed: bool = False,
    ) -> None:
        """Write a 2-D table back to the ROM at *address*."""
        rows = len(table)
        cols = len(table[0]) if rows else 0
        flat = [cell for row in table for cell in row]
        fmt_char = {(1, False): "B", (1, True): "b",
                    (2, False): "H", (2, True): "h"}[(cell_size, signed)]
        total = rows * cols * cell_size
        self._check_bounds(address, total)
        struct.pack_into(f">{rows * cols}{fmt_char}", self._data, address, *flat)

    def _mcu_block_defs(self) -> List[Tuple[int, int, int]]:
        mcu = self._detect_mcu_type()
        if mcu in (MCUType.SH7055_018UM, MCUType.SH7055_035UM):
            return SH7055_FLASH_BLOCKS
        return SH7058_FLASH_BLOCKS

    def get_flash_blocks(self) -> List[FlashBlock]:
        """Return a list of FlashBlock objects covering the entire ROM."""
        blocks = []
        for idx, start, end in self._mcu_block_defs():
            size = end - start
            data = bytearray(self._data[start:end])
            orig = self._original[start:end]
            modified = data != bytearray(orig)
            blocks.append(FlashBlock(idx, start, end, size, data, modified))
        return blocks

    def get_modified_blocks(self) -> List[FlashBlock]:
        """Return only those flash blocks that differ from the original ROM."""
        return [b for b in self.get_flash_blocks() if b.modified]

    def diff(self, other: "NissanROM") -> List[Tuple[int, int, int]]:
        limit = min(len(self._data), len(other._data))
        return [
            (addr, self._data[addr], other._data[addr])
            for addr in range(limit)
            if self._data[addr] != other._data[addr]
        ]

    def diff_summary(self, other: "NissanROM") -> dict:
        changes = self.diff(other)
        if not changes:
            return {
                "total_bytes":    len(self._data),
                "changed_count":  0,
                "changed_blocks": [],
                "first_change":   None,
                "last_change":    None,
            }
        addrs = [a for a, _, _ in changes]
        block_indices: set = set()
        for idx, start, end in self._mcu_block_defs():
            for a in addrs:
                if start <= a < end:
                    block_indices.add(idx)
        return {
            "total_bytes":    len(self._data),
            "changed_count":  len(changes),
            "changed_blocks": sorted(block_indices),
            "first_change":   min(addrs),
            "last_change":    max(addrs),
        }

    def save(self, filepath: str | Path) -> None:
        """Write the current ROM contents to *filepath*."""
        Path(filepath).write_bytes(bytes(self._data))

    def to_hex(self, address: int, length: int) -> str:
        self._check_bounds(address, length)
        chunk = self._data[address: address + length]
        rows = []
        for i in range(0, len(chunk), 16):
            row_bytes = chunk[i: i + 16]
            hex_part = " ".join(f"{b:02X}" for b in row_bytes)
            ascii_part = "".join(
                chr(b) if 0x20 <= b < 0x7F else "." for b in row_bytes
            )
            rows.append(f"{address + i:06X}:  {hex_part:<47}  {ascii_part}")
        return "\n".join(rows)

    def to_c_array(self, address: int, length: int, var_name: str = "rom_data") -> str:
        self._check_bounds(address, length)
        chunk = self._data[address: address + length]
        header = (
            f"/* ROM 0x{address:06X}\u20130x{address + length - 1:06X} "
            f"({length} bytes) */"
        )
        lines = [header, f"const uint8_t {var_name}[{length}] = {{"]
        row_size = 16
        for i in range(0, len(chunk), row_size):
            row = chunk[i: i + row_size]
            hex_items = ", ".join(f"0x{b:02X}" for b in row)
            comma = "," if i + row_size < len(chunk) else ""
            lines.append(f"    {hex_items}{comma}")
        lines.append("};") 
        return "\n".join(lines)

    def extract_region(self, start: int, end: int) -> bytes:
        self._check_bounds(start, end - start)
        return bytes(self._data[start:end])

    def find_string(self, pattern: str | bytes) -> Optional[int]:
        if isinstance(pattern, str):
            needle = pattern.encode("ascii", errors="replace")
        else:
            needle = bytes(pattern)
        idx = bytes(self._data).find(needle)
        return idx if idx != -1 else None

    def find_all_strings(self, min_len: int = 4) -> List[Tuple[int, str]]:
        """Extract all printable ASCII runs of length >= min_len."""
        printable = frozenset(string.printable.encode("ascii")) - frozenset(b"\t\n\r\x0b\x0c")
        results: List[Tuple[int, str]] = []
        start: Optional[int] = None
        buf: List[int] = []

        for i, b in enumerate(self._data):
            if b in printable:
                if start is None:
                    start = i
                buf.append(b)
            else:
                if start is not None and len(buf) >= min_len:
                    results.append((start, bytes(buf).decode("ascii", errors="replace")))
                start = None
                buf = []

        if start is not None and len(buf) >= min_len:
            results.append((start, bytes(buf).decode("ascii", errors="replace")))

        return results

    def _extract_ecuid(self) -> Optional[str]:
        rom_bytes = bytes(self._data)
        m = _NISSAN_PART_RE.search(rom_bytes)
        if m:
            return m.group(0).decode("ascii")
        m = _NISSAN_PART_BROAD_RE.search(rom_bytes)
        if m:
            return m.group(0).decode("ascii")
        candidates = [
            0x7FF00, 0x7FEF0, 0x7FF20, 0x7FE00,
            0x3FF00, 0x3FEF0,
        ]
        for offset in candidates:
            if offset + 16 > len(self._data):
                continue
            chunk = rom_bytes[offset: offset + 16]
            m = _NISSAN_PART_RE.search(chunk)
            if m:
                return m.group(0).decode("ascii")
            printable_run = re.search(rb'[ -~]{8,}', chunk)
            if printable_run:
                candidate = printable_run.group(0).decode("ascii").strip()
                if candidate:
                    return candidate
        return None

    def _find_fid_string(self) -> Optional[str]:
        mcu = self._detect_mcu_type()
        mcu_key = {
            MCUType.SH7058:       "SH7058",
            MCUType.SH7055_035UM: "SH7055_035",
            MCUType.SH7055_018UM: "SH7055_018",
        }.get(mcu, "SH7058")
        for offset in _FID_OFFSETS_BY_MCU.get(mcu_key, []):
            if offset + 32 > len(self._data):
                continue
            chunk = self._data[offset: offset + 32]
            if chunk[0] in range(0x20, 0x7F):
                end = 0
                for end, b in enumerate(chunk):
                    if b == 0x00 or b not in range(0x20, 0x7F):
                        break
                candidate = bytes(chunk[:end]).decode("ascii", errors="replace").strip()
                if len(candidate) >= 4:
                    return candidate
        scan_start = max(0, len(self._data) - 0x1000)
        region = bytes(self._data[scan_start:])
        for marker in (b"NISSAN", b"INFINITI", b"SH705", b"ECM", b"ROM"):
            idx = region.find(marker)
            if idx != -1:
                abs_offset = scan_start + idx
                chunk = self._data[abs_offset: abs_offset + 32]
                candidate = re.match(rb'[ -~]+', bytes(chunk))
                if candidate and len(candidate.group(0)) >= 4:
                    return candidate.group(0).decode("ascii").strip()
        return None

    def _detect_mcu_type(self) -> MCUType:
        reset_vec = self.read_u32(len(self._data) - 4) if len(self._data) >= 4 else 0
        if len(self._data) == ROM_SIZE_512K:
            if 0x60000 <= reset_vec < 0x80000:
                return MCUType.SH7055_035UM
            return MCUType.SH7055_018UM
        if 0x60000 <= reset_vec < 0x80000:
            return MCUType.SH7055_035UM
        return MCUType.SH7058

    def _extract_cpu_string(self) -> Optional[str]:
        offsets = [len(self._data) - 0x100, len(self._data) - 0x80]
        for offset in offsets:
            if offset < 0:
                continue
            chunk = bytes(self._data[offset: offset + 64])
            for marker in (b"SH2", b"SH-2", b"SH705", b"SuperH"):
                if marker in chunk:
                    idx = chunk.find(marker)
                    run = re.match(rb'[ -~]+', chunk[idx:])
                    if run:
                        return run.group(0).decode("ascii")
        return None

    @property
    def metadata(self) -> ROMMetadata:
        """Build and return a ROMMetadata snapshot."""
        sha = hashlib.sha256(self._data).hexdigest()
        reset_vec = self.read_u32(len(self._data) - 4) if len(self._data) >= 4 else 0
        return ROMMetadata(
            filename=self._filename,
            filesize=len(self._data),
            mcu_type=self._detect_mcu_type(),
            sha256=sha,
            reset_vector=reset_vec,
            ecuid=self._extract_ecuid(),
            fid_string=self._find_fid_string(),
            cpu_string=self._extract_cpu_string(),
        )

    def validate(self) -> List[Tuple[str, str]]:
        """
        Run sanity checks on the ROM image.

        Returns a list of (severity, message) tuples where severity is
        one of "INFO", "WARNING", or "ERROR".
        """
        issues: List[Tuple[str, str]] = []

        if len(self._data) not in (ROM_SIZE_512K, ROM_SIZE_1M):
            issues.append(("ERROR", f"Unexpected ROM size: {len(self._data)} bytes"))

        if len(self._data) >= 4:
            reset = self.read_u32(len(self._data) - 4)
            if reset == 0x00000000 or reset == 0xFFFFFFFF:
                issues.append(("ERROR", f"Invalid reset vector: 0x{reset:08X}"))
            elif reset >= len(self._data):
                issues.append((
                    "WARNING",
                    f"Reset vector 0x{reset:08X} points outside ROM "
                    f"(size 0x{len(self._data):06X})"
                ))
            else:
                issues.append(("INFO", f"Reset vector: 0x{reset:08X}"))

        ff_count = self._data.count(0xFF)
        if ff_count > len(self._data) * 0.9:
            issues.append(("ERROR", "ROM appears blank (>90% 0xFF bytes)"))
        elif ff_count > len(self._data) * 0.5:
            issues.append(("WARNING", f"ROM is >50% 0xFF bytes ({ff_count} bytes)"))

        ecuid = self._extract_ecuid()
        if ecuid:
            issues.append(("INFO", f"ECUID: {ecuid}"))
        else:
            issues.append(("WARNING", "ECUID not found in ROM"))

        fid = self._find_fid_string()
        if fid:
            issues.append(("INFO", f"FID string: {fid}"))

        mcu = self._detect_mcu_type()
        issues.append(("INFO", f"Detected MCU type: {mcu.name}"))

        sha = hashlib.sha256(self._data).hexdigest()
        issues.append(("INFO", f"SHA-256: {sha}"))

        return issues
