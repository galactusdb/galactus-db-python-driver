import platform
import socket
import ssl
import sys
from urllib.parse import urlsplit
from dataclasses import dataclass
from .codec import encode, decode, MAX_MESSAGE
from .types import Structure
from .types import dehydrate

VERSION = '0.2.0'
USER_AGENT = 'galactus-db-python-driver/' + VERSION
# Preamble, then 5.4 accepting down to 5.0, then 4.4, then two empty proposals.
_HANDSHAKE = bytes.fromhex('6060b017' '00040405' '00000404' '00000000' '00000000')
_SUCCESS, _RECORD, _IGNORED, _FAILURE = 0x70, 0x71, 0x7e, 0x7f
_HELLO, _LOGON, _RESET, _RUN, _BEGIN, _COMMIT, _ROLLBACK, _PULL = 0x01, 0x6a, 0x0f, 0x10, 0x11, 0x12, 0x13, 0x3f

def _validate_parameters(value, depth=0):
    if depth >= 64: raise ValueError('nesting exceeds 64 levels')
    value = dehydrate(value)
    if isinstance(value, Structure):
        if value.tag not in (0x44,0x74,0x54,0x64,0x46,0x49,0x66,0x69,0x45,0x58,0x59):
            raise TypeError('graph entities and unknown structures are result-only; pass properties or an ID')
        children = value.fields
    elif isinstance(value, dict): children = value.values()
    elif isinstance(value, (list, tuple)): children = value
    else: return
    for child in children: _validate_parameters(child, depth+1)

def _bolt_agent():
    return {'product': USER_AGENT,
            'language': 'Python/' + platform.python_version(),
            'language_details': platform.python_implementation() + ' ' + sys.version.split()[0],
            'platform': ' '.join(p for p in (platform.system(), platform.release(), platform.machine()) if p)}

class DatabaseError(Exception):
    """A FAILURE from the server. ``code`` and ``message`` are kept unchanged."""
    def __init__(self, metadata):
        self.code = metadata.get('code', 'DatabaseError')
        self.metadata = metadata
        parts = self.code.split('.') if isinstance(self.code, str) else []
        if len(parts) == 4 and all(parts):
            self.classification, self.category, self.title = parts[1:]
        else:
            self.classification = self.category = self.title = None
        super().__init__(metadata.get('message', self.code))

    @property
    def message(self): return self.metadata.get('message', self.code)
    @property
    def is_client_error(self): return self.classification == 'ClientError'
    @property
    def is_transient(self): return self.classification == 'TransientError'
    @property
    def is_database_error(self): return self.classification == 'DatabaseError'
    @property
    def is_retryable(self):
        """True for TransientError codes. The driver itself never retries."""
        return self.is_transient

@dataclass
class Result:
    keys: list
    records: list
    summary: dict

class Driver:
    """One serial connection. Use one driver per concurrent worker; close rolls back."""
    def __init__(self, uri, username, password, *, database='', timeout=30, trusted_certificates=None):
        u = urlsplit(uri)
        if u.scheme not in ('bolt', 'bolt+s') or not u.hostname or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment:
            raise ValueError('expected bolt://host:port or bolt+s://host:port')
        if trusted_certificates is not None and u.scheme != 'bolt+s':
            raise ValueError('trusted_certificates requires a bolt+s:// URI')
        self.database = database
        self._socket = None
        self._transaction = False
        self._bolt5 = False
        self.protocol_version = None
        self.server_agent = None
        self.connection_id = None
        self.last_bookmark = None
        context = ssl.create_default_context(cafile=trusted_certificates) if u.scheme == 'bolt+s' else None
        s = socket.create_connection((u.hostname, u.port or 7687), timeout)
        self._socket = s
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if context: self._socket = context.wrap_socket(s, server_hostname=u.hostname)
            self._socket.sendall(_HANDSHAKE)
            agreed = self._read(4)
            if agreed[:2] != b'\0\0' or not (agreed[3] == 5 and agreed[2] <= 4 or agreed[2:] == b'\x04\x04'):
                raise ValueError('server did not agree Bolt 5.0-5.4 or 4.4')
            major, minor = agreed[3], agreed[2]
            self.protocol_version = f'{major}.{minor}'
            self._bolt5 = major == 5
            auth = {'scheme':'basic', 'principal':username, 'credentials':password}
            if (major, minor) >= (5, 1):
                hello = self._exchange(_HELLO, {'user_agent':USER_AGENT, 'bolt_agent':_bolt_agent()}, auth=True)
                self._exchange(_LOGON, auth, auth=True)
            else:
                hello = self._exchange(_HELLO, {'user_agent':USER_AGENT, **auth}, auth=True)
            self.server_agent = hello.get('server')
            self.connection_id = hello.get('connection_id')
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
        if tag in (_RUN, _BEGIN):
            extra = fields[2 if tag == _RUN else 0]
            if not extra.get('db'): extra.pop('db', None)
        if self._socket is None: raise ConnectionError('driver is closed')
        body = encode(Structure(tag, fields), bolt5=self._bolt5)
        if len(body) > MAX_MESSAGE: raise ValueError('message exceeds 64 MiB')
        wire = bytearray()
        for i in range(0, len(body), 65535):
            b = body[i:i+65535]; wire.extend(len(b).to_bytes(2,'big')); wire.extend(b)
        wire.extend(b'\0\0')
        try: self._socket.sendall(wire)
        except OSError:
            self.close(); raise

    def _receive(self):
        """Read one response message; any transport or protocol failure discards the connection."""
        if self._socket is None: raise ConnectionError('driver is closed')
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
            if not isinstance(msg, Structure) or msg.tag not in (_SUCCESS, _RECORD, _IGNORED, _FAILURE):
                raise ValueError('invalid Bolt response')
            if msg.tag != _IGNORED and (len(msg.fields) != 1 or not isinstance(msg.fields[0], (dict, list))):
                raise ValueError('unexpected Bolt response')
            return msg
        except BaseException:
            # Discard failed connections; never retry writes with an unknown outcome.
            self.close(); raise

    def _response(self, *, auth=False, record=False):
        """Read the answer to one request. A database FAILURE resets the connection and is raised."""
        msg = self._receive()
        if msg.tag == _FAILURE:
            error = DatabaseError(msg.fields[0])
            if auth:
                self.close()  # authentication failure is terminal
            else:
                self._reset()
            raise error
        if msg.tag == _SUCCESS and isinstance(msg.fields[0], dict) or record and msg.tag == _RECORD and isinstance(msg.fields[0], list):
            return msg
        self.close(); raise ValueError('unexpected Bolt response')

    def _exchange(self, tag, *fields, auth=False):
        self._send(tag, *fields)
        return self._response(auth=auth).fields[0]

    def _reset(self):
        # The server rolls back any open transaction on RESET.
        self._transaction = False
        self._send(_RESET)
        while True:
            msg = self._receive()
            if msg.tag == _IGNORED: continue
            if msg.tag == _SUCCESS: return
            self.close(); raise ConnectionError('RESET did not succeed; connection discarded')

    def _bookmark(self, meta):
        if isinstance(meta.get('bookmark'), str): self.last_bookmark = meta['bookmark']

    def execute_query(self, query, parameters=None):
        if parameters is not None and not isinstance(parameters, dict): raise TypeError('parameters must be a map')
        _validate_parameters(parameters)
        autocommit = not self._transaction
        extra = {'db':self.database} if autocommit else {}
        meta = self._exchange(_RUN, query, {} if parameters is None else parameters, extra)
        keys = meta.get('fields', [])
        self._send(_PULL, {'n':-1})
        records = []
        while True:
            msg = self._response(record=True)
            if msg.tag == _SUCCESS:
                if msg.fields[0].get('has_more'):
                    self._send(_PULL, {'n':-1}); continue
                if autocommit: self._bookmark(msg.fields[0])
                return Result(keys, records, {**meta, **msg.fields[0]})
            values = msg.fields[0]
            if len(values) != len(keys): self.close(); raise ValueError('record width mismatch')
            records.append(dict(zip(keys, values)))

    def begin(self, *, read_only=False):
        if self._transaction: raise RuntimeError('transaction already open')
        self._exchange(_BEGIN, {'db':self.database, 'mode':'r' if read_only else 'w'})
        self._transaction = True
        return self

    def commit(self):
        if not self._transaction: raise RuntimeError('no transaction')
        result = self._exchange(_COMMIT); self._transaction = False
        self._bookmark(result)
        return result

    def rollback(self):
        if not self._transaction: raise RuntimeError('no transaction')
        self._exchange(_ROLLBACK); self._transaction = False

    @property
    def in_transaction(self):
        return self._transaction

    def close(self):
        s, self._socket = self._socket, None
        self._transaction = False
        if s is not None: s.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()
