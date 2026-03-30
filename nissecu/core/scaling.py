"""
nissecu.core.scaling — Linear ECU value scaling.
physical = raw * factor + offset
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Union

@dataclass
class Scaling:
    factor: float=1.0; offset: float=0.0; unit: str=""
    raw_min: int=0; raw_max: int=255; decimals: int=1

    def to_physical(self, raw): return raw*self.factor+self.offset
    def to_raw(self, physical):
        r=int(round((physical-self.offset)/self.factor)) if self.factor else 0
        return max(self.raw_min,min(self.raw_max,r))
    def format_value(self, raw):
        p=self.to_physical(raw); s=f"{p:.{self.decimals}f}"
        return f"{s} {self.unit}" if self.unit else s

    @classmethod
    def identity(cls): return cls()
    @classmethod
    def ignition_timing(cls): return cls(0.5,-64.0,"°BTDC",0,255,1)
    @classmethod
    def rpm(cls): return cls(12.5,0.0,"RPM",0,0xFFFF,0)
    @classmethod
    def coolant_temp(cls): return cls(1.0,-40.0,"°C",0,255,0)
    @classmethod
    def throttle_position(cls): return cls(0.3906,0.0,"%",0,255,1)
    @classmethod
    def maf_grams(cls): return cls(0.01,0.0,"g/s",0,0xFFFF,2)
    @classmethod
    def injector_pulsewidth(cls): return cls(0.001,0.0,"ms",0,0xFFFF,3)
    @classmethod
    def fuel_trim(cls): return cls(0.78125,-100.0,"%",0,255,1)
    @classmethod
    def lambda_target(cls): return cls(0.001,0.0,"λ",0,0xFFFF,3)
    @classmethod
    def boost_pressure(cls): return cls(0.5,0.0,"kPa",0,255,1)
