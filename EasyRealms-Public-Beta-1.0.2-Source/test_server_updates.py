import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from server_updates import check_update, check_upgrade, install_update, upgrade_versions, version_key


def zip_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


class FakeResponse(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class FakeCatalog:
    def __init__(self, spec, versions=None):
        self.spec = spec
        self.available_versions = versions or [spec["version"]]

    def resolve(self, kind, version):
        self.requested = (kind, version)
        return dict(self.spec)

    def request(self, url):
        return url

    def versions(self, kind):
        return list(self.available_versions)


class ServerUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "Server"
        self.folder.mkdir()
        self.spec = {
            "kind": "Paper", "version": "1.21.4", "detail": "Stable build 120",
            "url": "https://example.invalid/server.jar", "algorithm": "sha256", "checksum": "",
            "java": 21,
        }
        self.config = {
            "name": "Server", "kind": "Paper", "version": "1.21.4",
            "jar": "server.jar", "java": "java", "ram": 4,
        }
        (self.folder / "server.jar").write_bytes(b"old server")
        (self.folder / "easyservers.json").write_text(json.dumps(self.config), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_untracked_server_can_adopt_current_build(self):
        plan = check_update(FakeCatalog(self.spec), self.config)
        self.assertTrue(plan.update_available)
        self.assertFalse(plan.managed_build)
        self.assertEqual(plan.available_build, "Stable build 120")

    def test_tracked_server_reports_current_and_newer_builds(self):
        tracked = dict(self.config, installed_build={key: self.spec.get(key) for key in ("kind", "version", "detail", "url", "checksum", "algorithm")})
        self.assertFalse(check_update(FakeCatalog(self.spec), tracked).update_available)
        newer = dict(self.spec, detail="Stable build 121", url="https://example.invalid/121.jar")
        self.assertTrue(check_update(FakeCatalog(newer), tracked).update_available)

    def test_java_update_is_verified_and_keeps_previous_jar(self):
        content = zip_bytes({"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\n", "version.json": "{}"})
        spec = dict(self.spec, checksum=hashlib.sha256(content).hexdigest())
        result = install_update(FakeCatalog(spec), self.folder, self.config, spec, opener=lambda *_args, **_kwargs: FakeResponse(content))
        self.assertEqual((self.folder / "server.jar").read_bytes(), content)
        self.assertEqual((self.folder / ".easyrealms-previous-server.jar").read_bytes(), b"old server")
        saved = json.loads((self.folder / "easyservers.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["installed_build"]["detail"], "Stable build 120")
        self.assertEqual(saved["java"], "java")
        self.assertEqual(saved["ram"], 4)
        self.assertTrue(result["rollback_file"])

    def test_checksum_failure_changes_nothing(self):
        content = zip_bytes({"version.json": "{}"})
        spec = dict(self.spec, checksum="0" * 64)
        before = (self.folder / "easyservers.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "checksum"):
            install_update(FakeCatalog(spec), self.folder, self.config, spec, opener=lambda *_args, **_kwargs: FakeResponse(content))
        self.assertEqual((self.folder / "server.jar").read_bytes(), b"old server")
        self.assertEqual((self.folder / "easyservers.json").read_bytes(), before)

    def test_refuses_cross_version_update(self):
        spec = dict(self.spec, version="1.22")
        with self.assertRaisesRegex(ValueError, "change"):
            install_update(FakeCatalog(spec), self.folder, self.config, spec)

    def test_upgrade_list_is_forward_only_and_same_channel(self):
        catalog = FakeCatalog(self.spec, ["1.22", "1.21.5", "1.21.4", "1.20.6", "Preview 1.23"])
        self.assertEqual(upgrade_versions(catalog, "Paper", "1.21.4"), ["1.22", "1.21.5"])
        self.assertGreater(version_key("26.3"), version_key("1.21.10"))

    def test_upgrade_preflight_blocks_unmanaged_addons(self):
        (self.folder / "plugins").mkdir()
        (self.folder / "plugins" / "manual.jar").write_bytes(b"manual")
        target = dict(self.spec, version="1.21.5", detail="Stable build 140")
        plan = check_upgrade(FakeCatalog(target), self.folder, self.config, "1.21.5")
        self.assertFalse(plan.can_upgrade)
        self.assertIn("manual.jar", " ".join(plan.blockers))

    def test_forward_upgrade_changes_version_only_when_allowed(self):
        content = zip_bytes({"version.json": "{}"})
        target = dict(self.spec, version="1.21.5", checksum=hashlib.sha256(content).hexdigest())
        install_update(FakeCatalog(target), self.folder, self.config, target, opener=lambda *_args, **_kwargs: FakeResponse(content), allow_version_change=True)
        saved = json.loads((self.folder / "easyservers.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], "1.21.5")
        self.assertEqual(saved["java"], "java")

    def test_upgrade_preflight_blocks_downgrade(self):
        target = dict(self.spec, version="1.20.6")
        with self.assertRaisesRegex(ValueError, "Downgrades"):
            check_upgrade(FakeCatalog(target), self.folder, self.config, "1.20.6")

    def test_bedrock_update_preserves_world_and_settings(self):
        config = {"name": "Bedrock", "kind": "Bedrock", "version": "1.21.0", "executable": "bedrock_server.exe"}
        (self.folder / "easyservers.json").write_text(json.dumps(config), encoding="utf-8")
        (self.folder / "bedrock_server.exe").write_bytes(b"old exe")
        (self.folder / "server.properties").write_text("server-name=Mine\n", encoding="utf-8")
        (self.folder / "worlds").mkdir();(self.folder / "worlds" / "level.dat").write_bytes(b"world")
        content = zip_bytes({"bedrock_server.exe": b"new exe", "server.properties": "server-name=Default\n", "worlds/new/level.dat": b"replace", "runtime.dll": b"dll"})
        spec = {"kind": "Bedrock", "version": "1.21.0", "detail": "Official Windows server", "url": "https://example.invalid/bedrock.zip", "algorithm": "sha256", "checksum": None}
        install_update(FakeCatalog(spec), self.folder, config, spec, opener=lambda *_args, **_kwargs: FakeResponse(content))
        self.assertEqual((self.folder / "bedrock_server.exe").read_bytes(), b"new exe")
        self.assertEqual((self.folder / "runtime.dll").read_bytes(), b"dll")
        self.assertEqual((self.folder / "server.properties").read_text(encoding="utf-8"), "server-name=Mine\n")
        self.assertEqual((self.folder / "worlds" / "level.dat").read_bytes(), b"world")


if __name__ == "__main__":
    unittest.main()
