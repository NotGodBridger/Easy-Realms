import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from addons import AddonError, AddonManager, client_requirement, loader_for_kind


def jar_bytes():
    with tempfile.NamedTemporaryFile(suffix=".jar") as temp:
        with zipfile.ZipFile(temp.name, "w") as archive:
            archive.writestr("fabric.mod.json", "{}")
        temp.seek(0)
        return temp.read()


class FakeClient:
    def __init__(self):
        self.payload = jar_bytes()
        self.projects = {
            "root": {"id": "root", "slug": "root", "title": "Root Mod"},
            "dep": {"id": "dep", "slug": "dep", "title": "Required Library"},
            "optional": {"id": "optional", "slug": "optional", "title": "Optional Extra"},
        }
        self.version_map = {
            "root-v1": self.make_version("root", "root-v1", "1.0.0", "root-1.jar", [
                {"project_id": "dep", "dependency_type": "required"},
                {"project_id": "optional", "dependency_type": "optional"},
            ], "client_and_server"),
            "root-v2": self.make_version("root", "root-v2", "2.0.0", "root-2.jar", [
                {"project_id": "dep", "dependency_type": "required"},
            ], "client_and_server"),
            "dep-v1": self.make_version("dep", "dep-v1", "1.0.0", "dep.jar", [], "server_only"),
        }
        self.latest = {"root": "root-v1", "dep": "dep-v1"}
        self.search_args = None

    def make_version(self, project, id_, number, filename, dependencies, environment):
        return {
            "id": id_, "project_id": project, "name": project, "version_number": number,
            "game_versions": ["1.21.1"], "loaders": ["fabric"], "environment": environment,
            "status": "listed", "version_type": "release", "date_published": number,
            "dependencies": dependencies,
            "files": [{
                "filename": filename, "primary": True, "url": "https://cdn.modrinth.com/data/test/versions/test/" + filename,
                "size": len(self.payload), "hashes": {"sha512": hashlib.sha512(self.payload).hexdigest()},
            }],
        }

    def search(self, query, minecraft_version, loader):
        self.search_args = (query, minecraft_version, loader)
        return [{"project_id": "root", "title": "Root Mod"}]

    def project(self, project_id):
        return self.projects[project_id]

    def version(self, version_id):
        return self.version_map[version_id]

    def resolve_version(self, project_id, minecraft_version, loader):
        return self.version_map[self.latest[project_id]]

    def download(self, file, destination):
        destination.write_bytes(self.payload)
        return destination


class AddonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.client = FakeClient()
        self.manager = AddonManager(self.folder, "Fabric", "1.21.1", self.client)

    def tearDown(self):
        self.temp.cleanup()

    def test_kind_and_client_warning_mapping(self):
        self.assertEqual(loader_for_kind("Fabric"), "fabric")
        self.assertEqual(client_requirement("client_and_server"), "required")
        self.assertEqual(client_requirement("client_or_server_prefers_both"), "recommended")
        self.assertEqual(client_requirement("server_only"), "not required")

    def test_install_tracks_required_dependency_but_not_optional(self):
        installed = self.manager.install("root")
        self.assertEqual({item["project_id"] for item in installed}, {"root", "dep"})
        self.assertTrue((self.folder / "mods" / "root-1.jar").is_file())
        self.assertTrue((self.folder / "mods" / "dep.jar").is_file())
        data = json.loads((self.folder / ".easyrealms-addons.json").read_text())
        self.assertNotIn("optional", data["addons"])
        self.assertEqual(data["addons"]["dep"]["required_by"], ["root"])

    def test_remove_root_removes_orphan_dependency(self):
        self.manager.install("root")
        removed = self.manager.remove("root")
        self.assertEqual(set(removed), {"Root Mod", "Required Library"})
        self.assertFalse((self.folder / "mods" / "dep.jar").exists())
        self.assertEqual(self.manager.installed(), [])

    def test_update_replaces_old_file(self):
        self.manager.install("root")
        self.client.latest["root"] = "root-v2"
        self.manager.update("root")
        self.assertFalse((self.folder / "mods" / "root-1.jar").exists())
        self.assertTrue((self.folder / "mods" / "root-2.jar").is_file())
        self.assertEqual(self.manager.load()["addons"]["root"]["version_id"], "root-v2")

    def test_preview_marks_client_requirement_and_dependency(self):
        preview = {item["project_id"]: item for item in self.manager.preview("root")}
        self.assertEqual(preview["root"]["client_requirement"], "required")
        self.assertFalse(preview["root"]["is_dependency"])
        self.assertTrue(preview["dep"]["is_dependency"])

    def test_refuses_to_overwrite_unmanaged_same_filename(self):
        mods = self.folder / "mods"; mods.mkdir(); (mods / "root-1.jar").write_bytes(b"mine")
        with self.assertRaises(AddonError):
            self.manager.install("root")
        self.assertEqual((mods / "root-1.jar").read_bytes(), b"mine")

    def test_unsupported_kind(self):
        with self.assertRaises(AddonError):
            AddonManager(self.folder, "Vanilla", "1.21.1", self.client)

    def test_search_uses_exact_version_and_loader(self):
        self.manager.search("voice chat")
        self.assertEqual(self.client.search_args, ("voice chat", "1.21.1", "fabric"))


if __name__ == "__main__":
    unittest.main()
