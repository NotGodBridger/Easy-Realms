import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from server_health import blocking_issues, check_server, format_report


class ServerHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def java_server(self, **changes):
        folder = self.root / "Java"
        folder.mkdir()
        with zipfile.ZipFile(folder / "server.jar", "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0")
        (folder / "server.properties").write_text("online-mode=true\nwhite-list=true\nserver-port=25565\n")
        config = {"name": "Java", "kind": "Vanilla", "jar": "server.jar", "java": __import__("sys").executable, "ram": 4}
        config.update(changes)
        return folder, config

    def test_healthy_java_server_has_no_blockers(self):
        folder, config = self.java_server()
        checks = check_server(folder, config)
        self.assertEqual(blocking_issues(checks), [])
        self.assertIn("0 blocking issue(s)", format_report("Java", checks))

    def test_missing_jar_and_java_are_blocking(self):
        folder, config = self.java_server(jar="missing.jar", java="missing-java-command")
        titles = {item.title for item in blocking_issues(check_server(folder, config))}
        self.assertIn("Server JAR", titles)
        self.assertIn("Java runtime", titles)

    def test_rejects_configured_path_outside_server(self):
        folder, config = self.java_server(jar="../outside.jar")
        self.assertTrue(any(item.title == "Server JAR" and item.level == "error" for item in check_server(folder, config)))

    def test_public_security_warnings(self):
        folder, config = self.java_server(auto_port_forward=True)
        (folder / "server.properties").write_text("online-mode=false\nwhite-list=false\nserver-port=25565\n")
        warnings = [item.title for item in check_server(folder, config) if item.level == "warning"]
        self.assertIn("Account authentication", warnings)
        self.assertIn("Player access list", warnings)
        self.assertIn("Internet sharing", warnings)

    def test_bedrock_program_and_nethernet(self):
        folder = self.root / "Bedrock";folder.mkdir()
        (folder / "bedrock_server.exe").write_bytes(b"MZ")
        (folder / "server.properties").write_text("server-port=19132\ntransport=nethernet\nonline-mode=true\nallow-list=true\n")
        checks = check_server(folder, {"kind": "Bedrock", "executable": "bedrock_server.exe"})
        self.assertEqual(blocking_issues(checks), [])
        self.assertTrue(any(item.title == "Bedrock transport" and item.level == "pass" for item in checks))


if __name__ == "__main__":
    unittest.main()
