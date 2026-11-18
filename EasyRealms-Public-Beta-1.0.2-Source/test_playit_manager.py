import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from playit_manager import (
    PlayitStatus,
    check_playit_status,
    claim_url_from_output,
    find_playit_executable,
    tunnel_target,
)


class PlayitManagerTests(unittest.TestCase):
    def test_claim_url_accepts_only_exact_playit_format(self):
        output = "Open https://playit.gg/claim/0123aBCdef to approve"
        self.assertEqual(claim_url_from_output(output), "https://playit.gg/claim/0123aBCdef")
        self.assertEqual(claim_url_from_output("https://evil.test/claim/0123abcdef"), "")
        self.assertEqual(claim_url_from_output("https://playit.gg/claim/not-a-code"), "")
        self.assertEqual(claim_url_from_output("https://playit.gg/claim/0123abcdef/extra"), "")
        self.assertEqual(claim_url_from_output("https://playit.gg/claim/0123abcdef?next=evil"), "")
        self.assertEqual(claim_url_from_output("https://playit.gg.evil.test/claim/0123abcdef"), "")

    def test_executable_search_rejects_unrelated_programs(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder) / "helper.exe"
            good = Path(folder) / "playit.exe"
            bad.write_bytes(b"x")
            good.write_bytes(b"x")
            self.assertEqual(find_playit_executable([bad, good], require_protected=False), good.resolve())
            self.assertIsNone(find_playit_executable([bad], require_protected=False))

    def test_protected_install_check_can_reject_user_writable_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "playit.exe"
            executable.write_bytes(b"x")
            with patch("playit_manager._inside_windows_program_files", return_value=False):
                self.assertIsNone(find_playit_executable([executable], require_protected=True))

    def test_server_targets_use_loopback_only(self):
        java = tunnel_target("Paper", {"server-port": "25570"})
        bedrock = tunnel_target("Bedrock", {"server-port": "19133"})
        self.assertEqual(java.local_address, "127.0.0.1:25570")
        self.assertEqual(java.tunnel_type, "Minecraft Java")
        self.assertEqual(bedrock.local_address, "127.0.0.1:19133")
        self.assertIn("NetherNet", bedrock.tunnel_type)

    def test_status_does_not_require_playit_to_be_installed(self):
        with patch("playit_manager.find_playit_executable", return_value=None):
            status = check_playit_status()
        self.assertFalse(status.installed)
        self.assertIn("machine-installed Playit", status.message)

    def test_successful_status_is_reported(self):
        result = type("Result", (), {"returncode": 0})()
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / "playit.exe"
            executable.write_bytes(b"x")
            with patch("playit_manager.subprocess.run", return_value=result):
                status = check_playit_status(executable)
        self.assertTrue(status.installed)
        self.assertTrue(status.running)


if __name__ == "__main__":
    unittest.main()
