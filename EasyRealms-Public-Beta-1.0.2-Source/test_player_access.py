import json
import tempfile
import unittest
from pathlib import Path

from player_access import PlayerAccessError, load_access_snapshot, player_commands, validate_player_name


class PlayerAccessTests(unittest.TestCase):
    def test_java_names_are_strict(self):
        self.assertEqual(validate_player_name("Vanilla", "Steve_123"), "Steve_123")
        for unsafe in ("ab", "name with space", "@a", "Steve\nstop", "name;op"):
            with self.assertRaises(PlayerAccessError):
                validate_player_name("Paper", unsafe)

    def test_bedrock_gamertags_are_quoted_without_command_injection(self):
        self.assertEqual(player_commands("Bedrock", "add", "Example Player"), (
            "allowlist on", 'allowlist add "Example Player"'
        ))
        for unsafe in ('Name" stop', "@a", "Name\\stop", "Name;stop", "Name\nstop"):
            with self.assertRaises(PlayerAccessError):
                player_commands("Bedrock", "add", unsafe)

    def test_remove_revokes_operator_before_access(self):
        self.assertEqual(player_commands("Vanilla", "remove", "Steve"), (
            "deop Steve", "whitelist remove Steve"
        ))

    def test_list_and_enable_are_edition_aware(self):
        self.assertEqual(player_commands("Fabric", "list"), ("whitelist list",))
        self.assertEqual(player_commands("Bedrock", "enable"), ("allowlist on",))

    def test_reads_java_access_files_without_modifying_them(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            whitelist = [{"uuid": "1", "name": "Alex"}, {"uuid": "2", "name": "Steve"}]
            operators = [{"uuid": "2", "name": "Steve", "level": 4}]
            (root / "whitelist.json").write_text(json.dumps(whitelist), encoding="utf-8")
            (root / "ops.json").write_text(json.dumps(operators), encoding="utf-8")
            before = (root / "whitelist.json").read_bytes()
            snapshot = load_access_snapshot(root, "Vanilla")
            self.assertEqual(snapshot.allowed, ("Alex", "Steve"))
            self.assertEqual(snapshot.operators, ("Steve",))
            self.assertEqual((root / "whitelist.json").read_bytes(), before)

    def test_rejects_malformed_access_file(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "allowlist.json").write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(PlayerAccessError, "could not be read safely"):
                load_access_snapshot(folder, "Bedrock")


if __name__ == "__main__":
    unittest.main()
