"""Object mapping: nodes and relationships as dataclasses, and the Cypher for everyday operations.

    from dataclasses import dataclass
    from galactus import Driver
    from galactus.mapper import Mapper, node, relationship, stored_as

    @node(key='id')
    @dataclass
    class Person:
        id: int
        name: str
        email: str = stored_as('email_address', default=None)

    with Driver('bolt://localhost:7687', 'gdb', password) as driver:
        people = Mapper(driver)
        people.save(Person(1, 'Ann', 'ann@example.com'))
        ann = people.find(Person, 1)

Standard library only. See docs/MAPPER.md for the contract every Galactus mapper follows.
"""
import dataclasses
from .types import Node, Relationship, UnboundRelationship

__all__ = ['Mapper', 'MappingError', 'node', 'relationship', 'stored_as', 'properties_of', 'from_node',
           'from_relationship']


class MappingError(Exception):
    """A type that cannot be mapped, or a value that does not fit it."""


def _name(value, what):
    if not isinstance(value, str) or not value or '`' in value:
        raise MappingError(f'{what} must be a name without backticks, got {value!r}')
    return value


def _quote(name):
    return '`' + name + '`'


def stored_as(property_name, **field_options):
    """A dataclass field stored under another property name."""
    metadata = dict(field_options.pop('metadata', {}), property=property_name)
    return dataclasses.field(metadata=metadata, **field_options)


class _Shape:
    """What the mapper knows of a declared type."""
    def __init__(self, cls, name, key):
        if not dataclasses.is_dataclass(cls):
            raise MappingError(f'{cls.__name__} must be a dataclass')
        self.cls, self.name = cls, _name(name, 'a label or relationship type')
        self.fields = {f.name: _name(f.metadata.get('property', f.name), f'{cls.__name__}.{f.name}')
                       for f in dataclasses.fields(cls)}
        if key is not None and key not in self.fields:
            raise MappingError(f'{cls.__name__} has no field {key!r} to be its key')
        self.key = key

    @property
    def key_property(self):
        return self.fields[self.key]


def node(cls=None, *, label=None, key=None):
    """Declare a dataclass as a node type. ``label`` defaults to the class name."""
    def declare(cls):
        cls.__galactus_node__ = _Shape(cls, label or cls.__name__, key)
        return cls
    return declare if cls is None else declare(cls)


def relationship(cls=None, *, type=None):
    """Declare a dataclass as a relationship type. ``type`` defaults to the class name in upper case."""
    def declare(cls):
        cls.__galactus_relationship__ = _Shape(cls, type or cls.__name__.upper(), None)
        return cls
    return declare if cls is None else declare(cls)


def _shape(cls, kind='node'):
    shape = getattr(cls, f'__galactus_{kind}__', None)
    if shape is None or shape.cls is not cls:
        raise MappingError(f'{getattr(cls, "__name__", cls)!r} is not declared as a {kind} type')
    return shape


def _any_shape(cls):
    for kind in ('node', 'relationship'):
        shape = getattr(cls, f'__galactus_{kind}__', None)
        if shape is not None and shape.cls is cls:
            return shape
    raise MappingError(f'{getattr(cls, "__name__", cls)!r} is not declared as a node or relationship type')


def properties_of(obj):
    """Every declared property of an object, by its stored name."""
    shape = _any_shape(type(obj))
    return {stored: getattr(obj, field) for field, stored in shape.fields.items()}


def _build(shape, properties):
    values = {}
    for f in dataclasses.fields(shape.cls):
        stored = shape.fields[f.name]
        if stored in properties:
            values[f.name] = properties[stored]
        elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            values[f.name] = None
    try:
        return shape.cls(**values)
    except Exception as error:
        raise MappingError(f'{shape.cls.__name__}: {error}') from error


def from_node(cls, value):
    """An object of a declared node type from a ``Node``."""
    if not isinstance(value, Node):
        raise MappingError(f'{cls.__name__}: expected a node, got {type(value).__name__}')
    return _build(_shape(cls), value.properties)


def from_relationship(cls, value):
    """An object of a declared relationship type from a ``Relationship``."""
    if not isinstance(value, (Relationship, UnboundRelationship)):
        raise MappingError(f'{cls.__name__}: expected a relationship, got {type(value).__name__}')
    return _build(_shape(cls, 'relationship'), value.properties)


def _from_value(cls, value):
    if isinstance(value, Node):
        return from_node(cls, value)
    if isinstance(value, (Relationship, UnboundRelationship)):
        return from_relationship(cls, value)
    if isinstance(value, dict):
        return _build(_any_shape(cls), value)
    raise MappingError(f'{cls.__name__}: expected a node, a relationship or a map, got {type(value).__name__}')


class Mapper:
    """Runs the everyday operations on a driver, each as one statement."""
    def __init__(self, driver):
        self.driver = driver

    def _run(self, query, parameters):
        return self.driver.execute_query(query, parameters).records

    @staticmethod
    def _keyed(cls):
        shape = _shape(cls)
        if shape.key is None:
            raise MappingError(f'{cls.__name__} has no key')
        return shape

    @staticmethod
    def _key_value(shape, value):
        if value is None:
            raise MappingError(f'{shape.cls.__name__}: the key {shape.key!r} has no value')
        return value

    def create(self, obj):
        shape = _shape(type(obj))
        rows = self._run(f'CREATE (n:{_quote(shape.name)}) SET n = $properties RETURN n',
                         {'properties': properties_of(obj)})
        return from_node(shape.cls, rows[0]['n'])

    def save(self, obj):
        shape = self._keyed(type(obj))
        key = self._key_value(shape, getattr(obj, shape.key))
        rows = self._run(f'MERGE (n:{_quote(shape.name)} {{{_quote(shape.key_property)}: $key}}) '
                         'SET n += $properties RETURN n', {'key': key, 'properties': properties_of(obj)})
        return from_node(shape.cls, rows[0]['n'])

    def find(self, cls, key):
        shape = self._keyed(cls)
        rows = self._run(f'MATCH (n:{_quote(shape.name)} {{{_quote(shape.key_property)}: $key}}) RETURN n LIMIT 1',
                         {'key': self._key_value(shape, key)})
        return from_node(cls, rows[0]['n']) if rows else None

    def find_all(self, cls, filter=None, limit=None):
        shape = _shape(cls)
        parameters, conditions = {}, []
        for index, (name, value) in enumerate((filter or {}).items()):
            if name not in shape.fields:
                raise MappingError(f'{cls.__name__} has no field {name!r} to filter by')
            parameters[f'p{index}'] = value
            conditions.append(f'n.{_quote(shape.fields[name])} = $p{index}')
        query = f'MATCH (n:{_quote(shape.name)})'
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        query += ' RETURN n'
        if shape.key is not None:
            query += f' ORDER BY n.{_quote(shape.key_property)}'
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                raise MappingError('limit must be a whole number, zero or more')
            parameters['limit'] = limit
            query += ' LIMIT $limit'
        return [from_node(cls, row['n']) for row in self._run(query, parameters)]

    def delete(self, cls, key):
        shape = self._keyed(cls)
        rows = self._run(f'MATCH (n:{_quote(shape.name)} {{{_quote(shape.key_property)}: $key}}) '
                         'DETACH DELETE n RETURN count(*) AS deleted', {'key': self._key_value(shape, key)})
        return rows[0]['deleted'] > 0

    def relate(self, start, link, end):
        a, b, r = self._keyed(type(start)), self._keyed(type(end)), _shape(type(link), 'relationship')
        rows = self._run(
            f'MATCH (a:{_quote(a.name)} {{{_quote(a.key_property)}: $a}}), '
            f'(b:{_quote(b.name)} {{{_quote(b.key_property)}: $b}}) '
            f'MERGE (a)-[r:{_quote(r.name)}]->(b) SET r += $properties RETURN r',
            {'a': self._key_value(a, getattr(start, a.key)), 'b': self._key_value(b, getattr(end, b.key)),
             'properties': properties_of(link)})
        if not rows:
            raise MappingError(f'{a.cls.__name__} or {b.cls.__name__} was not found to relate')
        return from_relationship(r.cls, rows[0]['r'])

    def related(self, start, link_cls, end_cls):
        a, b, r = self._keyed(type(start)), _shape(end_cls), _shape(link_cls, 'relationship')
        query = (f'MATCH (a:{_quote(a.name)} {{{_quote(a.key_property)}: $a}})'
                 f'-[r:{_quote(r.name)}]->(b:{_quote(b.name)}) RETURN r, b')
        if b.key is not None:
            query += f' ORDER BY b.{_quote(b.key_property)}'
        rows = self._run(query, {'a': self._key_value(a, getattr(start, a.key))})
        return [(from_relationship(link_cls, row['r']), from_node(end_cls, row['b'])) for row in rows]

    def query(self, cls, cypher, parameters=None):
        result = self.driver.execute_query(cypher, parameters)
        if not result.keys:
            return []
        return [_from_value(cls, record[result.keys[0]]) for record in result.records]
