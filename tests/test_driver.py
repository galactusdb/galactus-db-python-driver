import os,ssl,sys,unittest
from pathlib import Path
from datetime import date,datetime,time,timedelta,timezone
from decimal import Decimal
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from galactus import *
from galactus.codec import encode,decode

def rows(name):return [line.split('\t') for line in (root/'tests/fixtures'/name).read_text().splitlines() if line]

class CodecTests(unittest.TestCase):
 def test_golden(self):
  for name,h in rows('values.tsv'):
   b=bytes.fromhex(h)
   with self.subTest(name=name): self.assertEqual(encode(decode(b)),b)
 def test_golden_bolt5(self):
  for name,h in rows('bolt5.tsv'):
   b=bytes.fromhex(h)
   with self.subTest(name=name): self.assertEqual(encode(decode(b),bolt5=True),b)
 def test_datetime_pairs(self):
  for bolt4,bolt5 in rows('datetime_pairs.tsv'):
   with self.subTest(bolt4=bolt4):
    v=decode(bytes.fromhex(bolt4));self.assertEqual(v,decode(bytes.fromhex(bolt5)))
    self.assertEqual(encode(v).hex(),bolt4);self.assertEqual(encode(v,bolt5=True).hex(),bolt5)
 def test_graph_element_ids(self):
  node=decode(bytes.fromhex(dict(rows('values.tsv'))['node']))
  rel=decode(bytes.fromhex(dict(rows('values.tsv'))['relationship']))
  self.assertEqual((node.id,node.element_id),(1,'1'))
  self.assertEqual((rel.element_id,rel.start_element_id,rel.end_element_id),('2','1','3'))
  self.assertEqual(decode(bytes.fromhex(dict(rows('bolt5.tsv'))['unbound_relationship'])).element_id,'2')
 def test_zoned_basis(self):
  local,utc=ZonedDateTime.local(3600,0,'Europe/London'),ZonedDateTime.utc(3600,0,'Europe/London')
  self.assertNotEqual(local,utc);self.assertEqual(ZonedDateTime(3600,0,'Europe/London'),local)
  for v in (local,utc):
   for bolt5 in (False,True):self.assertEqual(decode(encode(v,bolt5=bolt5)),v)
  self.assertEqual(encode(utc)[1],0x69);self.assertEqual(encode(local,bolt5=True)[1],0x66)
 def test_decimal(self):
  self.assertEqual(decode(encode(Decimal('12.30'))),'12.30')
  self.assertEqual(decode(encode(Decimal('1E+3'))),'1000')
  self.assertEqual(decode(encode(Decimal('-1.5E-7'))),'-0.00000015')
  for bad in ('NaN','sNaN','Infinity','-Infinity'):
   with self.assertRaises(ValueError):encode(Decimal(bad))
 def test_malformed(self):
  for h in (root/'tests/fixtures/malformed.tsv').read_text().splitlines():
   with self.subTest(h=h), self.assertRaises((ValueError,TypeError,OverflowError)):decode(bytes.fromhex(h))
 def test_native(self):
  for v in [date(1960,1,1),datetime(1960,1,1,1,2,3,456789,tzinfo=timezone(timedelta(hours=5,minutes=30))),time(1,2,3,456789),2**63-1,-2**63,b'\0\xff',{'x':[None,False,'世界']}]:
   for bolt5 in (False,True):self.assertEqual(decode(encode(v,bolt5=bolt5)),v)
  for v in [2**63,-2**63-1,{1:'bad'},object()]:
   with self.assertRaises((TypeError,OverflowError)):encode(v)
 def test_error_classification(self):
  e=DatabaseError({'code':codes.CONSTRAINT_VALIDATION_FAILED,'message':'m'})
  self.assertEqual((e.code,e.message,e.classification,e.category,e.title),(codes.CONSTRAINT_VALIDATION_FAILED,'m','ClientError','Schema','ConstraintValidationFailed'))
  self.assertTrue(e.is_client_error);self.assertFalse(e.is_retryable or e.is_transient or e.is_database_error)
  t=DatabaseError({'code':codes.SNAPSHOT_TOO_OLD});self.assertTrue(t.is_transient and t.is_retryable)
  odd=DatabaseError({'code':'Odd'});self.assertIsNone(odd.classification);self.assertFalse(odd.is_retryable)
 def test_configuration(self):
  for uri in ['neo4j://h:7687','bolt+ssc://h:7687','bolt://u:p@h:7687','bolt://h:7687?x=1']:
   with self.subTest(uri=uri),self.assertRaises(ValueError):Driver(uri,'gdb','x')
  with self.assertRaises(ValueError):Driver('bolt://127.0.0.1:1','gdb','x',trusted_certificates='ca.pem')

@unittest.skipUnless(os.getenv('GDB_TEST_URI'),'set GDB_TEST_URI for a disposable database')
class LiveTests(unittest.TestCase):
 def driver(self,password=None,**options):
  if 'trusted_certificates' not in options and os.getenv('GDB_TEST_CA_FILE'):options['trusted_certificates']=os.environ['GDB_TEST_CA_FILE']
  return Driver(os.environ['GDB_TEST_URI'],'gdb',password or os.environ['GDB_TEST_PASSWORD'],**options)
 def test_live(self):
  with self.driver() as d:
   if os.getenv('GDB_TEST_EXPECT_BOLT'):self.assertEqual(d.protocol_version,os.environ['GDB_TEST_EXPECT_BOLT'])
   self.assertTrue(d.server_agent);self.assertTrue(d.connection_id)
   values={'n':2**63-1,'b':b'\0\xff','t':datetime(1960,1,1,1,2,3,456789,tzinfo=timezone(timedelta(hours=5,minutes=30))),'s':'x'*70000}
   self.assertEqual(d.execute_query('RETURN $v AS v',{'v':values}).records[0]['v'],values)
   for line in (root/'tests/fixtures/spatial.tsv').read_text().splitlines():
    domain,wkt=line.split('\t')
    with self.subTest(domain=domain,wkt=wkt):
     s=d.execute_query('RETURN spatial.fromWKT($wkt,{domain:$domain}) AS shape',{'wkt':wkt,'domain':domain}).records[0]['shape']
     self.assertIsInstance(s,Spatial)
     r=d.execute_query('RETURN spatial.fromMap($s) AS shape, $nested AS nested',{'s':s,'nested':[{'shape':s}]}).records[0]
     self.assertEqual(r['shape'],s);self.assertEqual(r['nested'][0]['shape'],s)
   d.begin();d.execute_query('CREATE (:DriverPython {n:1})');d.rollback()
   self.assertEqual(d.execute_query('MATCH (n:DriverPython) RETURN count(n) AS n').records[0]['n'],0)
   d.begin();d.execute_query('CREATE (:DriverPython {n:2})');d.commit()
   self.assertEqual(d.execute_query('MATCH (n:DriverPython) RETURN n').records[0]['n'].properties['n'],2)
   # Database errors are classified, and the same driver recovers after RESET.
   with self.assertRaises(DatabaseError) as failure:d.execute_query('INVALID QUERY')
   e=failure.exception
   self.assertTrue(e.code and e.classification and e.category and e.title);self.assertTrue(e.is_client_error);self.assertFalse(e.is_retryable)
   self.assertEqual(d.execute_query('RETURN 1 AS one').records[0]['one'],1)
   # A failure inside an explicit transaction closes it; autocommit work continues.
   d.begin();d.execute_query('CREATE (:DriverPython {n:3})')
   with self.assertRaises(DatabaseError):d.execute_query('INVALID QUERY')
   self.assertFalse(d.in_transaction)
   with self.assertRaises(RuntimeError):d.commit()
   self.assertEqual(d.execute_query('MATCH (n:DriverPython {n:3}) RETURN count(n) AS n').records[0]['n'],0)
   self.assertEqual(d.execute_query('RETURN 1 AS one').records[0]['one'],1)

 def test_graph_element_ids(self):
  with self.driver() as d:
   r=d.execute_query('CREATE (a:DriverPythonGraph)-[r:DRIVER_PYTHON_LINK]->(b:DriverPythonGraph) RETURN a,r,b,id(a) AS ai,id(r) AS ri,id(b) AS bi').records[0]
   a,rel,b=r['a'],r['r'],r['b']
   self.assertEqual((a.id,a.element_id),(r['ai'],str(r['ai'])));self.assertEqual(b.element_id,str(r['bi']))
   self.assertEqual((rel.id,rel.element_id,rel.start_element_id,rel.end_element_id),(r['ri'],str(r['ri']),str(r['ai']),str(r['bi'])))
   self.assertEqual(d.execute_query('MATCH (n) WHERE id(n)=$id RETURN elementId(n) AS e',{'id':r['ai']}).records[0]['e'],a.element_id)

 def test_temporal_and_decimal(self):
  with self.driver() as d:
   bolt5=d.protocol_version.startswith('5.')
   offset=datetime(2026,7,1,13,0,0,123456,tzinfo=timezone(timedelta(hours=1)))
   wrapped=DateTime(1782910800,123456789,3600)
   for v in (offset,wrapped):
    self.assertEqual(d.execute_query('RETURN $v AS v',{'v':v}).records[0]['v'],v)
   utc=1782907200  # 2026-07-01T12:00:00Z; Europe/London is UTC+1 (BST) then.
   zoned_utc,zoned_local=ZonedDateTime.utc(utc,5,'Europe/London'),ZonedDateTime.local(utc+3600,5,'Europe/London')
   # The server answers with its protocol's basis: UTC (tag i) on 5.x, local (tag f) on 4.4.
   expected=zoned_utc if bolt5 else zoned_local
   for v in (zoned_utc,zoned_local):
    with self.subTest(sent=v):self.assertEqual(d.execute_query('RETURN $v AS v',{'v':v}).records[0]['v'],expected)
   self.assertEqual(d.execute_query('RETURN $v.year AS y, $v.hour AS h',{'v':zoned_utc}).records[0],{'y':2026,'h':13})
   for v in (Decimal('12.30'),'12.30'):
    self.assertEqual(d.execute_query('RETURN decimal($d) AS d',{'d':v}).records[0]['d'],'12.30')

 def test_constraint_violation(self):
  with self.driver() as d:
   d.execute_query('CREATE CONSTRAINT FOR (n:DriverPythonUnique) REQUIRE n.key IS UNIQUE')
   d.execute_query('CREATE (:DriverPythonUnique {key:$k})',{'k':'same'})
   with self.assertRaises(DatabaseError) as failure:d.execute_query('CREATE (:DriverPythonUnique {key:$k})',{'k':'same'})
   self.assertEqual(failure.exception.code,codes.CONSTRAINT_VALIDATION_FAILED);self.assertEqual(failure.exception.title,'ConstraintValidationFailed')
   self.assertEqual(d.execute_query('MATCH (n:DriverPythonUnique {key:$k}) RETURN count(n) AS n',{'k':'same'}).records[0]['n'],1)

 def test_bookmark(self):
  with self.driver() as d:
   d.execute_query('CREATE (:DriverPythonBookmark)')
   first=d.last_bookmark
   if first is not None:
    self.assertIsInstance(first,str)
    d.begin();d.execute_query('CREATE (:DriverPythonBookmark)');d.commit()
    self.assertIsInstance(d.last_bookmark,str)

 @unittest.skipUnless(os.getenv('GDB_TEST_CA_FILE'),'tls pass only')
 def test_tls_trust(self):
  with self.assertRaises(ssl.SSLError):self.driver(trusted_certificates=None)
  plain=os.environ['GDB_TEST_URI'].replace('bolt+s://','bolt://',1)
  with self.assertRaises(ValueError):Driver(plain,'gdb',os.environ['GDB_TEST_PASSWORD'],trusted_certificates=os.environ['GDB_TEST_CA_FILE'])

 def test_auth_failure(self):
  with self.assertRaises(DatabaseError) as failure:self.driver('wrong-password')
  self.assertTrue(failure.exception.code)

if __name__=='__main__':unittest.main()
