import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

loader=importlib.machinery.SourceFileLoader('bootstrap',str(Path(__file__).with_name('bootstrap.pyw')))
spec=importlib.util.spec_from_loader(loader.name,loader)
b=importlib.util.module_from_spec(spec);loader.exec_module(b)

class StartupTests(unittest.TestCase):
    def run_setup(self,dependency_results=None,pip_code=0,child_fails=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);python=root/'.venv'/('Scripts/python.exe' if b.os.name=='nt' else 'bin/python')
            python.parent.mkdir(parents=True);python.touch()
            (root/'dependency_check.py').touch()
            messages=[]
            def popen(*args,**kwargs):
                child=MagicMock();child.poll.return_value=1 if child_fails else None
                if not child_fails:Path(kwargs['env']['EASY_SERVERS_READY_FILE']).write_text('ready')
                return child
            results=list(dependency_results or [0,0])
            def run_process(args,**kwargs):
                result=MagicMock()
                if args[1:3] == ['-m','pip']:
                    result.returncode=pip_code
                else:
                    result.returncode=results.pop(0)
                return result
            with patch.object(b,'ROOT',root),patch.object(b,'LOG',root/'startup.log'),patch.object(b,'command') as command,patch.object(b.subprocess,'run',side_effect=run_process),patch.object(b.subprocess,'Popen',side_effect=popen):
                if child_fails:
                    with self.assertRaisesRegex(RuntimeError,'dashboard could not open'):b.prepare(messages.append)
                else:b.prepare(messages.append)
                return command.call_count,messages
    def test_ready_environment_skips_installer(self):
        count,messages=self.run_setup();self.assertEqual(count,0);self.assertIn('Opening your server dashboard…',messages)
    def test_missing_dependency_installs(self):
        count,messages=self.run_setup([1,0,0]);self.assertEqual(count,1);self.assertIn('Verifying installed components…',messages)
    def test_missing_pip_is_bootstrapped_before_packages(self):
        count,_=self.run_setup([1,0,0],pip_code=1);self.assertEqual(count,2)
    def test_failed_dependency_verification_stops_launch(self):
        with self.assertRaisesRegex(RuntimeError,'did not pass verification'):
            self.run_setup([1,1],pip_code=0)
    def test_crash_reports_error(self):self.run_setup(child_fails=True)
    def test_failed_setup_is_reported(self):
        with patch.object(b.subprocess,'run') as run:
            run.return_value.returncode=1
            with self.assertRaisesRegex(RuntimeError,'Setup could not complete'):b.command(['python'],None,1)

if __name__=='__main__':unittest.main()
