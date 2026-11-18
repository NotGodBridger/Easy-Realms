from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import dependency_check as dependencies


class DependencyCheckTests(unittest.TestCase):
    def test_version_parser_ignores_suffixes(self):
        self.assertEqual(dependencies.version_tuple('6.8.3'), (6, 8, 3))
        self.assertEqual(dependencies.version_tuple('6.9.0rc1'), (6, 9, 0))
        self.assertEqual(dependencies.version_tuple('unknown'), ())

    def test_required_file_check_lists_only_missing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative in dependencies.REQUIRED_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            self.assertEqual(dependencies.check_files(root), [])
            (root / dependencies.REQUIRED_FILES[0]).unlink()
            self.assertEqual(len(dependencies.check_files(root)), 1)

    def test_cli_reports_success_when_checks_pass(self):
        with patch.object(dependencies, 'check_dependencies', return_value=[]), \
             patch.object(dependencies, 'check_files', return_value=[]):
            self.assertEqual(dependencies.main([]), 0)

    def test_cli_reports_failure(self):
        with patch.object(dependencies, 'check_dependencies', return_value=['missing']), \
             patch.object(dependencies, 'check_files', return_value=[]):
            self.assertEqual(dependencies.main([]), 1)


if __name__ == '__main__':
    unittest.main()
