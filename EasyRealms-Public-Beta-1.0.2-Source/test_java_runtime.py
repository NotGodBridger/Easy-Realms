import io,json,hashlib,tempfile,threading,types,zipfile,unittest,tarfile
from pathlib import Path
from unittest.mock import patch
import java_runtime as j
class Reply(io.BytesIO):
    headers={}
class JavaRuntimeTests(unittest.TestCase):
    def test_existing_java_needs_no_download(self):
        with patch.object(j.urllib.request,'urlopen') as fetch:
            self.assertEqual(j.ensure_java(21,'Automatic',lambda *a:None,threading.Event(),lambda _:21),'java')
            fetch.assert_not_called()
    def test_verified_install_and_cache(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('jdk-21/bin/java.exe',b'test runtime')
        data=out.getvalue();meta=[{'binary':{'package':{'link':'https://example.org/java.zip','checksum':hashlib.sha256(data).hexdigest()}}}]
        with tempfile.TemporaryDirectory() as tmp:
            def detect(path):
                if path=='java':raise ValueError('missing')
                return 21
            with patch.object(j,'os',types.SimpleNamespace(name='nt',environ={'EASY_REALMS_DATA':tmp})),patch.object(j.urllib.request,'urlopen',side_effect=[Reply(json.dumps(meta).encode()),Reply(data)]) as fetch:
                path=j.ensure_java(21,'Automatic',lambda *a:None,threading.Event(),detect)
                self.assertTrue(Path(path).is_file());self.assertIn(str(Path(tmp)/'java'),path)
                self.assertEqual(j.ensure_java(21,'Automatic',lambda *a:None,threading.Event(),detect),path)
                self.assertEqual(fetch.call_count,2)
    def test_explicit_wrong_java_is_not_replaced(self):
        with self.assertRaisesRegex(ValueError,'Select Java 21'):
            j.ensure_java(21,'custom-java',lambda *a:None,threading.Event(),lambda _:17)
    def test_verified_linux_install(self):
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w:gz') as archive:
            payload=b'test linux runtime';info=tarfile.TarInfo('jdk-21/bin/java');info.size=len(payload);info.mode=0o755
            archive.addfile(info,io.BytesIO(payload))
        data=out.getvalue();meta=[{'binary':{'package':{'link':'https://example.org/java.tar.gz','checksum':hashlib.sha256(data).hexdigest()}}}]
        with tempfile.TemporaryDirectory() as tmp:
            def detect(path):
                if path=='java':raise ValueError('missing')
                return 21
            fake_os=types.SimpleNamespace(name='posix',environ={'EASY_REALMS_DATA':tmp})
            with patch.object(j,'os',fake_os),patch.object(j.sys,'platform','linux'),patch.object(j.platform,'machine',return_value='x86_64'),patch.object(j.urllib.request,'urlopen',side_effect=[Reply(json.dumps(meta).encode()),Reply(data)]):
                path=j.ensure_java(21,'Automatic',lambda *a:None,threading.Event(),detect)
                self.assertTrue(Path(path).is_file());self.assertTrue(Path(path).stat().st_mode&0o111)
    def test_linux_tar_rejects_links(self):
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w:gz') as archive:
            info=tarfile.TarInfo('jdk-21/bin/java');info.type=tarfile.SYMTYPE;info.linkname='/bin/sh';archive.addfile(info)
        with tempfile.TemporaryDirectory() as tmp:
            archive_path=Path(tmp)/'java.tar.gz';archive_path.write_bytes(out.getvalue());destination=Path(tmp)/'out';destination.mkdir()
            with self.assertRaisesRegex(ValueError,'Unsafe'):
                j._extract_tar(archive_path,destination,threading.Event(),RuntimeError)
    def test_linux_tar_allows_safe_internal_links(self):
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w:gz') as archive:
            payload=b'licence';base=tarfile.TarInfo('jdk-21/legal/java.base/LICENSE');base.size=len(payload);archive.addfile(base,io.BytesIO(payload))
            link=tarfile.TarInfo('jdk-21/legal/java.naming/LICENSE');link.type=tarfile.SYMTYPE;link.linkname='../java.base/LICENSE';archive.addfile(link)
        with tempfile.TemporaryDirectory() as tmp:
            archive_path=Path(tmp)/'java.tar.gz';archive_path.write_bytes(out.getvalue());destination=Path(tmp)/'out';destination.mkdir()
            j._extract_tar(archive_path,destination,threading.Event(),RuntimeError)
            self.assertEqual((destination/'jdk-21/legal/java.naming/LICENSE').read_bytes(),b'licence')
if __name__=='__main__':unittest.main()
