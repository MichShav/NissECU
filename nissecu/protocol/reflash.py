"""
nissecu.protocol.reflash — ECU ROM Reflash Engine (SH7055/SH7058)

High-level flow: open programming session -> unlock security -> erase ->
write -> verify. Battery must be >= 11.5 V throughout.
"""
from __future__ import annotations
import logging, struct, time
from enum import Enum, auto
from typing import Callable, Optional
log = logging.getLogger(__name__)

DEFAULT_BLOCK_MAP = [
    (0x00000000,0x010000),(0x00010000,0x010000),(0x00020000,0x010000),
    (0x00030000,0x010000),(0x00040000,0x010000),(0x00050000,0x010000),
    (0x00060000,0x010000),(0x00070000,0x010000),
]
MIN_BATTERY_VOLTAGE=11.5
_DUMP_BPS=5000; _WRITE_BPS=1500

class ReflashError(Exception): pass
class ReflashState(Enum):
    IDLE=auto(); CONNECTED=auto(); UNLOCKED=auto(); DUMPING=auto()
    ERASING=auto(); WRITING=auto(); VERIFYING=auto(); DONE=auto(); ERROR=auto()

def check_battery_voltage(session) -> float:
    from nissecu.protocol.kwp2000 import KWP_SID, KWPMessage, ECU_ADDRESS, TESTER_ADDRESS
    resp=session._request(KWPMessage(sid=int(KWP_SID.READ_DATA_BY_LOCAL_ID),
        data=bytes([0x14]),target=ECU_ADDRESS,source=TESTER_ADDRESS),timeout=0.5)
    if resp is None or resp.is_negative_response or len(resp.data)<2: return 0.0
    return resp.data[1]*0.08

class ECUReflasher:
    def __init__(self, session, rom_data=b"", block_map=None, chunk_size=0x80):
        self._session=session; self._rom_data=bytes(rom_data)
        self._block_map=block_map or DEFAULT_BLOCK_MAP
        self._chunk_size=chunk_size; self.state=ReflashState.IDLE

    def dump_rom(self, rom_size=0x80000, chunk_size=0x100, progress_callback=None) -> Optional[bytes]:
        self.state=ReflashState.DUMPING; buf=bytearray(); offset=0
        while offset<rom_size:
            n=min(chunk_size,rom_size-offset)
            chunk=self._session.read_memory_by_address(offset,n)
            if chunk is None: self.state=ReflashState.ERROR; return None
            buf.extend(chunk); offset+=len(chunk)
            if progress_callback: progress_callback(offset,rom_size,bytes(chunk))
        self.state=ReflashState.DONE; return bytes(buf)

    def flash_rom(self, progress_callback=None, skip_blocks=None, verify=True) -> bool:
        skip_blocks=skip_blocks or []
        total=sum(s for _,s in self._block_map)
        volts=check_battery_voltage(self._session)
        if 0.0<volts<MIN_BATTERY_VOLTAGE:
            raise ReflashError(f"Battery {volts:.1f}V < {MIN_BATTERY_VOLTAGE}V")
        done=0
        self.state=ReflashState.ERASING
        for i,(addr,size) in enumerate(self._block_map):
            if i in skip_blocks: done+=size; continue
            if not self._erase_block(addr,size): self.state=ReflashState.ERROR; raise ReflashError(f"Erase failed at 0x{addr:06X}")
            done+=size
            if progress_callback: progress_callback(ReflashState.ERASING,done,total)
        self.state=ReflashState.WRITING; done=0
        for i,(addr,size) in enumerate(self._block_map):
            if i in skip_blocks: done+=size; continue
            blk=self._rom_data[addr:addr+size]
            if len(blk)<size: blk+=b"\xFF"*(size-len(blk))
            if not self._write_block(addr,blk,progress_callback,total,done):
                self.state=ReflashState.ERROR; raise ReflashError(f"Write failed at 0x{addr:06X}")
            done+=size
        if verify:
            self.state=ReflashState.VERIFYING; done=0
            for i,(addr,size) in enumerate(self._block_map):
                if i in skip_blocks: done+=size; continue
                exp=self._rom_data[addr:addr+size]
                if len(exp)<size: exp+=b"\xFF"*(size-len(exp))
                if not self.verify_block(addr,exp): self.state=ReflashState.ERROR; raise ReflashError(f"Verify failed at 0x{addr:06X}")
                done+=size
                if progress_callback: progress_callback(ReflashState.VERIFYING,done,total)
        self.state=ReflashState.DONE; return True

    def _erase_block(self,addr,size):
        ok=self._session.write_memory_by_address(addr,b"\xFF")
        if ok: time.sleep(0.2)
        return ok

    def _write_block(self,addr,data,cb,total,base):
        offset=0
        while offset<len(data):
            chunk=data[offset:offset+self._chunk_size]
            if not self._session.write_memory_by_address(addr+offset,chunk): return False
            offset+=len(chunk)
            if cb and total: cb(ReflashState.WRITING,base+offset,total)
        return True

    def verify_block(self,addr,expected) -> bool:
        offset=0; rchunk=min(self._chunk_size*2,0x100)
        while offset<len(expected):
            n=min(rchunk,len(expected)-offset)
            actual=self._session.read_memory_by_address(addr+offset,n)
            if actual is None: return False
            if actual!=expected[offset:offset+n]:
                for j,(a,e) in enumerate(zip(actual,expected[offset:offset+n])):
                    if a!=e: log.error("Verify mismatch at 0x%06X+%d: read 0x%02X expected 0x%02X",addr,offset+j,a,e); break
                return False
            offset+=n
        return True

    @staticmethod
    def estimate_time(rom_size,modified_blocks_count) -> int:
        erase=modified_blocks_count*0.25
        wb=(rom_size//len(DEFAULT_BLOCK_MAP))*modified_blocks_count
        return max(1,int(erase+wb/_WRITE_BPS+wb/_DUMP_BPS+0.9999))
