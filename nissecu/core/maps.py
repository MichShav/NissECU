"""
nissecu.core.maps — Map/table definitions, reading, writing, and comparison.

Provides CellType, MapCategory, Scaling, AxisDefinition, MapDefinition,
DefinitionManager (JSON loader), MapReader, MapWriter, MapDiff, compare_maps.
"""
from __future__ import annotations
import json, struct
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

class CellType(Enum):
    UINT8="uint8"; UINT16="uint16"; INT8="int8"; INT16="int16"

class MapCategory(Enum):
    FUEL="fuel"; IGNITION="ignition"; KNOCK="knock"; AIR="air"; IDLE="idle"
    VTCS="vtcs"; THROTTLE="throttle"; TORQUE="torque"; LIMITER="limiter"
    TEMPERATURE="temperature"; TRANSMISSION="transmission"; SPEED="speed"
    DTC="dtc"; SENSOR="sensor"; OTHER="other"

@dataclass
class Scaling:
    name: str; factor: float=1.0; offset: float=0.0; units: str=""
    format_str: str="{:.2f}"; min_raw: Optional[int]=None; max_raw: Optional[int]=None

    def to_engineering(self, raw): return raw*self.factor+self.offset
    def to_raw(self, eng):
        r=round((eng-self.offset)/self.factor)
        if self.min_raw is not None: r=max(self.min_raw,r)
        if self.max_raw is not None: r=min(self.max_raw,r)
        return int(r)
    def format_value(self, raw):
        s=self.format_str.format(self.to_engineering(raw))
        return f"{s} {self.units}" if self.units else s

SCALINGS: Dict[str, Scaling] = {
    "ignition_timing": Scaling("ignition_timing",0.5,-64.0,"°BTDC","{:.1f}",0,255),
    "afr_lambda":      Scaling("afr_lambda",0.001,0.0,"λ","{:.3f}",0,65535),
    "afr_ratio":       Scaling("afr_ratio",0.001*14.7,0.0,":1","{:.2f}",0,65535),
    "fuel_percent":    Scaling("fuel_percent",100.0/255,0.0,"%","{:.1f}",0,255),
    "rpm":             Scaling("rpm",1.0,0.0,"RPM","{:.0f}",0,65535),
    "rpm_x50":         Scaling("rpm_x50",50.0,0.0,"RPM","{:.0f}",0,65535),
    "load_mgstroke":   Scaling("load_mgstroke",0.01,0.0,"mg/stroke","{:.2f}",0,65535),
    "temp_celsius":    Scaling("temp_celsius",1.0,-40.0,"°C","{:.0f}",0,255),
    "maf_voltage":     Scaling("maf_voltage",5.0/255,0.0,"V","{:.3f}",0,255),
    "throttle_percent":Scaling("throttle_percent",100.0/255,0.0,"%","{:.1f}",0,255),
    "knock_threshold": Scaling("knock_threshold",0.01,0.0,"","{:.2f}",0,255),
    "raw_byte":        Scaling("raw_byte",1.0,0.0,"","{:.0f}",0,255),
    "raw_word":        Scaling("raw_word",1.0,0.0,"","{:.0f}",0,65535),
    "injector_pw":     Scaling("injector_pw",0.008,0.0,"ms","{:.3f}",0,65535),
    "vvt_angle":       Scaling("vvt_angle",0.5,0.0,"°CA","{:.1f}",0,127),
}

@dataclass
class AxisDefinition:
    address: int; length: int; cell_type: CellType=CellType.UINT8
    scaling: Optional[Scaling]=None; label: str=""
    @property
    def cell_bytes(self): return 2 if self.cell_type in (CellType.UINT16,CellType.INT16) else 1

@dataclass
class MapDefinition:
    name: str; description: str; category: MapCategory; address: int
    cell_type: CellType; scaling: Scaling; rows: int=1; cols: int=1
    x_axis: Optional[AxisDefinition]=None; y_axis: Optional[AxisDefinition]=None; notes: str=""

    @property
    def is_scalar(self): return self.rows==1 and self.cols==1
    @property
    def is_1d(self): return (self.rows==1 and self.cols>1) or (self.rows>1 and self.cols==1)
    @property
    def is_2d(self): return self.rows>1 and self.cols>1
    @property
    def data_size(self): return self.rows*self.cols
    @property
    def cell_bytes(self): return 2 if self.cell_type in (CellType.UINT16,CellType.INT16) else 1
    @property
    def is_signed(self): return self.cell_type in (CellType.INT8,CellType.INT16)

class DefinitionManager:
    def __init__(self): self._maps: Dict[str,MapDefinition]={}

    def load_definition_file(self, filepath) -> int:
        data=json.loads(Path(filepath).read_text(encoding="utf-8"))
        loaded=0
        for entry in data.get("maps",[]):
            try: self._maps[entry["name"]]=self._parse(entry); loaded+=1
            except (KeyError,ValueError) as e: import warnings; warnings.warn(str(e))
        return loaded

    def _parse(self, e) -> MapDefinition:
        sr=e.get("scaling","raw_byte")
        if isinstance(sr,str): sc=SCALINGS.get(sr,SCALINGS["raw_byte"])
        elif isinstance(sr,dict): sc=Scaling(sr.get("name",e["name"]),float(sr.get("factor",1)),float(sr.get("offset",0)),sr.get("units",""),sr.get("format_str","{:.2f}"))
        else: sc=SCALINGS["raw_byte"]
        return MapDefinition(e["name"],e.get("description",""),MapCategory(e.get("category","other")),
            _pi(e["address"]),CellType(e.get("cell_type","uint8")),sc,
            int(e.get("rows",1)),int(e.get("cols",1)),
            self._ax(e.get("x_axis")),self._ax(e.get("y_axis")),e.get("notes",""))

    @staticmethod
    def _ax(d):
        if d is None: return None
        sc=SCALINGS.get(d.get("scaling","raw_byte"),SCALINGS["raw_byte"])
        return AxisDefinition(_pi(d["address"]),int(d["length"]),CellType(d.get("cell_type","uint8")),sc,d.get("label",""))

    def get_maps(self): return list(self._maps.values())
    def get_map(self, name): return self._maps[name]
    def get_maps_by_category(self, cat): return [m for m in self._maps.values() if m.category==cat]
    def register(self, defn): self._maps[defn.name]=defn

class MapReader:
    def __init__(self, rom_data): self._rom=bytes(rom_data)

    def read_map(self, defn: MapDefinition) -> Dict[str,Any]:
        raw_flat=self._cells(defn.address,defn.data_size,defn.cell_type)
        raw_2d=[raw_flat[r*defn.cols:(r+1)*defn.cols] for r in range(defn.rows)]
        eng_2d=[[defn.scaling.to_engineering(v) for v in row] for row in raw_2d]
        xa_r=xa_e=ya_r=ya_e=None
        if defn.x_axis:
            xa_r=self._cells(defn.x_axis.address,defn.x_axis.length,defn.x_axis.cell_type)
            sc=defn.x_axis.scaling or SCALINGS["raw_word"]; xa_e=[sc.to_engineering(v) for v in xa_r]
        if defn.y_axis:
            ya_r=self._cells(defn.y_axis.address,defn.y_axis.length,defn.y_axis.cell_type)
            sc=defn.y_axis.scaling or SCALINGS["raw_word"]; ya_e=[sc.to_engineering(v) for v in ya_r]
        return {"raw":raw_2d,"engineering":eng_2d,"x_axis_raw":xa_r,"x_axis_eng":xa_e,
                "y_axis_raw":ya_r,"y_axis_eng":ya_e,"definition":defn}

    def _cells(self,addr,count,ct):
        fm={CellType.UINT8:("B",1),CellType.INT8:("b",1),CellType.UINT16:("H",2),CellType.INT16:("h",2)}
        c,w=fm[ct]; total=count*w
        if addr<0 or addr+total>len(self._rom): raise ValueError(f"Out of bounds: 0x{addr:06X}+{total}")
        return list(struct.unpack_from(f">{count}{c}",self._rom,addr))

class MapWriter:
    def __init__(self, rom_data: bytearray):
        if not isinstance(rom_data,bytearray): raise TypeError("Requires bytearray")
        self._rom=rom_data

    def write_map(self, defn, eng_values):
        flat=[v for row in eng_values for v in row]
        self._cells(defn.address,[defn.scaling.to_raw(v) for v in flat],defn.cell_type)

    def write_map_raw(self, defn, raw_values):
        self._cells(defn.address,[c for row in raw_values for c in row],defn.cell_type)

    def _cells(self,addr,values,ct):
        fm={CellType.UINT8:("B",1),CellType.INT8:("b",1),CellType.UINT16:("H",2),CellType.INT16:("h",2)}
        c,w=fm[ct]; total=len(values)*w
        if addr<0 or addr+total>len(self._rom): raise ValueError(f"Out of bounds: 0x{addr:06X}+{total}")
        struct.pack_into(f">{len(values)}{c}",self._rom,addr,*values)

@dataclass
class CellDiff:
    row: int; col: int; raw_a: int; raw_b: int; eng_a: float; eng_b: float; delta_eng: float
    @property
    def changed(self): return self.raw_a!=self.raw_b

@dataclass
class MapDiff:
    definition: MapDefinition; cells: List[List[CellDiff]]
    @property
    def changed_cells(self): return [c for row in self.cells for c in row if c.changed]
    @property
    def changed_count(self): return len(self.changed_cells)
    @property
    def max_delta(self): d=[abs(c.delta_eng) for c in self.changed_cells]; return max(d) if d else 0.0
    def summary(self): return f"Map '{self.definition.name}': {self.changed_count}/{self.definition.rows*self.definition.cols} cells changed, max \u0394={self.max_delta:.3f} {self.definition.scaling.units}"

def compare_maps(rom_a, rom_b, descriptor: MapDefinition) -> MapDiff:
    ra=MapReader(rom_a).read_map(descriptor); rb=MapReader(rom_b).read_map(descriptor)
    cells=[[CellDiff(r,c,ra["raw"][r][c],rb["raw"][r][c],ra["engineering"][r][c],rb["engineering"][r][c],rb["engineering"][r][c]-ra["engineering"][r][c])
            for c in range(descriptor.cols)] for r in range(descriptor.rows)]
    return MapDiff(descriptor,cells)

def _pi(v):
    if isinstance(v,int): return v
    s=str(v).strip(); return int(s,16) if s.startswith(("0x","0X")) else int(s)
