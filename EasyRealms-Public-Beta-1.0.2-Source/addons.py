from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


API = "https://api.modrinth.com/v2"
MANIFEST = ".easyrealms-addons.json"
MAX_ADDON_SIZE = 256 * 1024 * 1024
SERVER_ENVIRONMENTS = {
    "client_and_server",
    "client_only_server_optional",
    "server_only",
    "server_only_client_optional",
    "dedicated_server_only",
    "client_or_server",
    "client_or_server_prefers_both",
    "unknown",
}
FABRIC_PRESETS = {
    "Performance essentials": ["fabric-api", "lithium", "ferrite-core"],
    "Simple Voice Chat": ["simple-voice-chat"],
}


class AddonError(RuntimeError):
    pass


def loader_for_kind(kind: str) -> str:
    loader = {"Fabric": "fabric", "Paper": "paper"}.get(kind)
    if not loader:
        raise AddonError("Mods and plugins are currently available for Fabric and Paper servers.")
    return loader


def addon_folder_for_kind(kind: str) -> str:
    loader_for_kind(kind)
    return "mods" if kind == "Fabric" else "plugins"


def client_requirement(environment: str) -> str:
    if environment in {"client_and_server", "client_only_server_optional"}:
        return "required"
    if environment == "client_or_server_prefers_both":
        return "recommended"
    if environment == "unknown":
        return "unknown"
    return "not required"


def _primary_file(version: dict) -> dict:
    files = version.get("files") or []
    file = next((item for item in files if item.get("primary")), files[0] if files else None)
    if not file:
        raise AddonError(f"Modrinth version {version.get('version_number', '')} has no downloadable file.")
    filename = Path(str(file.get("filename", ""))).name
    if not filename or not filename.lower().endswith(".jar"):
        raise AddonError("Easy Realms only installs Modrinth JAR files.")
    try:
        size = int(file.get("size", 0))
    except (TypeError, ValueError):
        size = 0
    if size < 0 or size > MAX_ADDON_SIZE:
        raise AddonError(f"{filename} is larger than the 256 MB safety limit.")
    return file


class ModrinthClient:
    def __init__(self):
        self.cache: dict[tuple, object] = {}
        self.user_agent = "EasyRealms/Public-Beta-1.0.2 (desktop server manager)"

    def _json(self, path: str, params: dict | None = None):
        query = urllib.parse.urlencode(params or {}, doseq=True)
        url = API + path + (("?" + query) if query else "")
        key = (url,)
        if key in self.cache:
            return self.cache[key]
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                value = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise AddonError("That Modrinth project or version no longer exists.") from exc
            raise AddonError(f"Modrinth returned HTTP {exc.code}. Try again in a moment.") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise AddonError(f"Could not reach Modrinth: {exc}") from exc
        self.cache[key] = value
        return value

    def search(self, query: str, minecraft_version: str, loader: str, limit: int = 20, offset: int = 0) -> list[dict]:
        facets = [
            ["project_type:mod"],
            [f"versions:{minecraft_version}"],
            [f"categories:{loader}"],
            [f"environment:{value}" for value in sorted(SERVER_ENVIRONMENTS)],
        ]
        result = self._json("/search", {
            "query": query.strip(),
            "limit": max(1, min(50, int(limit))),
            "offset": max(0, int(offset)),
            "index": "relevance",
            "facets": json.dumps(facets, separators=(",", ":")),
        })
        return list(result.get("hits", []))

    def project(self, project_id: str) -> dict:
        return self._json("/project/" + urllib.parse.quote(str(project_id), safe=""))

    def version(self, version_id: str) -> dict:
        return self._json("/version/" + urllib.parse.quote(str(version_id), safe=""))

    def versions(self, project_id: str) -> list[dict]:
        return list(self._json("/project/" + urllib.parse.quote(str(project_id), safe="") + "/version"))

    def resolve_version(self, project_id: str, minecraft_version: str, loader: str) -> dict:
        candidates = []
        for version in self.versions(project_id):
            if minecraft_version not in (version.get("game_versions") or []):
                continue
            if loader not in (version.get("loaders") or []):
                continue
            if version.get("environment", version.get("server_side", "unknown")) not in SERVER_ENVIRONMENTS:
                continue
            if version.get("status", "listed") not in {"listed", "unlisted"}:
                continue
            candidates.append(version)
        if not candidates:
            raise AddonError(f"No server-compatible {loader.title()} build supports Minecraft {minecraft_version}.")
        candidates.sort(key=lambda item: (item.get("version_type") == "release", item.get("date_published", "")), reverse=True)
        return candidates[0]

    def download(self, file: dict, destination: Path) -> Path:
        url = str(file.get("url", ""))
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "cdn.modrinth.com":
            raise AddonError("Easy Realms blocked a download outside Modrinth's official CDN.")
        expected_size = int(file.get("size", 0) or 0)
        if expected_size > MAX_ADDON_SIZE:
            raise AddonError("This add-on is larger than the 256 MB safety limit.")
        hashes = file.get("hashes") or {}
        expected_sha512 = str(hashes.get("sha512", "")).lower()
        expected_sha1 = str(hashes.get("sha1", "")).lower()
        if not expected_sha512 and not expected_sha1:
            raise AddonError("Modrinth did not provide a file hash, so Easy Realms refused the download.")
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        sha512 = hashlib.sha512(); sha1 = hashlib.sha1(); total = 0
        try:
            with urllib.request.urlopen(request, timeout=45) as response, destination.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ADDON_SIZE:
                        raise AddonError("The download exceeded the 256 MB safety limit.")
                    sha512.update(chunk); sha1.update(chunk); output.write(chunk)
        except AddonError:
            destination.unlink(missing_ok=True)
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            destination.unlink(missing_ok=True)
            raise AddonError(f"The Modrinth download failed: {exc}") from exc
        if expected_size and total != expected_size:
            destination.unlink(missing_ok=True)
            raise AddonError("The downloaded file size did not match Modrinth's record.")
        actual = sha512.hexdigest() if expected_sha512 else sha1.hexdigest()
        expected = expected_sha512 or expected_sha1
        if actual != expected:
            destination.unlink(missing_ok=True)
            raise AddonError("The downloaded file failed its Modrinth hash check.")
        if not zipfile.is_zipfile(destination):
            destination.unlink(missing_ok=True)
            raise AddonError("The downloaded file is not a valid JAR archive.")
        return destination


class AddonManager:
    def __init__(self, server_folder, kind: str, minecraft_version: str, client=None):
        self.server = Path(server_folder)
        self.kind = kind
        self.minecraft_version = str(minecraft_version)
        self.loader = loader_for_kind(kind)
        self.folder = self.server / addon_folder_for_kind(kind)
        self.manifest = self.server / MANIFEST
        self.client = client or ModrinthClient()

    def load(self) -> dict:
        try:
            value = json.loads(self.manifest.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("addons", {}), dict):
                raise ValueError
            return value
        except FileNotFoundError:
            return {"schema": 1, "addons": {}}
        except (OSError, ValueError, TypeError) as exc:
            raise AddonError(f"Could not read {MANIFEST}. Restore it or remove the broken file before continuing.") from exc

    def installed(self) -> list[dict]:
        return sorted(self.load()["addons"].values(), key=lambda item: (bool(item.get("installed_as_dependency")), str(item.get("name", "")).lower()))

    def search(self, query: str) -> list[dict]:
        return self.client.search(query, self.minecraft_version, self.loader)

    def _validate_version(self, project_id: str, version: dict):
        if project_id not in {str(version.get("project_id", "")), str(version.get("project_id", project_id))}:
            raise AddonError("A dependency version did not belong to the expected Modrinth project.")
        if self.minecraft_version not in (version.get("game_versions") or []):
            raise AddonError(f"{version.get('name', project_id)} does not support Minecraft {self.minecraft_version}.")
        if self.loader not in (version.get("loaders") or []):
            raise AddonError(f"{version.get('name', project_id)} does not support the {self.loader.title()} loader.")
        if version.get("environment", version.get("server_side", "unknown")) not in SERVER_ENVIRONMENTS:
            raise AddonError(f"{version.get('name', project_id)} is not designed for a server.")
        _primary_file(version)

    def _resolve_graph(self, projects, pinned: dict[str, str] | None = None) -> dict[str, dict]:
        pinned = pinned or {}
        roots = []
        root_versions: dict[str, str] = {}
        for project in projects:
            supplied = str(project)
            info = self.client.project(supplied)
            canonical = str(info.get("id") or supplied)
            if canonical not in roots:
                roots.append(canonical)
            selected = pinned.get(supplied) or pinned.get(canonical)
            if selected:
                root_versions[canonical] = selected
        nodes: dict[str, dict] = {}
        visiting: set[str] = set()

        def resolve(project_id: str, parent: str | None = None, forced_version: str | None = None):
            project_id = str(project_id)
            if project_id in visiting:
                raise AddonError("Modrinth returned a circular required-dependency chain.")
            if project_id in nodes:
                if forced_version and nodes[project_id]["version"].get("id") != forced_version:
                    raise AddonError("Two required dependencies need conflicting versions of the same project.")
                if parent:
                    nodes[project_id]["required_by"].add(parent)
                return
            visiting.add(project_id)
            version_id = forced_version or pinned.get(project_id)
            version = self.client.version(version_id) if version_id else self.client.resolve_version(project_id, self.minecraft_version, self.loader)
            actual_project = str(version.get("project_id", project_id))
            if actual_project != project_id:
                raise AddonError("Modrinth returned a version for the wrong dependency project.")
            self._validate_version(project_id, version)
            node = {"project_id": project_id, "version": version, "required_by": set([parent]) if parent else set(), "dependencies": []}
            nodes[project_id] = node
            for dependency in version.get("dependencies") or []:
                if dependency.get("dependency_type") != "required":
                    continue
                dep_project = dependency.get("project_id")
                dep_version = dependency.get("version_id")
                if not dep_project and dep_version:
                    dep = self.client.version(str(dep_version)); dep_project = dep.get("project_id")
                if not dep_project:
                    raise AddonError(f"{version.get('name', project_id)} has a required external dependency Easy Realms cannot install automatically.")
                dep_project = str(dep_project)
                node["dependencies"].append(dep_project)
                resolve(dep_project, project_id, str(dep_version) if dep_version else None)
            visiting.remove(project_id)

        for root in roots:
            resolve(root, forced_version=root_versions.get(root))
        for node in nodes.values():
            node["is_dependency"] = node["project_id"] not in roots
        return nodes

    def preview_many(self, projects, pinned: dict[str, str] | None = None) -> list[dict]:
        graph = self._resolve_graph(projects, pinned)
        result = []
        for project_id, node in graph.items():
            project = self.client.project(project_id)
            version = node["version"]
            environment = version.get("environment", version.get("server_side", "unknown"))
            result.append({
                "project_id": project_id,
                "name": project.get("title") or version.get("name") or project_id,
                "version_id": version.get("id"),
                "version_number": version.get("version_number", "unknown"),
                "environment": environment,
                "client_requirement": client_requirement(environment),
                "is_dependency": node["is_dependency"],
            })
        return result

    def preview(self, project_id: str, version_id: str | None = None) -> list[dict]:
        return self.preview_many([project_id], {str(project_id): version_id} if version_id else None)

    def install(self, project_id: str, version_id: str | None = None) -> list[dict]:
        return self.install_many([project_id], {str(project_id): version_id} if version_id else None)

    def install_many(self, projects, pinned: dict[str, str] | None = None) -> list[dict]:
        graph = self._resolve_graph(projects, pinned)
        roots = [project_id for project_id,node in graph.items() if not node["is_dependency"]]
        metadata = self.load(); addons = metadata["addons"]
        self.folder.mkdir(parents=True, exist_ok=True)
        planned_names: dict[str, str] = {}
        projects_info = {project_id: self.client.project(project_id) for project_id in graph}
        for project_id, node in graph.items():
            filename = Path(str(_primary_file(node["version"])["filename"])).name
            if filename.lower() in planned_names and planned_names[filename.lower()] != project_id:
                raise AddonError(f"Two selected add-ons use the same filename: {filename}")
            planned_names[filename.lower()] = project_id
            target = self.folder / filename
            owner = next((pid for pid, item in addons.items() if str(item.get("file", "")).lower() == filename.lower()), None)
            if target.exists() and owner != project_id:
                raise AddonError(f"{filename} already exists but is not managed by Easy Realms. Move it out of {self.folder.name} before installing.")

        staged: dict[str, Path] = {}
        stage_root = Path(tempfile.mkdtemp(prefix=".easyrealms-", dir=self.folder))
        try:
            for project_id, node in graph.items():
                file = _primary_file(node["version"])
                staged[project_id] = self.client.download(file, stage_root / Path(str(file["filename"])).name)
            for project_id, node in graph.items():
                version = node["version"]; source = staged[project_id]; target = self.folder / source.name
                previous = addons.get(project_id, {}).get("file")
                os.replace(source, target)
                if previous and previous != target.name:
                    old = self.folder / Path(str(previous)).name
                    if old != target:
                        old.unlink(missing_ok=True)
                project = projects_info[project_id]
                environment = version.get("environment", version.get("server_side", "unknown"))
                addons[project_id] = {
                    "project_id": project_id,
                    "slug": project.get("slug", project_id),
                    "name": project.get("title") or version.get("name") or project_id,
                    "version_id": version.get("id"),
                    "version_number": version.get("version_number", "unknown"),
                    "file": target.name,
                    "minecraft_version": self.minecraft_version,
                    "loader": self.loader,
                    "environment": environment,
                    "client_requirement": client_requirement(environment),
                    "installed_as_dependency": node["is_dependency"],
                    "required_by": sorted(node["required_by"]),
                    "dependencies": sorted(node["dependencies"]),
                }
            for root in roots:
                if root in addons:
                    addons[root]["installed_as_dependency"] = False
            self._prune_orphans(metadata)
            self._save(metadata)
            return [addons[project_id] for project_id in graph if project_id in addons]
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)

    def update(self, project_id: str) -> list[dict]:
        item = self.load()["addons"].get(str(project_id))
        if not item:
            raise AddonError("That add-on is not managed by Easy Realms.")
        return self.install(str(project_id))

    def remove(self, project_id: str) -> list[str]:
        project_id = str(project_id); metadata = self.load(); addons = metadata["addons"]
        item = addons.get(project_id)
        if not item:
            raise AddonError("That add-on is not managed by Easy Realms.")
        if item.get("installed_as_dependency") and item.get("required_by"):
            raise AddonError("This add-on is required by another managed add-on and cannot be removed by itself.")
        removed = [str(item.get("name", project_id))]
        (self.folder / Path(str(item.get("file", ""))).name).unlink(missing_ok=True)
        addons.pop(project_id, None)
        removed.extend(self._prune_orphans(metadata))
        self._save(metadata)
        return removed

    def _prune_orphans(self, metadata: dict) -> list[str]:
        addons = metadata["addons"]
        removed: list[str] = []
        while True:
            required_by = {project_id: set() for project_id in addons}
            for parent, item in addons.items():
                for dependency in item.get("dependencies") or []:
                    if dependency in required_by:
                        required_by[dependency].add(parent)
            orphan = next((project_id for project_id, item in addons.items() if item.get("installed_as_dependency") and not required_by[project_id]), None)
            if orphan is None:
                for project_id, parents in required_by.items():
                    addons[project_id]["required_by"] = sorted(parents)
                return removed
            item = addons.pop(orphan)
            (self.folder / Path(str(item.get("file", ""))).name).unlink(missing_ok=True)
            removed.append(str(item.get("name", orphan)))

    def _save(self, metadata: dict):
        metadata["schema"] = 1
        metadata["minecraft_version"] = self.minecraft_version
        metadata["loader"] = self.loader
        temp = self.manifest.with_suffix(".tmp")
        try:
            temp.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temp, self.manifest)
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise AddonError(f"Could not save {MANIFEST}: {exc}") from exc
