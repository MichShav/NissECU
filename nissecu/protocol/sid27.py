"""
nissecu.protocol.sid27 — KWP2000 Security Access (SID 0x27) Key Generation

Implements seed-to-key algorithms for Nissan/Infiniti SH7055/SH7058 ECUs.
Actual key_constant values must be derived from your own ROM dump.
"""
from __future__ import annotations
import logging, struct, time
from typing import Callable, Dict, Optional
log = logging.getLogger(__name__)

KNOWN_KEYS: Dict[str, Optional[tuple]] = {
    "VQ35DE_2003": None, "VQ35DE_2004": None, "VQ35DE_2005": None,
    "VQ35DE_2006": None, "VQ35DE_REVUP": None, "VQ35HR_2007": None,
    "VQ35HR_2008": None, "VQ37VHR_2009": None, "SR20DET_S15": None,
    "RB26DETT_R34": None,
}

def enc1(seed: int, key: int) -> int:
    result=seed
    for _ in range(32):
        if result&0x80000000: result=((result<<1)&0xFFFFFFFF)^key
        else: result=(result<<1)&0xFFFFFFFF
    return result

def enc2(seed: int, key: int) -> int:
    result=seed
    for _ in range(32):
        if result&0x00000001: result=((result>>1)|0x80000000)^key
        else: result=(result>>1)&0x7FFFFFFF
    return result

def generate_key_algo1(seed_bytes: bytes, key_constant: int) -> bytes:
    if len(seed_bytes)!=4: raise ValueError("seed must be 4 bytes")
    s=struct.unpack(">I",seed_bytes)[0]
    return struct.pack(">I",enc2(enc1(s,key_constant),key_constant))

def generate_key_algo2(seed_bytes: bytes, key_constant: int) -> bytes:
    if len(seed_bytes)!=4: raise ValueError("seed must be 4 bytes")
    s=struct.unpack(">I",seed_bytes)[0]
    return struct.pack(">I",enc1(enc2(s,key_constant),key_constant))

def make_key_function(key_constant: int, algorithm: int=1) -> Callable[[bytes],bytes]:
    gen=generate_key_algo1 if algorithm==1 else generate_key_algo2 if algorithm==2 else None
    if gen is None: raise ValueError(f"Unknown algorithm {algorithm}")
    def _key(seed): return gen(seed, key_constant)
    return _key

def search_key_in_rom(rom_data: bytes, test_seed=b"\x12\x34\x56\x78", algorithm=1) -> Optional[int]:
    gen=generate_key_algo1 if algorithm==1 else generate_key_algo2
    trivial={b"\x00"*4,b"\xFF"*4,test_seed}
    t0=time.monotonic()
    for i in range(0,len(rom_data)-3,4):
        c=struct.unpack_from(">I",rom_data,i)[0]
        if c in (0,0xFFFFFFFF): continue
        try:
            if gen(test_seed,c) not in trivial: return c
        except Exception: pass
    return None

def get_known_key(identifier: str) -> Optional[tuple]:
    entry=KNOWN_KEYS.get(identifier)
    if entry is None: log.warning("Key %r not confirmed in KNOWN_KEYS",identifier)
    return entry

def test_key(transport_or_session, key_constant, algorithm=1, test_seed=None) -> bool:
    from nissecu.protocol.kwp2000 import KWP2000Session, SessionType
    owns=False
    if isinstance(transport_or_session, KWP2000Session): session=transport_or_session
    else: session=KWP2000Session(transport_or_session); owns=True
    try:
        if owns and not session.start_session(SessionType.PROGRAMMING): return False
        seed=test_seed or session.request_seed(level=0x01)
        if seed is None or len(seed)!=4: return False
        return session.send_key(level=0x01, key=make_key_function(key_constant,algorithm)(seed))
    finally:
        if owns: session.end_session()
