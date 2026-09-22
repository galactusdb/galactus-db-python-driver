"""Lossless values for types not fully expressible by Python's built-ins."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

@dataclass(frozen=True)
class Structure:
    tag: int
    fields: tuple

# Named immutable values have the same field order as Bolt 4.4.
from collections import namedtuple
_SCHEMA = {
    0x4e: ('Node', 'id labels properties'),
    0x52: ('Relationship', 'id start_id end_id type properties'),
    0x72: ('UnboundRelationship', 'id type properties'),
    0x50: ('Path', 'nodes relationships sequence'),
    0x44: ('Date', 'days'),
    0x74: ('LocalTime', 'nanoseconds'),
    0x54: ('Time', 'nanoseconds offset_seconds'),
    0x64: ('LocalDateTime', 'seconds nanoseconds'),
    0x46: ('DateTime', 'seconds nanoseconds offset_seconds'),
    0x66: ('ZonedDateTime', 'seconds nanoseconds zone_id'),
    0x45: ('Duration', 'months days seconds nanoseconds'),
    0x58: ('Point2D', 'srid x y'),
    0x59: ('Point3D', 'srid x y z'),
}
TYPES = {}
for _tag, (_name, _fields) in _SCHEMA.items():
    _cls = namedtuple(_name, _fields, module=__name__)
    _cls.tag = _tag
    TYPES[_tag] = globals()[_name] = _cls

EPOCH = datetime(1970, 1, 1)

def dehydrate(value):
    if type(value) in TYPES.values():
        if value.tag in (0x58, 0x59):
            return Structure(value.tag, (value.srid,) + tuple(float(c) for c in value[1:]))
        return Structure(value.tag, tuple(value))
    if isinstance(value, datetime):
        delta = value.replace(tzinfo=None) - EPOCH
        seconds = delta.days * 86400 + delta.seconds
        nanos = value.microsecond * 1000
        if value.utcoffset() is None:
            return Structure(0x64, (seconds, nanos))
        # Fixed offset preserves the instant even for ambiguous named-zone times.
        return Structure(0x46, (seconds, nanos, int(value.utcoffset().total_seconds())))
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
    cls = TYPES.get(tag)
    if cls is None:
        return Structure(tag, tuple(fields))
    if len(fields) != len(cls._fields):
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
    except (OverflowError, ValueError):
        pass
    return value

__all__ = ['Structure'] + [name for name, _ in _SCHEMA.values()]
