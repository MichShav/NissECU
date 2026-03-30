"""
nissecu.core.binary_diff — Binary diff and region analysis for ROM comparison.
"""
from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

@dataclass
class DiffRegion:
    start: int; end: int; bytes_a: bytes; bytes_b: bytes

    @property
    def size(self): return self.end-self.start
    @property
    def address_str(self): return f"0x{self.start:06X}\u20130x{self.end-1:06X}"

    def hex_dump(self,max_bytes=64):
        limit=min(self.size,max_bytes); lines=[]
        for i in range(0,limit,8):
            ca=self.bytes_a[i:i+8]; cb=self.bytes_b[i:i+8]
            lines.append(f"{self.start+i:06X}:  {' '.join(f'{b:02X}' for b in ca):<23}  \u2192  {' '.join(f'{b:02X}' for b in cb):<23}")
        if self.size>max_bytes: lines.append(f"... ({self.size-max_bytes} more bytes)")
        return "\n".join(lines)

    def changed_offsets(self): return [self.start+i for i in range(min(len(self.bytes_a),len(self.bytes_b))) if self.bytes_a[i]!=self.bytes_b[i]]
    def changed_count(self): return sum(1 for a,b in zip(self.bytes_a,self.bytes_b) if a!=b)
    def to_patch_records(self): return [(self.start+i,self.bytes_a[i],self.bytes_b[i]) for i in range(min(len(self.bytes_a),len(self.bytes_b))) if self.bytes_a[i]!=self.bytes_b[i]]

def find_diff_regions(data_a, data_b, gap_tolerance=8) -> List[DiffRegion]:
    limit=min(len(data_a),len(data_b))
    if not limit: return []
    regions=[]; region_start=None; gap_count=0; i=0
    while i<limit:
        if data_a[i]!=data_b[i]:
            if region_start is None: region_start=i
            gap_count=0
        else:
            if region_start is not None:
                gap_count+=1
                if gap_count>gap_tolerance:
                    re=i-gap_count+1
                    regions.append(DiffRegion(region_start,re,bytes(data_a[region_start:re]),bytes(data_b[region_start:re])))
                    region_start=None; gap_count=0
        i+=1
    if region_start is not None:
        re=limit
        while re>region_start and data_a[re-1]==data_b[re-1]: re-=1
        if re>region_start: regions.append(DiffRegion(region_start,re,bytes(data_a[region_start:re]),bytes(data_b[region_start:re])))
    return regions

def summarize_diffs(regions: List[DiffRegion]) -> Dict:
    if not regions:
        return {"region_count":0,"total_bytes_in_regions":0,"total_bytes_changed":0,
                "largest_region":None,"smallest_region":None,"first_change":None,
                "last_change":None,"changed_offsets_sample":[]}
    sample=[]; [sample.extend(r.changed_offsets()) for r in regions if len(sample)<16]
    last=None
    for r in reversed(regions):
        offsets=r.changed_offsets()
        if offsets: last=offsets[-1]; break
    return {"region_count":len(regions),"total_bytes_in_regions":sum(r.size for r in regions),
            "total_bytes_changed":sum(r.changed_count() for r in regions),
            "largest_region":max(regions,key=lambda r:r.size),
            "smallest_region":min(regions,key=lambda r:r.size),
            "first_change":sample[0] if sample else None,"last_change":last,
            "changed_offsets_sample":sample[:16]}

def diff_to_patch(regions: List[DiffRegion]) -> bytes:
    records=[r for region in regions for r in region.to_patch_records()]
    blob=struct.pack(">I",len(records))
    for addr,_,new in records: blob+=struct.pack(">IB",addr,new)
    return blob

def apply_patch(data: bytearray, patch: bytes) -> int:
    if len(patch)<4: raise ValueError("Patch too short")
    count=struct.unpack_from(">I",patch,0)[0]; offset=4; modified=0
    for _ in range(count):
        addr,new=struct.unpack_from(">IB",patch,offset); offset+=5
        if 0<=addr<len(data): data[addr]=new; modified+=1
    return modified
