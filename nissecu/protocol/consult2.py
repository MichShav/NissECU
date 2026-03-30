"""
nissecu.protocol.consult2 — Nissan Consult-II Protocol

Frame format (host -> ECU): [CMD][LEN][DATA...][CHECKSUM]
checksum = (0x100 - sum(CMD+LEN+DATA)) & 0xFF

Init: send FF FF EF, receive 10 (ACK)
Commands: 0xD0 ECU-ID, 0x5A read regs, 0x5B stream, 0x30 stop,
          0xA0 ROM read, 0xB0 ROM write, 0xCA erase
"""
from __future__ import annotations
import struct, time, logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
log = logging.getLogger(__name__)

VQ35DE_REGISTERS: Dict[str, tuple] = {
    "rpm":          (0x0000, 12.5,    0.0,  "RPM"),
    "coolant_temp": (0x0008, 1.0,   -40.0, "°C"),
    "battery_v":    (0x000C, 0.08,   0.0,  "V"),
    "vspeed":       (0x000E, 1.0,    0.0,  "km/h"),
    "tps":          (0x0016, 0.3906, 0.0,  "%"),
    "maf":          (0x001A, 0.01,   0.0,  "g/s"),
    "map_kpa":      (0x001C, 0.0625, 0.0,  "kPa"),
    "o2_b1s1":      (0x0020, 0.01563,0.0,  "V"),
    "o2_b2s1":      (0x0022, 0.01563,0.0,  "V"),
    "injector_pw":  (0x0030, 0.01221,0.0,  "ms"),
    "ign_timing":   (0x0034, 0.375, -10.0, "°BTDC"),
    "fuel_trim_st": (0x0036, 0.01563,0.0,  "%"),
    "fuel_trim_lt": (0x0038, 0.01563,0.0,  "%"),
    "knock":        (0x0045, 1.0,    0.0,  ""),
    "closed_loop":  (0x0046, 1.0,    0.0,  ""),
    "vtc_angle":    (0x006A, 1.0,    0.0,  "°"),
    "iacv_steps":   (0x003C, 1.0,    0.0,  "steps"),
}

@dataclass
class LiveDataFrame:
    timestamp: float
    values: Dict[str, float]
    raw: Dict[str, int]

class ConsultII:
    BAUD=9600; WAKEUP=bytes([0xFF,0xFF,0xEF]); ACK=0x10
    CMD_ECU_ID=0xD0; CMD_READ_REGS=0x5A; CMD_STREAM=0x5B; CMD_STOP=0x30
    CMD_ROM_READ=0xA0; CMD_ROM_WRITE=0xB0; CMD_ERASE=0xCA
    _MAX_REGS_PER_REQUEST=16

    def __init__(self, transport):
        self._t=transport; self._streaming=False; self._stream_addresses=[]

    def initialize(self) -> bool:
        self._t.drain(); self._t.send(self.WAKEUP)
        ack=self._t.read_raw(1, timeout=0.5)
        if not ack: log.error("ConsultII.initialize: no response"); return False
        if ack[0]!=self.ACK: log.error("Unexpected ACK 0x%02X",ack[0]); return False
        log.info("ConsultII initialized"); return True

    def end_session(self):
        if self._streaming: self.stop_stream()
        try: self._t.send(self._build_frame(self.CMD_STOP, b""))
        except Exception: pass

    def read_ecu_id(self) -> Optional[Dict]:
        payload=self._send_recv(self._build_frame(self.CMD_ECU_ID,b""),timeout=1.0)
        if payload is None: return None
        part=payload[:16].rstrip(b"\x00\xff")
        try: pn=part.decode("ascii",errors="replace").strip()
        except Exception: pn=part.hex()
        return {"part_number":pn,"ecuid":payload.hex()}

    def read_register(self, address: int) -> Optional[int]:
        return self.read_registers([address]).get(address)

    def read_registers(self, addresses: List[int]) -> Dict[int,int]:
        if not addresses: return {}
        if len(addresses)>self._MAX_REGS_PER_REQUEST:
            raise ValueError(f"Max {self._MAX_REGS_PER_REQUEST} regs")
        payload=b"".join(struct.pack(">H",a) for a in addresses)
        resp=self._send_recv(self._build_frame(self.CMD_READ_REGS,payload),timeout=1.0)
        if resp is None: return {}
        return {addr: struct.unpack_from(">H",resp,i*2)[0]
                for i,addr in enumerate(addresses) if i*2+2<=len(resp)}

    def read_live_data(self, param_names=None) -> Optional[LiveDataFrame]:
        if param_names is None: param_names=list(VQ35DE_REGISTERS.keys())
        valid=[(n,VQ35DE_REGISTERS[n]) for n in param_names if n in VQ35DE_REGISTERS]
        if not valid: return None
        addresses=[e[1][0] for e in valid]; raw_vals={}
        for i in range(0,len(addresses),self._MAX_REGS_PER_REQUEST):
            batch=addresses[i:i+self._MAX_REGS_PER_REQUEST]
            r=self.read_registers(batch)
            if not r and batch: return None
            raw_vals.update(r)
        ts=time.monotonic(); values={}; raw_named={}
        for name,(addr,scale,offset,unit) in valid:
            if addr in raw_vals:
                rv=raw_vals[addr]; raw_named[name]=rv; values[name]=rv*scale+offset
        return LiveDataFrame(timestamp=ts,values=values,raw=raw_named)

    def start_stream(self, addresses: List[int]) -> bool:
        if len(addresses)>self._MAX_REGS_PER_REQUEST: raise ValueError("Max 16 regs")
        payload=b"".join(struct.pack(">H",a) for a in addresses)
        resp=self._send_recv(self._build_frame(self.CMD_STREAM,payload),timeout=1.0)
        if resp is None: return False
        self._streaming=True; self._stream_addresses=list(addresses); return True

    def stop_stream(self) -> bool:
        try: self._t.send(self._build_frame(self.CMD_STOP,b""))
        except Exception: return False
        self._streaming=False; self._t.drain(); return True

    def read_stream_frame(self) -> Optional[Dict[int,int]]:
        if not self._streaming: return None
        n=len(self._stream_addresses)
        raw=self._t.read_raw(2+n*2+1,timeout=0.5)
        if not raw: return None
        payload=self._parse_response(raw)
        if payload is None: return None
        return {addr: struct.unpack_from(">H",payload,i*2)[0]
                for i,addr in enumerate(self._stream_addresses) if i*2+2<=len(payload)}

    def read_rom_chunk(self, offset: int, length: int) -> Optional[bytes]:
        payload=bytes([(offset>>16)&0xFF,(offset>>8)&0xFF,offset&0xFF,(length>>8)&0xFF,length&0xFF])
        return self._send_recv(self._build_frame(self.CMD_ROM_READ,payload),timeout=5.0)

    def write_rom_chunk(self, offset: int, data: bytes) -> bool:
        header=bytes([(offset>>16)&0xFF,(offset>>8)&0xFF,offset&0xFF,(len(data)>>8)&0xFF,len(data)&0xFF])
        return self._send_recv(self._build_frame(self.CMD_ROM_WRITE,header+data),timeout=10.0) is not None

    def _build_frame(self, cmd: int, payload: bytes) -> bytes:
        body=bytes([cmd,len(payload)])+payload
        return body+bytes([(0x100-sum(body))&0xFF])

    def _parse_response(self, raw: bytes) -> Optional[bytes]:
        if len(raw)<3: return None
        length=raw[1]; total=2+length+1
        if len(raw)<total: return None
        payload=raw[2:2+length]; cksum=raw[2+length]
        if cksum!=((0x100-sum(raw[:2+length]))&0xFF): return None
        return payload

    def _checksum(self, data: bytes) -> int:
        return (0x100-(sum(data)&0xFF))&0xFF

    def _send_recv(self, frame: bytes, timeout: float=1.0) -> Optional[bytes]:
        self._t.send(frame)
        header=self._t.read_raw(2,timeout=timeout)
        if len(header)<2: return None
        rest=self._t.read_raw(header[1]+1,timeout=timeout)
        if len(rest)<header[1]+1: return None
        return self._parse_response(header+rest)
