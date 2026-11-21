"""The mapper's shared test (docs/MAPPER.md), and its checks that need no database."""
import os, pathlib, sys, unittest
from dataclasses import dataclass
from typing import Optional
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from galactus import Driver
from galactus.mapper import Mapper, MappingError, node, relationship, stored_as, properties_of, from_node
from galactus.types import Node


@node(key='id')
@dataclass
class Person:
    id: int
    name: str
    email: Optional[str] = stored_as('email_address', default=None)
    age: Optional[int] = None


@node(key='name')
@dataclass
class Company:
    name: str


@relationship(type='WORKS_AT')
@dataclass
class WorksAt:
    since: int
    role: str


@node(label='Note')
@dataclass
class Note:
    text: str


class DeclarationTests(unittest.TestCase):
    def test_properties_use_stored_names(self):
        self.assertEqual(properties_of(Person(1, 'Ann', 'ann@example.com')),
                         {'id': 1, 'name': 'Ann', 'email_address': 'ann@example.com', 'age': None})

    def test_a_node_becomes_an_object(self):
        ann = from_node(Person, Node(7, ['Person'], {'id': 1, 'name': 'Ann', 'email_address': 'a@b', 'extra': True}, '7'))
        self.assertEqual(ann, Person(1, 'Ann', 'a@b', None))
        self.assertEqual(from_node(Person, Node(7, ['Person'], {'id': 2}, '7')), Person(2, None, None, None))
        with self.assertRaises(MappingError):
            from_node(Person, {'id': 1})

    def test_bad_declarations_are_refused(self):
        with self.assertRaises(MappingError):
            @node(label='Bad`Label')
            @dataclass
            class Bad:
                x: int
        with self.assertRaises(MappingError):
            @node
            @dataclass
            class BadField:
                x: int = stored_as('a`b', default=0)
        with self.assertRaises(MappingError):
            @node(key='missing')
            @dataclass
            class BadKey:
                x: int
        with self.assertRaises(MappingError):
            @node
            class NotADataclass:
                pass


@unittest.skipUnless(os.getenv('GDB_TEST_URI'), 'set GDB_TEST_URI for a disposable database')
class LiveMapperTests(unittest.TestCase):
    def test_the_shared_story(self):
        options = {}
        if os.getenv('GDB_TEST_CA_FILE'):
            options['trusted_certificates'] = os.environ['GDB_TEST_CA_FILE']
        with Driver(os.environ['GDB_TEST_URI'], 'gdb', os.environ['GDB_TEST_PASSWORD'], **options) as driver:
            driver.execute_query('MATCH (n) WHERE n:Person OR n:Company OR n:Note DETACH DELETE n')
            mapper = Mapper(driver)
            # 2. create, find, and the stored property name
            ann = Person(1, 'Ann', 'ann@example.com')
            self.assertEqual(mapper.create(ann), ann)
            self.assertEqual(mapper.find(Person, 1), ann)
            raw = driver.execute_query('MATCH (p:Person {id: 1}) RETURN p.email_address AS e, p.email AS none').records[0]
            self.assertEqual((raw['e'], raw['none']), ('ann@example.com', None))
            # 3. save changes, and creates
            ann.age = 41
            self.assertEqual(mapper.save(ann).age, 41)
            self.assertEqual(mapper.save(Person(2, 'Bob')), Person(2, 'Bob'))
            self.assertEqual(driver.execute_query('MATCH (p:Person) RETURN count(p) AS c').records[0]['c'], 2)
            # 4. a missing key
            self.assertIsNone(mapper.find(Person, 99))
            # 5. find all
            mapper.save(Person(3, 'Bob', age=41))
            self.assertEqual([p.id for p in mapper.find_all(Person)], [1, 2, 3])
            self.assertEqual([p.id for p in mapper.find_all(Person, {'name': 'Bob'})], [2, 3])
            self.assertEqual([p.id for p in mapper.find_all(Person, {'name': 'Bob', 'age': 41})], [3])
            self.assertEqual([p.id for p in mapper.find_all(Person, limit=2)], [1, 2])
            with self.assertRaises(MappingError):
                mapper.find_all(Person, {'height': 1})
            # 6. relate and related
            acme = mapper.save(Company('Acme'))
            self.assertEqual(mapper.relate(ann, WorksAt(2020, 'engineer'), acme), WorksAt(2020, 'engineer'))
            self.assertEqual(mapper.relate(ann, WorksAt(2021, 'lead'), acme), WorksAt(2021, 'lead'))
            self.assertEqual(mapper.related(ann, WorksAt, Company), [(WorksAt(2021, 'lead'), Company('Acme'))])
            with self.assertRaises(MappingError):
                mapper.relate(Person(77, 'Nobody'), WorksAt(1, 'x'), acme)
            # 7. a hand-written statement
            found = mapper.query(Person, 'MATCH (p:Person) WHERE p.age >= $age RETURN p ORDER BY p.id', {'age': 41})
            self.assertEqual([p.id for p in found], [1, 3])
            self.assertEqual(mapper.query(Company, 'RETURN {name: $n} AS c', {'n': 'Made up'}), [Company('Made up')])
            # 8. delete
            self.assertTrue(mapper.delete(Person, 3))
            self.assertFalse(mapper.delete(Person, 3))
            # 9. no key
            self.assertEqual(mapper.create(Note('hello')), Note('hello'))
            for refused in (lambda: mapper.save(Note('x')), lambda: mapper.find(Note, 'x'), lambda: mapper.find(Person, None)):
                with self.assertRaises(MappingError):
                    refused()
            # the operations join an open transaction
            driver.begin()
            mapper.save(Person(50, 'Temporary'))
            driver.rollback()
            self.assertIsNone(mapper.find(Person, 50))


if __name__ == '__main__':
    unittest.main()
