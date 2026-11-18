import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import zipfile
import backend as b

class Response(io.BytesIO):
    def __init__(self, content):
        super().__init__(content); self.headers={'Content-Length':str(len(content))}

class Tests(unittest.TestCase):
    def setUp(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('META-INF/MANIFEST.MF','Manifest-Version: 1.0')
        self.data=out.getvalue()
        self.spec=dict(kind='Fabric',version='1.21.1',java=21,url='https://example.org/server.jar',algorithm='sha256',checksum=hashlib.sha256(self.data).hexdigest())
        self.tmp=tempfile.TemporaryDirectory();self.parent=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def create(self,**kw):
        options=dict(catalog=b.Catalog(),spec=self.spec,parent=self.parent,name='Test World',ram=4,java='java',accepted=True,progress=lambda *a:None,cancel=threading.Event());options.update(kw)
        with patch('backend.java_major',return_value=21),patch('backend.urllib.request.urlopen',return_value=Response(self.data)):
            return b.create_server(**options)
    def test_create_and_launch_script(self):
        p=Path(self.create());self.assertTrue((p/'mods').is_dir());self.assertEqual((p/'eula.txt').read_text(),'eula=true\n')
        compile((p/'launch.py').read_text(),'launch.py','exec')
        self.assertFalse(any(self.parent.glob('.easyservers-*')))
    def test_integrity_failure_cleanup(self):
        self.spec['checksum']='bad'
        with self.assertRaisesRegex(ValueError,'checksum'):self.create()
        self.assertEqual(list(self.parent.iterdir()),[])
    def test_cancellation_cleanup(self):
        c=threading.Event();c.set()
        with self.assertRaises(b.Cancelled):self.create(cancel=c)
        self.assertEqual(list(self.parent.iterdir()),[])
    def test_existing_world_preserved(self):
        p=self.parent/'Test World';p.mkdir();(p/'world.dat').write_text('keep')
        with self.assertRaisesRegex(ValueError,'already exists'):self.create()
        self.assertEqual((p/'world.dat').read_text(),'keep')
    def test_eula(self):
        with self.assertRaisesRegex(ValueError,'EULA'):self.create(accepted=False)
    def test_names(self):
        for n in ('../world','CON','bad/name','hi&bye',''):
            with self.assertRaises(ValueError):b.validate_name(n)
    def test_loader_filtering(self):
        c=b.Catalog();c.cache[b.MOJANG]={'versions':[{'id':'1.21','type':'release'},{'id':'1.20','type':'release'}]};c.cache[b.FABRIC+'/game']=[{'version':'1.20','stable':True}]
        self.assertEqual(c.versions('Fabric'),['1.20'])
    def test_paper_contact_required(self):
        c=b.Catalog();c.cache[b.MOJANG]={'versions':[]}
        with self.assertRaisesRegex(ValueError,'contact'):c.versions('Paper')
    def test_paper_user_agent_contains_real_contact(self):
        request=b.Catalog('https://example.org/easy-realms').request(b.PAPER)
        self.assertIn('https://example.org/easy-realms',request.get_header('User-agent'))
        self.assertIn('EasyRealms/Public-Beta-1.0.2',request.get_header('User-agent'))
    def test_paper_request_rejects_missing_contact_before_network(self):
        with self.assertRaisesRegex(ValueError,'contact'):b.Catalog().request(b.PAPER)
    def test_linux_403_has_clear_error_without_unsafe_retry(self):
        error=urllib.error.HTTPError('https://example.org/file',403,'Forbidden',{},None)
        with patch.object(b.sys,'platform','linux'),patch.object(b.shutil,'which',return_value=None),patch.object(b.urllib.request,'urlopen',side_effect=error):
            with self.assertRaisesRegex(ValueError,'HTTP 403'):b.Catalog().open('https://example.org/file')
    def test_bedrock_catalog_parses_stable_and_preview(self):
        page='''"https:\\/\\/www.minecraft.net\\/bedrockdedicatedserver\\/bin-win\\/bedrock-server-1.26.63.1.zip" "/bedrockdedicatedserver/bin-win-preview/bedrock-server-1.26.70.23.zip"'''
        downloads=b.Catalog.parse_bedrock_downloads(page)
        self.assertIn('1.26.63.1',downloads)
        self.assertIn('Preview 1.26.70.23',downloads)
        self.assertTrue(downloads['1.26.63.1'].startswith('https://www.minecraft.net/'))
    def test_bedrock_catalog_parses_official_api(self):
        payload={'result':{'links':[
            {'downloadType':'serverBedrockWindows','downloadUrl':'https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-1.26.63.1.zip'},
            {'downloadType':'serverBedrockPreviewWindows','downloadUrl':'https://www.minecraft.net/bedrockdedicatedserver/bin-win-preview/bedrock-server-1.26.70.24.zip'},
            {'downloadType':'serverBedrockLinux','downloadUrl':'https://www.minecraft.net/bedrockdedicatedserver/bin-linux/bedrock-server-1.26.63.1.zip'}]}}
        downloads=b.Catalog.parse_bedrock_api(payload)
        self.assertEqual(list(downloads),['1.26.63.1','Preview 1.26.70.24'])
    def test_bedrock_api_rejects_untrusted_url(self):
        payload={'result':{'links':[{'downloadType':'serverBedrockWindows','downloadUrl':'https://example.org/bedrock-server-1.26.63.1.zip'}]}}
        self.assertEqual({},b.Catalog.parse_bedrock_api(payload))
    def test_create_bedrock_server(self):
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            archive.writestr('bedrock_server.exe',b'MZ')
            archive.writestr('server.properties','server-name=Dedicated Server\nserver-port=19132\n')
        data=output.getvalue();spec=dict(kind='Bedrock',version='1.26.63.1',java=None,detail='Official Windows server',url='https://example.org/bedrock.zip',algorithm='sha256',checksum=None)
        options=dict(catalog=b.Catalog(),spec=spec,parent=self.parent,name='Bedrock World',ram=4,java='Automatic',accepted=True,progress=lambda *a:None,cancel=threading.Event())
        with patch('backend.urllib.request.urlopen',return_value=Response(data)):
            path=Path(b.create_server(**options))
        self.assertTrue((path/'bedrock_server.exe').is_file())
        self.assertFalse((path/'eula.txt').exists())
        self.assertIn('server-name=Bedrock World',(path/'server.properties').read_text())
        self.assertIn('transport=nethernet',(path/'server.properties').read_text())
        self.assertEqual(json.loads((path/'easyservers.json').read_text())['kind'],'Bedrock')
    def test_java_version_parsing(self):
        for value,want in [('openjdk version "21.0.2"',21),('java version "1.8.0_321"',8)]:
            with patch('backend.subprocess.run') as run:
                run.return_value.stderr=value;run.return_value.stdout='';run.return_value.returncode=0
                self.assertEqual(b.java_major('java'),want)

if __name__=='__main__':unittest.main()
