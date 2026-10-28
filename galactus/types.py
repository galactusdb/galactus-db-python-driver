"""Lossless values for types not fully expressible by Python's built-ins."""
from collections import namedtuple
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

@dataclass(frozen=True)
class Structure:
    tag: int
    fields: tuple

# Named immutable values keep the Bolt 4.4 field order; Bolt 5 graph fields follow.
_SCHEMA = {
    0x4e: ('Node', 'id labels properties element_id'),
    0x52: ('Relationship', 'id start_id end_id type properties element_id start_element_id end_element_id'),
    0x72: ('UnboundRelationship', 'id type properties element_id'),
    0x50: ('Path', 'nodes relationships sequence'),
    0x44: ('Date', 'days'),
    0x74: ('LocalTime', 'nanoseconds'),
    0x54: ('Time', 'nanoseconds offset_seconds'),
    0x64: ('LocalDateTime', 'seconds nanoseconds'),
    0x46: ('DateTime', 'seconds nanoseconds offset_seconds'),
    0x66: ('ZonedDateTime', 'seconds nanoseconds zone_id basis'),
    0x45: ('Duration', 'months days seconds nanoseconds'),
    0x58: ('Point2D', 'srid x y'),
    0x59: ('Point3D', 'srid x y z'),
}
# Bolt 4.4 field counts for structures whose Bolt 5 form is longer.
_BOLT4_FIELDS = {0x4e: 3, 0x52: 5, 0x72: 3}
LOCAL, UTC = 'local', 'utc'

TYPES = {}
for _tag, (_name, _fields) in _SCHEMA.items():
    _defaults = (None,) * sum(f.endswith('element_id') for f in _fields.split())
    _cls = namedtuple(_name, _fields, module=__name__, defaults=_defaults or None)
    _cls.tag = _tag
    TYPES[_tag] = globals()[_name] = _cls

def _graph(base, ids):
    """Element IDs default to the decimal text of the integer IDs, as on Bolt 4.4."""
    def __new__(cls, *args, **kwargs):
        value = base.__new__(cls, *args, **kwargs)
        missing = {name: str(getattr(value, source)) for name, source in ids.items() if getattr(value, name) is None}
        return value._replace(**missing) if missing else value
    return type(base.__name__, (base,), {'__slots__': (), '__new__': __new__, '__module__': __name__})

Node = _graph(Node, {'element_id': 'id'})
Relationship = _graph(Relationship, {'element_id': 'id', 'start_element_id': 'start_id', 'end_element_id': 'end_id'})
UnboundRelationship = _graph(UnboundRelationship, {'element_id': 'id'})

class ZonedDateTime(ZonedDateTime):
    """Named-zone datetime. ``basis`` says whether ``seconds`` are local ('local') or UTC ('utc')
    epoch seconds; Bolt tag ``f`` carries local seconds and ``i`` UTC seconds."""
    __slots__ = ()
    def __new__(cls, seconds, nanoseconds, zone_id, basis=LOCAL):
        if basis not in (LOCAL, UTC): raise ValueError("basis must be 'local' or 'utc'")
        return super().__new__(cls, seconds, nanoseconds, zone_id, basis)
    @classmethod
    def local(cls, seconds, nanoseconds, zone_id):
        return cls(seconds, nanoseconds, zone_id, LOCAL)
    @classmethod
    def utc(cls, seconds, nanoseconds, zone_id):
        return cls(seconds, nanoseconds, zone_id, UTC)

for _cls in (Node, Relationship, UnboundRelationship, ZonedDateTime):
    TYPES[_cls.tag] = _cls

EPOCH = datetime(1970, 1, 1)

def dehydrate(value, bolt5=False):
    """Convert a native or named value to its wire form for the agreed protocol."""
    if isinstance(value, Decimal):
        if not value.is_finite(): raise ValueError('decimal NaN and infinities are not supported')
        return format(value, 'f')
    if type(value) in TYPES.values():
        if value.tag in (0x58, 0x59):
            return Structure(value.tag, (value.srid,) + tuple(float(c) for c in value[1:]))
        if value.tag == 0x66:
            return Structure(0x69 if value.basis == UTC else 0x66, tuple(value[:3]))
        if value.tag == 0x46 and bolt5:
            return Structure(0x49, (value.seconds - value.offset_seconds,) + tuple(value[1:]))
        fields = tuple(value)
        if not bolt5 and value.tag in _BOLT4_FIELDS: fields = fields[:_BOLT4_FIELDS[value.tag]]
        return Structure(value.tag, fields)
    if isinstance(value, datetime):
        delta = value.replace(tzinfo=None) - EPOCH
        seconds = delta.days * 86400 + delta.seconds
        nanos = value.microsecond * 1000
        if value.utcoffset() is None:
            return Structure(0x64, (seconds, nanos))
        # Fixed offset preserves the instant even for ambiguous named-zone times.
        offset = int(value.utcoffset().total_seconds())
        return Structure(0x49, (seconds - offset, nanos, offset)) if bolt5 else Structure(0x46, (seconds, nanos, offset))
    if isinstance(value, date):
        return Structure(0x44, ((value - EPOCH.date()).days,))
    if isinstance(value, time):
        nanos = ((value.hour * 60 + value.minute) * 60 + value.second) * 10**9 + value.microsecond * 1000
        offset = value.utcoffset()
        return Structure(0x74, (nanos,)) if offset is None else Structure(0x54, (nanos, int(offset.total_seconds())))
    if isinstance(value, timedelta):
        return Structure(0x45, (0, value.days, value.seconds, value.microseconds * 1000))
    return value

def hydrate(tag, fields):
    if tag == 0x49:  # UTC-based offset datetime; held as local seconds like tag F
        if len(fields) != 3: raise ValueError('invalid structure field count')
        if not all(isinstance(f, int) and not isinstance(f, bool) for f in fields):
            raise ValueError('invalid datetime fields')
        tag, fields = 0x46, [fields[0] + fields[2], fields[1], fields[2]]
    elif tag in (0x66, 0x69):
        if len(fields) != 3: raise ValueError('invalid structure field count')
        return ZonedDateTime(*fields, UTC if tag == 0x69 else LOCAL)
    cls = TYPES.get(tag)
    if cls is None:
        return Structure(tag, tuple(fields))
    if len(fields) != len(cls._fields) and len(fields) != _BOLT4_FIELDS.get(tag):
        raise ValueError('invalid structure field count')
    value = cls(*fields)
    # Use native temporals only when they preserve the complete value.
    try:
        if tag == 0x44:
            return EPOCH.date() + timedelta(days=fields[0])
        if tag in (0x64, 0x46) and fields[1] % 1000 == 0:
            dt = EPOCH + timedelta(seconds=fields[0], microseconds=fields[1] // 1000)
            return dt if tag == 0x64 else dt.replace(tzinfo=timezone(timedelta(seconds=fields[2])))
        if tag in (0x74, 0x54) and fields[0] % 1000 == 0:
            n = fields[0]
            if not 0 <= n < 86400 * 10**9:
                raise ValueError('invalid time')
            seconds, micro = divmod(n // 1000, 10**6)
            return time(seconds // 3600, seconds // 60 % 60, seconds % 60, micro,
                        tzinfo=None if tag == 0x74 else timezone(timedelta(seconds=fields[1])))
    except (OverflowError, ValueError, TypeError):
        pass
    return value

__all__ = ['Structure', 'LOCAL', 'UTC'] + [name for name, _ in _SCHEMA.values()]
