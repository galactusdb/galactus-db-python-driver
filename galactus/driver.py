import socket
import ssl
from urllib.parse import urlsplit
from dataclasses import dataclass
from .codec import encode, decode, MAX_MESSAGE
from .types import Structure
from .types import dehydrate

def _validate_parameters(value, depth=0):
    if depth >= 64: raise ValueError('nesting exceeds 64 levels')
    value = dehydrate(value)
    if isinstance(value, Structure):
        if value.tag not in (0x44,0x74,0x54,0x64,0x46,0x66,0x45,0x58,0x59):
            raise TypeError('graph entities and unknown structures are result-only; pass properties or an ID')
        children = value.fields
    elif isinstance(value, dict): children = value.values()
    elif isinstance(value, (list, tuple)): children = value
    else: return
    for child in children: _validate_parameters(child, depth+1)

class DatabaseError(Exception):
    def __init__(self, metadata):
        self.code = metadata.get('code', 'DatabaseError')
        self.metadata = metadata
        super().__init__(metadata.get('message', self.code))

@dataclass
class Result:
    keys: list
    records: list
    summary: dict

class Driver:
    """One serial connection. Use one driver per concurrent worker; close rolls back."""
    def __init__(self, uri, username, password, *, database='', timeout=30):
        u = urlsplit(uri)
        if u.scheme not in ('bolt', 'bolt+s') or not u.hostname or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment:
            raise ValueError('expected bolt://host:port or bolt+s://host:port')
        self.database = database
        self._socket = None
        self._transaction = False
        s = socket.create_connection((u.hostname, u.port or 7687), timeout)
        self._socket = s
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if u.scheme == 'bolt+s': self._socket = ssl.create_default_context().wrap_socket(s, server_hostname=u.hostname)
            self._socket.sendall(bytes.fromhex('6060b01700000404000000000000000000000000'))
            if self._read(4) != b'\x00\x00\x04\x04': raise ValueError('server did not select Bolt 4.4')
            self._send(1, {'user_agent':'galactus-python/0.1', 'scheme':'basic', 'principal':username, 'credentials':password})
            self._success()
        except BaseException:
            self.close(); raise

    def _read(self, n):
        data = bytearray()
        while len(data) < n:
            b = self._socket.recv(n - len(data))
            if not b: raise ConnectionError('connection closed')
            data.extend(b)
        return bytes(data)

    def _send(self, tag, *fields):
        if tag in (0x10, 0x11):
            extra = fields[2 if tag == 0x10 else 0]
            if not extra.get('db'): extra.pop('db', None)
        if self._socket is None: raise ConnectionError('driver is closed')
        body = encode(Structure(tag, fields))
        if len(body) > MAX_MESSAGE: raise ValueError('message exceeds 64 MiB')
        wire = bytearray()
        for i in range(0, len(body), 65535):
            b = body[i:i+65535]; wire.extend(len(b).to_bytes(2,'big')); wire.extend(b)
        wire.extend(b'\0\0')
        try: self._socket.sendall(wire)
        except OSError:
            self.close(); raise

    def _receive(self):
        try:
            body = bytearray()
            while True:
                n = int.from_bytes(self._read(2),'big')
                if n == 0:
                    if body: break
                    continue  # Bolt NOOP
                if len(body) + n > MAX_MESSAGE: raise ValueError('message exceeds 64 MiB')
                body.extend(self._read(n))
            msg = decode(body)
            if not isinstance(msg, Structure): raise ValueError('invalid Bolt response')
            if msg.tag == 0x7f: raise DatabaseError(msg.fields[0])
            if msg.tag not in (0x70, 0x71) or len(msg.fields) != 1: raise ValueError('unexpected Bolt response')
            return msg
        except BaseException:
            # Discard failed connections; never retry writes with an unknown outcome.
            self.close(); raise

    def _success(self):
        msg = self._receive()
        if msg.tag != 0x70: self.close(); raise ValueError('expected SUCCESS')
        return msg.fields[0]

    def execute_query(self, query, parameters=None):
        if parameters is not None and not isinstance(parameters, dict): raise TypeError('parameters must be a map')
        _validate_parameters(parameters)
        extra = {} if self._transaction else {'db':self.database}
        self._send(0x10, query, {} if parameters is None else parameters, extra)
        meta = self._success(); keys = meta.get('fields', [])
        self._send(0x3f, {'n':-1})
        records = []
        while True:
            msg = self._receive()
            if msg.tag == 0x70:
                if msg.fields[0].get('has_more'):
                    self._send(0x3f, {'n':-1}); continue
                return Result(keys, records, {**meta, **msg.fields[0]})
            values = msg.fields[0]
            if len(values) != len(keys): self.close(); raise ValueError('record width mismatch')
            records.append(dict(zip(keys, values)))

    def begin(self, *, read_only=False):
        if self._transaction: raise RuntimeError('transaction already open')
        self._send(0x11, {'db':self.database, 'mode':'r' if read_only else 'w'})
        self._success(); self._transaction = True
        return self

    def commit(self):
        if not self._transaction: raise RuntimeError('no transaction')
        self._send(0x12); result = self._success(); self._transaction = False
        return result

    def rollback(self):
        if not self._transaction: raise RuntimeError('no transaction')
        self._send(0x13); self._success(); self._transaction = False

    def close(self):
        s, self._socket = self._socket, None
        self._transaction = False
        if s is not None: s.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
