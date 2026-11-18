from pathlib import Path
import os
import tempfile
import unittest
import zipfile

from diagnostics import DiagnosticSession, _has_clean_footer, create_support_bundle


class DiagnosticTests(unittest.TestCase):
    def test_each_launch_writes_a_clean_session_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = DiagnosticSession('test', Path(temporary), keep=5)
            session.warning('Test warning without private values')
            path = session.path
            session.finish(0)
            contents = path.read_text(encoding='utf-8')
            self.assertIn('SESSION START Easy Realms test', contents)
            self.assertIn('Test warning without private values', contents)
            self.assertIn('SESSION END status=clean exit_code=0', contents)
            self.assertTrue(_has_clean_footer(path))

    def test_incomplete_previous_launch_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            logs = Path(temporary) / 'logs'; logs.mkdir()
            (logs / 'easy-realms-old.log').write_text('SESSION START\n', encoding='utf-8')
            session = DiagnosticSession('test', Path(temporary), keep=5)
            path = session.path
            session.finish()
            self.assertIn('previous session did not record a clean shutdown', path.read_text(encoding='utf-8'))

    def test_old_logs_are_pruned(self):
        with tempfile.TemporaryDirectory() as temporary:
            logs = Path(temporary) / 'logs'; logs.mkdir()
            for index in range(8):
                path = logs / f'easy-realms-{index:02}.log'
                path.write_text('SESSION END status=clean\n', encoding='utf-8')
                path.touch()
            session = DiagnosticSession('test', Path(temporary), keep=4)
            session.finish()
            self.assertLessEqual(len(list(logs.glob('easy-realms-*.log'))), 4)

    def test_support_bundle_is_redacted_and_excludes_private_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / 'data'; logs = data / 'logs'; logs.mkdir(parents=True)
            private = 'C:\\Users\\Alice\\Easy Realms\\server contact=alice@example.com ip=203.0.113.42 token=super-secret https://playit.gg/claim/ABC123\n'
            for index in range(7):
                path = logs / f'easy-realms-{index}.log'; path.write_text(private, encoding='utf-8');os.utime(path, (index + 1, index + 1))
            (data / 'settings.ini').write_text('password=do-not-include', encoding='utf-8')
            world = data / 'servers' / 'World';world.mkdir(parents=True);(world / 'level.dat').write_bytes(b'private world')
            destination = Path(temporary) / 'support.zip'
            report = 'Easy Realms Server Doctor — Secret World\n[PASS] Server folder: C:\\Users\\Alice\\World'
            create_support_bundle(data, destination, 'test-version', report)
            with zipfile.ZipFile(destination) as archive:
                names = set(archive.namelist());combined = '\n'.join(archive.read(name).decode('utf-8') for name in names)
            self.assertIn('README.txt', names);self.assertIn('system.txt', names);self.assertIn('server-doctor.txt', names)
            self.assertEqual(len([name for name in names if name.startswith('logs/')]), 5)
            self.assertNotIn('settings.ini', names);self.assertNotIn('level.dat', names)
            for private_value in ('Alice', 'alice@example.com', '203.0.113.42', 'super-secret', 'ABC123', 'Secret World'):
                self.assertNotIn(private_value, combined)
            self.assertIn('<EMAIL>', combined);self.assertIn('<IP_ADDRESS>', combined);self.assertIn('<SERVER>', combined)

    def test_support_bundle_caps_large_log_and_adds_zip_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary);logs = data / 'logs';logs.mkdir()
            (logs / 'easy-realms-large.log').write_text('x' * (1024 * 1024 + 200), encoding='utf-8')
            result = create_support_bundle(data, Path(temporary) / 'report', 'test')
            self.assertEqual(result.suffix, '.zip')
            with zipfile.ZipFile(result) as archive:
                text = archive.read('logs/easy-realms-large.log').decode('utf-8')
            self.assertTrue(text.startswith('[Earlier content omitted by Easy Realms]'))
            self.assertLess(len(text), 1024 * 1024 + 100)

    def test_support_bundle_refuses_linked_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);data = root / 'data';logs = data / 'logs';logs.mkdir(parents=True)
            outside = root / 'private.txt';outside.write_text('should never be included', encoding='utf-8')
            linked = logs / 'easy-realms-linked.log'
            try:linked.symlink_to(outside)
            except (OSError, NotImplementedError):self.skipTest('Symbolic links are unavailable')
            destination = create_support_bundle(data, root / 'support.zip', 'test')
            with zipfile.ZipFile(destination) as archive:
                self.assertFalse(any('linked' in name for name in archive.namelist()))
                combined = '\n'.join(archive.read(name).decode('utf-8') for name in archive.namelist())
            self.assertNotIn('should never be included', combined)


if __name__ == '__main__':
    unittest.main()
