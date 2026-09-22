"""Lossless geometry/geography envelope. Topology validation stays on the server."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Spatial:
    domain: str
    srid: int
    layout: str
    model: str
    wkb: bytes

    def __post_init__(self):
        if self.domain not in ('geometry', 'geography') or self.layout not in ('XY', 'XYZ'):
            raise ValueError('unsupported spatial domain/layout')
        if self.model != ('planar' if self.domain == 'geometry' else 'greatCircle'):
            raise ValueError('spatial model does not match domain')
        object.__setattr__(self, 'wkb', bytes(self.wkb))

    def to_map(self):
        return {'$gdbType':'spatial', 'version':1, 'domain':self.domain, 'srid':self.srid,
                'layout':self.layout, 'model':self.model, 'wkb':self.wkb}

    @classmethod
    def from_map(cls, value):
        if value.get('$gdbType') != 'spatial' or value.get('version') != 1:
            raise ValueError('unsupported spatial envelope version')
        payload = 'wkbHex' if 'wkbHex' in value else 'wkb'
        if set(value) != {'$gdbType','version','domain','srid','layout','model',payload}:
            raise ValueError('invalid spatial envelope fields')
        wkb = bytes.fromhex(value[payload]) if payload == 'wkbHex' else value[payload]
        return cls(value['domain'],value['srid'],value['layout'],value['model'],wkb)

def hydrate_map(value):
    # Unknown versions stay maps, so future extension metadata is never lost.
    if value.get('$gdbType') == 'spatial' and value.get('version') == 1:
        return Spatial.from_map(value)
    return value
