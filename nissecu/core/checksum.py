"""
nissecu.core.checksum — ROM checksum verification and correction.

Supports byte32 (sum+stored==0x5AA5A55A) and word16 methods.
"""
from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import List, Optional

CHECKSUM_TARGET_5AA5=0x5AA5A55A
_DESCRIPTOR_SIZE=12
_KNOWN_OFFSETS=[0x7FFF0,0x7FFEC,0x7FFF4,0x7FFFC,0x7FF00,0x7FF80,0x7FFE0,0x3FFF0,0x3FFEC,0x3FFFC]

@dataclass
class ChecksumArea:
    descriptor_offset: int; start: int; end: int; stored_sum: int; method: str
    @property
    def size(self): return self.end-self.start

@dataclass
class ChecksumResult:
    area: ChecksumArea; computed: int; valid: bool; fixed: bool=False

class ChecksumEngine:
    def __init__(self, data: bytearray):
        if not isinstance(data,bytearray): raise TypeError("Requires bytearray")
        self._data=data

    def verify(self) -> List[ChecksumResult]:
        return [ChecksumResult(a,*self._check(a)) for a in self._find_areas()]

    def fix(self) -> List[ChecksumResult]:
        results=[]
        for area in self._find_areas():
            if area.method=="word16":
                ns=self._word16(area.start,area.end)
                struct.pack_into(">H",self._data,area.descriptor_offset+8,ns)
                na=ChecksumArea(area.descriptor_offset,area.start,area.end,ns,"word16")
            else:
                raw=self._bytesum(area.start,area.end)
                ns=(CHECKSUM_TARGET_5AA5-raw)&0xFFFFFFFF
                struct.pack_into(">I",self._data,area.descriptor_offset+8,ns)
                na=ChecksumArea(area.descriptor_offset,area.start,area.end,ns,"byte32")
            results.append(ChecksumResult(na,*self._check(na),fixed=True))
        return results

    @staticmethod
    def verify_quick(rom_data: bytes) -> bool:
        if len(rom_data)<0x10000: return False
        return (sum(rom_data[-0x10000:])&0xFFFFFFFF)==CHECKSUM_TARGET_5AA5

    def _find_areas(self):
        seen=set(); areas=[]
        for off in _KNOWN_OFFSETS:
            if off+12>len(self._data): continue
            s,e,st=struct.unpack_from(">III",self._data,off)
            if s>=e or e>len(self._data) or s in seen: continue
            if s&3 or e&3 or (e-s)<256 or (e-s)%256: continue
            seen.add(s)
            method="word16" if st<=0xFFFF and self._word16(s,e)==st else "byte32"
            areas.append(ChecksumArea(off,s,e,st,method))
        return areas or self._scan()

    def _scan(self):
        areas=[]; seen=set()
        for off in range(0,len(self._data)-12,4):
            s,e,st=struct.unpack_from(">III",self._data,off)
            if s>=e or e>len(self._data) or s in seen: continue
            if s&3 or e&3 or (e-s)<256 or (e-s)%256: continue
            if st in (0,0xFFFFFFFF): continue
            raw=self._bytesum(s,e)
            if (raw+st)&0xFFFFFFFF==CHECKSUM_TARGET_5AA5:
                areas.append(ChecksumArea(off,s,e,st,"byte32")); seen.add(s)
            elif st<=0xFFFF and self._word16(s,e)==st:
                areas.append(ChecksumArea(off,s,e,st,"word16")); seen.add(s)
            if len(areas)>=8: break
        return areas

    def _check(self, area):
        if area.method=="word16":
            c=self._word16(area.start,area.end); return c,c==area.stored_sum
        raw=self._bytesum(area.start,area.end)
        full=(raw+area.stored_sum)&0xFFFFFFFF; return full,full==CHECKSUM_TARGET_5AA5

    def _bytesum(self,s,e): return sum(self._data[s:e])&0xFFFFFFFF
    def _word16(self,s,e):
        t=0; i=s
        while i+1<=e: t=(t+((self._data[i]<<8)|self._data[i+1]))&0xFFFF; i+=2
        if i<e: t=(t+(self._data[i]<<8))&0xFFFF
        return t
