"""Bounded PackStream v1 codec; no JSON coercion or external dependencies."""
import struct
from .types import Structure, dehydrate, hydrate
from .spatial import Spatial, hydrate_map

MAX_MESSAGE = 64 * 1024 * 1024

def encode(value, depth=0):
    if depth >= 64:
        raise ValueError('nesting exceeds 64 levels')
    value = dehydrate(value)
    if isinstance(value, Spatial): value = value.to_map()
    def child(v): return encode(v, depth + 1)
    def header(n, tiny, base):
        if tiny and n < 16: return bytes([tiny | n])
        if n < 256: return bytes([base, n])
        if n < 65536: return bytes([base + 1]) + struct.pack('>H', n)
        return bytes([base + 2]) + struct.pack('>I', n)
    if value is None: return b'\xc0'
    if isinstance(value, bool): return b'\xc3' if value else b'\xc2'
    if isinstance(value, int):
        if -16 <= value < 128: return bytes([value & 255])
        for low, high, marker, fmt in [(-128,127,0xc8,'b'),(-32768,32767,0xc9,'h'),(-2**31,2**31-1,0xca,'i'),(-2**63,2**63-1,0xcb,'q')]:
            if low <= value <= high: return bytes([marker]) + struct.pack('>' + fmt, value)
        raise OverflowError('integer outside signed 64-bit range')
    if isinstance(value, float): return b'\xc1' + struct.pack('>d', value)
    if isinstance(value, str):
        b = value.encode('utf-8'); return header(len(b), 0x80, 0xd0) + b
    if isinstance(value, (bytes, bytearray, memoryview)):
        b = bytes(value); return header(len(b), 0, 0xcc) + b
    if isinstance(value, Structure):
        if len(value.fields) > 15 or not 0 <= value.tag <= 255: raise ValueError('invalid structure')
        return bytes([0xb0 | len(value.fields), value.tag]) + b''.join(map(child, value.fields))
    if isinstance(value, (list, tuple)):
        return header(len(value), 0x90, 0xd4) + b''.join(map(child, value))
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value): raise TypeError('map keys must be strings')
        return header(len(value), 0xa0, 0xd8) + b''.join(child(k) + child(v) for k, v in value.items())
    raise TypeError('unsupported parameter type: ' + type(value).__name__)

def decode(data):
    pos = 0
    def take(n):
        nonlocal pos
        if n > len(data) - pos: raise ValueError('truncated PackStream')
        b = data[pos:pos+n]; pos += n; return b
    def read(depth=0):
        if depth >= 64: raise ValueError('nesting exceeds 64 levels')
        m = take(1)[0]
        if m <= 127: return m
        if m >= 240: return m - 256
        if m == 0xc0: return None
        if m in (0xc2, 0xc3): return m == 0xc3
        if m in (0xc1, 0xc8, 0xc9, 0xca, 0xcb):
            fmt, size = {0xc1:('d',8),0xc8:('b',1),0xc9:('h',2),0xca:('i',4),0xcb:('q',8)}[m]
            return struct.unpack('>' + fmt, take(size))[0]
        if 0x80 <= m <= 0xbf: kind, n = m & 0xf0, m & 15
        else:
            base = next((b for b in (0xcc,0xd0,0xd4,0xd8) if b <= m <= b+2), None)
            if base is None: raise ValueError('unknown PackStream marker')
            kind = {0xcc:0xcc,0xd0:0x80,0xd4:0x90,0xd8:0xa0}[base]
            n = int.from_bytes(take(1 << (m-base)), 'big')
        if kind == 0x80: return take(n).decode('utf-8')
        if kind == 0xcc: return bytes(take(n))
        if kind == 0xb0:
            tag = take(1)[0]
            return hydrate(tag, [read(depth+1) for _ in range(n)])
        if n > len(data) - pos: raise ValueError('invalid collection size')
        if kind == 0x90: return [read(depth+1) for _ in range(n)]
        result = {}
        for _ in range(n):
            key = read(depth+1)
            if not isinstance(key, str) or key in result: raise ValueError('invalid or duplicate map key')
            result[key] = read(depth+1)
        return hydrate_map(result)
    value = read()
    if pos != len(data): raise ValueError('trailing PackStream bytes')
    return value
