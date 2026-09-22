import os,sys,unittest
from pathlib import Path
from datetime import date,datetime,time,timedelta,timezone
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from galactus import *
from galactus.codec import encode,decode

class CodecTests(unittest.TestCase):
 def test_golden(self):
  for line in (root/'tests/fixtures/values.tsv').read_text().splitlines():
   name,h=line.split('\t');b=bytes.fromhex(h)
   with self.subTest(name=name): self.assertEqual(encode(decode(b)),b)
 def test_malformed(self):
  for h in (root/'tests/fixtures/malformed.tsv').read_text().splitlines():
   with self.subTest(h=h), self.assertRaises((ValueError,TypeError,OverflowError)):decode(bytes.fromhex(h))
 def test_native(self):
  for v in [date(1960,1,1),datetime(1960,1,1,1,2,3,456789,tzinfo=timezone(timedelta(hours=5,minutes=30))),time(1,2,3,456789),2**63-1,-2**63,b'\0\xff',{'x':[None,False,'ä¸–ç•Œ']}]:
   self.assertEqual(decode(encode(v)),v)
  for v in [2**63,-2**63-1,{1:'bad'},object()]:
   with self.assertRaises((TypeError,OverflowError)):encode(v)

@unittest.skipUnless(os.getenv('GDB_TEST_URI'),'set GDB_TEST_URI for a disposable database')
class LiveTests(unittest.TestCase):
 def driver(self,password=None):return Driver(os.environ['GDB_TEST_URI'],'gdb',password or os.environ['GDB_TEST_PASSWORD'])
 def test_live(self):
  with self.driver() as d:
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
   with self.assertRaises(DatabaseError):d.execute_query('INVALID QUERY')
   with self.assertRaises(ConnectionError):d.execute_query('RETURN 1')
 def test_auth_failure(self):
  with self.assertRaises(DatabaseError):self.driver('wrong-password')

if __name__=='__main__':unittest.main()
