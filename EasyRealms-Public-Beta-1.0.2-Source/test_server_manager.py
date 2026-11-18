import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from server_manager import BackupStore, ServerEntry, ServerLibrary, inspect_server, read_properties, update_properties


class ServerManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server = self.root / "World"
        self.server.mkdir()
        (self.server / "server.jar").write_bytes(b"jar")
        (self.server / "server.properties").write_text("# keep me\nmotd=Old\nunknown=keep\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_import_detects_and_deduplicates(self):
        (self.server / "plugins").mkdir()
        library = ServerLibrary(self.root / "data")
        first = library.add(self.server)
        second = library.add(self.server)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.kind, "Paper")
        self.assertEqual(len(library.all()), 1)

    def test_properties_preserve_unknown_lines(self):
        update_properties(self.server, {"motd": "New world", "max-players": "12"})
        text = (self.server / "server.properties").read_text(encoding="utf-8")
        self.assertIn("# keep me", text)
        self.assertIn("unknown=keep", text)
        self.assertEqual(read_properties(self.server)["motd"], "New world")
        self.assertEqual(read_properties(self.server)["max-players"], "12")

    def test_backup_and_restore_keeps_recovery_copy(self):
        entry = ServerEntry("abc", "World", str(self.server))
        store = BackupStore(self.root / "data")
        archive = store.create(entry)
        (self.server / "server.properties").write_text("motd=Changed\n", encoding="utf-8")
        recovery = store.restore(entry, archive)
        self.assertTrue(recovery.is_dir())
        self.assertIn("motd=Old", (self.server / "server.properties").read_text(encoding="utf-8"))

    def test_backup_retention_removes_only_old_archives(self):
        entry = ServerEntry("abc", "World", str(self.server))
        store = BackupStore(self.root / "data")
        manual = store.create(entry)
        for _ in range(4):
            store.create(entry, automatic=True)
        removed = store.prune(entry, keep=2, automatic_only=True)
        self.assertEqual(len(removed), 2)
        self.assertEqual(len(store.list(entry)), 3)
        self.assertTrue(manual.exists())
        self.assertTrue(all(not archive.exists() for archive in removed))

    def test_rejects_invalid_folder(self):
        empty = self.root / "Empty"
        empty.mkdir()
        with self.assertRaises(ValueError):
            inspect_server(empty)
    def test_detects_bedrock_server(self):
        bedrock=self.root/'Bedrock';bedrock.mkdir();(bedrock/'bedrock_server.exe').write_bytes(b'MZ');(bedrock/'server.properties').write_text('server-name=Bedrock\n')
        self.assertEqual(inspect_server(bedrock)['kind'],'Bedrock')


if __name__ == "__main__":
    unittest.main()
