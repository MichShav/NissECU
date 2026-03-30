"""
nissecu.protocol.kwp2000 — KWP2000 (ISO 14230) Session Manager

Typical usage:
    transport = KLineInterface(KLineConfig(port="/dev/ttyUSB0", baudrate=10400))
    transport.open()
    session = KWP2000Session(transport)
    session.start_session(SessionType.PROGRAMMING)
    data = session.read_memory_by_address(0x00000000, 0x100)
    session.end_session(); transport.close()
"""
from __future__ import annotations
import logging, struct, time
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional
log = logging.getLogger(__name__)

ECU_ADDRESS=0x10; TESTER_ADDRESS=0xF0; STANDARD_BAUD=10400; KERNEL_BAUD=62500

class SessionType(IntEnum):
    DEFAULT=0x81; PROGRAMMING=0x85; EXTENDED_DIAGNOSTIC=0x86

class KWP_SID(IntEnum):
    START_COMMUNICATION=0x81; STOP_COMMUNICATION=0x82
    START_DIAGNOSTIC_SESSION=0x10; ECU_RESET=0x11
    READ_MEMORY_BY_ADDRESS=0x23; WRITE_MEMORY_BY_ADDRESS=0x3D
    CLEAR_DIAGNOSTIC_INFO=0x14; READ_DTC_BY_STATUS=0x18
    SECURITY_ACCESS=0x27; TESTER_PRESENT=0x3E
    READ_DATA_BY_LOCAL_ID=0x21; WRITE_DATA_BY_LOCAL_ID=0x2E

class KWP_NRC(IntEnum):
    GENERAL_REJECT=0x10; SERVICE_NOT_SUPPORTED=0x11
    CONDITIONS_NOT_CORRECT=0x22; REQUEST_OUT_OF_RANGE=0x31
    SECURITY_ACCESS_DENIED=0x33; INVALID_KEY=0x35
    BUSY_REPEAT_REQUEST=0x21; RESPONSE_PENDING=0x78

@dataclass
class KWPMessage:
    sid: int
    data: bytes = b""
    target: int = ECU_ADDRESS
    source: int = TESTER_ADDRESS

    def to_bytes(self) -> bytes:
        payload=bytes([self.sid])+self.data
        header=bytes([0x80,self.target,self.source,len(payload)])
        body=header+payload
        return body+bytes([sum(body)&0xFF])

    @classmethod
    def from_bytes(cls, raw: bytes) -> "KWPMessage":
        if len(raw)<5: raise ValueError(f"Frame too short: {len(raw)}")
        _,target,source,length=raw[0],raw[1],raw[2],raw[3]
        if len(raw)<4+length+1: raise ValueError("Frame truncated")
        payload=raw[4:4+length]; cksum=raw[4+length]
        computed=sum(raw[:4+length])&0xFF
        if cksum!=computed: raise ValueError(f"Checksum error: {computed:02X}!={cksum:02X}")
        return cls(sid=payload[0],data=payload[1:],target=source,source=target)

    @property
    def is_positive_response(self): return self.sid==(self._req_sid()+0x40)
    @property
    def is_negative_response(self): return self.sid==0x7F
    def _req_sid(self):
        if self.is_negative_response and self.data: return self.data[0]
        return self.sid-0x40
    @property
    def nrc(self): return self.data[1] if self.is_negative_response and len(self.data)>=2 else None

class KWP2000Session:
    _MAX_BUSY_RETRIES=3; _BUSY_RETRY_DELAY=0.1

    def __init__(self, transport, ecu_address=ECU_ADDRESS, tester_address=TESTER_ADDRESS):
        self._transport=transport; self._ecu=ecu_address; self._tester=tester_address
        self._session_type=None

    @property
    def is_connected(self): return self._session_type is not None

    def start_session(self, session_type=SessionType.DEFAULT) -> bool:
        resp=self._request(KWPMessage(sid=int(KWP_SID.START_DIAGNOSTIC_SESSION),
            data=bytes([int(session_type)]),target=self._ecu,source=self._tester))
        if resp is None or resp.is_negative_response:
            log.error("start_session failed"); return False
        self._session_type=session_type; return True

    def end_session(self):
        try:
            self._request(KWPMessage(sid=int(KWP_SID.STOP_COMMUNICATION),
                target=self._ecu,source=self._tester),timeout=0.5)
        except Exception: pass
        finally: self._session_type=None

    def ping(self) -> bool:
        resp=self._request(KWPMessage(sid=int(KWP_SID.TESTER_PRESENT),
            data=bytes([0x01]),target=self._ecu,source=self._tester),timeout=0.5)
        return resp is not None and not resp.is_negative_response

    def request_seed(self, level=0x01) -> Optional[bytes]:
        resp=self._request(KWPMessage(sid=int(KWP_SID.SECURITY_ACCESS),
            data=bytes([level]),target=self._ecu,source=self._tester))
        if resp is None or resp.is_negative_response: return None
        return resp.data[1:] if len(resp.data)>1 else b""

    def send_key(self, level: int, key: bytes) -> bool:
        resp=self._request(KWPMessage(sid=int(KWP_SID.SECURITY_ACCESS),
            data=bytes([level+1])+key,target=self._ecu,source=self._tester))
        return resp is not None and not resp.is_negative_response

    def read_memory_by_address(self, address: int, length: int) -> Optional[bytes]:
        addr_b=struct.pack(">I",address)[1:]; len_b=struct.pack(">H",length)
        resp=self._request(KWPMessage(sid=int(KWP_SID.READ_MEMORY_BY_ADDRESS),
            data=addr_b+len_b,target=self._ecu,source=self._tester),timeout=2.0)
        if resp is None or resp.is_negative_response: return None
        return resp.data

    read_memory=read_memory_by_address

    def write_memory_by_address(self, address: int, data: bytes) -> bool:
        addr_b=struct.pack(">I",address)[1:]
        resp=self._request(KWPMessage(sid=int(KWP_SID.WRITE_MEMORY_BY_ADDRESS),
            data=addr_b+data,target=self._ecu,source=self._tester),timeout=5.0)
        return resp is not None and not resp.is_negative_response

    def read_dtcs(self) -> List[int]:
        resp=self._request(KWPMessage(sid=int(KWP_SID.READ_DTC_BY_STATUS),
            data=bytes([0xFF,0x00,0xFF]),target=self._ecu,source=self._tester),timeout=2.0)
        if resp is None or resp.is_negative_response or not resp.data: return []
        num=resp.data[0]; dtcs=[]
        for i in range(num):
            off=1+i*3
            if off+2>len(resp.data): break
            dtcs.append((resp.data[off]<<8)|resp.data[off+1])
        return dtcs

    def clear_dtcs(self) -> bool:
        resp=self._request(KWPMessage(sid=int(KWP_SID.CLEAR_DIAGNOSTIC_INFO),
            data=bytes([0xFF,0x00]),target=self._ecu,source=self._tester),timeout=2.0)
        return resp is not None and not resp.is_negative_response

    def _request(self, msg: KWPMessage, timeout=1.0) -> Optional[KWPMessage]:
        frame=msg.to_bytes()
        for attempt in range(self._MAX_BUSY_RETRIES+1):
            self._transport.send(frame)
            raw=self._transport.receive(timeout=timeout)
            if not raw: return None
            try: resp=KWPMessage.from_bytes(raw)
            except ValueError as e: log.error("Frame parse error: %s",e); return None
            if resp.is_negative_response and resp.nrc==int(KWP_NRC.BUSY_REPEAT_REQUEST):
                if attempt<self._MAX_BUSY_RETRIES: time.sleep(self._BUSY_RETRY_DELAY); continue
            return resp
        return None
