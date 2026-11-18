"""Local server library, common properties and recoverable backups."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import zipfile


@dataclass
class ServerEntry:
    id: str
    name: str
    path: str
    kind: str = "Vanilla"
    version: str = "Unknown"


class ServerLibrary:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.data_dir / "servers.json"

    def all(self):
        if not self.file.is_file():
            return []
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
            entries = [ServerEntry(**item) for item in raw if Path(item["path"]).is_dir()]
        except (OSError, ValueError, TypeError, KeyError):
            return []
        return entries

    def _save(self, entries):
        payload = json.dumps([asdict(item) for item in entries], indent=2)
        temp = self.file.with_suffix(".tmp")
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, self.file)

    def add(self, folder):
        path = Path(folder).expanduser().resolve()
        info = inspect_server(path)
        entries = self.all()
        existing = next((item for item in entries if Path(item.path) == path), None)
        if existing:
            existing.name, existing.kind, existing.version = info["name"], info["kind"], info["version"]
            entry = existing
        else:
            entry = ServerEntry(uuid.uuid4().hex, info["name"], str(path), info["kind"], info["version"])
            entries.append(entry)
        self._save(entries)
        return entry

    def remove(self, entry_id):
        entries = [item for item in self.all() if item.id != entry_id]
        self._save(entries)


def inspect_server(folder):
    path = Path(folder).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("That server folder does not exist.")
    metadata = path / "easyservers.json"
    config = {}
    if metadata.is_file():
        try:
            config = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("This server's Easy Realms information is damaged.")
    jars = list(path.glob("*.jar"))
    markers = [metadata, path / "server.properties", path / "eula.txt", path / "bedrock_server.exe", path / "bedrock_server"]
    if not jars and not any(marker.is_file() for marker in markers):
        raise ValueError("Choose the folder containing server.jar or server.properties.")
    names = " ".join(jar.name.lower() for jar in jars)
    if config.get("kind") in {"Vanilla", "Fabric", "Paper", "Bedrock"}:
        kind = config["kind"]
    elif (path / "bedrock_server.exe").is_file() or (path / "bedrock_server").is_file():
        kind = "Bedrock"
    elif (path / "mods").is_dir() or "fabric" in names:
        kind = "Fabric"
    elif (path / "plugins").is_dir() or "paper" in names:
        kind = "Paper"
    else:
        kind = "Vanilla"
    version = str(config.get("version") or _version_from_jar(jars) or "Unknown")
    return {"name": str(config.get("name") or path.name), "kind": kind, "version": version}


def _version_from_jar(jars):
    preferred = next((jar for jar in jars if jar.name.lower() == "server.jar"), jars[0] if jars else None)
    if not preferred or not zipfile.is_zipfile(preferred):
        return None
    try:
        with zipfile.ZipFile(preferred) as archive:
            if "version.json" in archive.namelist():
                data = json.loads(archive.read("version.json"))
                value = data.get("id") or data.get("name")
                if value and re.fullmatch(r"[0-9A-Za-z._+-]+", str(value)):
                    return str(value)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        pass
    return None


DEFAULT_PROPERTIES = {
    "motd": "An Easy Realms Minecraft server",
    "gamemode": "survival",
    "difficulty": "easy",
    "max-players": "20",
    "server-port": "25565",
    "online-mode": "true",
    "white-list": "false",
    "view-distance": "8",
    "simulation-distance": "8",
    "pvp": "true",
    "server-name": "Easy Realms Bedrock Server",
    "allow-list": "false",
    "tick-distance": "4",
    "transport": "nethernet",
}


def read_properties(folder):
    result = dict(DEFAULT_PROPERTIES)
    file = Path(folder) / "server.properties"
    if not file.is_file():
        return result
    for raw in file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def update_properties(folder, changes):
    _validate_properties(changes)
    file = Path(folder) / "server.properties"
    lines = file.read_text(encoding="utf-8", errors="replace").splitlines() if file.is_file() else []
    remaining = {str(key): str(value) for key, value in changes.items()}
    output = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    if output and output[-1] != "":
        output.append("")
    output.extend(f"{key}={value}" for key, value in remaining.items())
    temp = file.with_suffix(".tmp")
    temp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(temp, file)


def _validate_properties(changes):
    numeric = {"max-players": (1, 1000), "server-port": (1, 65535), "server-portv6": (1, 65535), "view-distance": (2, 32), "simulation-distance": (2, 32), "tick-distance": (4, 12)}
    for key, (low, high) in numeric.items():
        if key in changes:
            try:
                value = int(changes[key])
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a number.")
            if not low <= value <= high:
                raise ValueError(f"{key} must be between {low} and {high}.")
    if "motd" in changes and ("\n" in str(changes["motd"]) or "\r" in str(changes["motd"])):
        raise ValueError("The server description must be one line.")
    if "server-name" in changes and (";" in str(changes["server-name"]) or "\n" in str(changes["server-name"]) or "\r" in str(changes["server-name"])):
        raise ValueError("The Bedrock server name must be one line and cannot contain a semicolon.")


class BackupStore:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "backups"
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, entry):
        result = self.root / entry.id
        result.mkdir(parents=True, exist_ok=True)
        return result

    def list(self, entry):
        return sorted(self.folder(entry).glob("*.zip"), reverse=True)

    def create(self, entry, progress=None, automatic=False):
        source = Path(entry.path)
        if not source.is_dir():
            raise ValueError("The server folder is missing.")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%f")
        target = self.folder(entry) / f"{'auto-' if automatic else ''}{stamp}.zip"
        temp = target.with_suffix(".tmp")
        files = [item for item in source.rglob("*") if item.is_file() and "logs" not in item.relative_to(source).parts and "backups" not in item.relative_to(source).parts]
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for index, item in enumerate(files, 1):
                archive.write(item, item.relative_to(source))
                if progress:
                    progress(int(index * 100 / max(1, len(files))), f"Backing up {item.name}…")
        os.replace(temp, target)
        return target

    def prune(self, entry, keep=5, automatic_only=False):
        keep = int(keep)
        if not 1 <= keep <= 100:
            raise ValueError("Backup retention must be between 1 and 100.")
        removed = []
        candidates = [item for item in self.list(entry) if not automatic_only or item.name.startswith("auto-")]
        for archive in candidates[keep:]:
            archive.unlink(missing_ok=True)
            removed.append(archive)
        return removed

    def restore(self, entry, archive):
        source = Path(entry.path)
        archive = Path(archive)
        if archive.parent != self.folder(entry) or not archive.is_file():
            raise ValueError("Choose a backup created for this server.")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S-%f")
        stage = Path(tempfile.mkdtemp(prefix=".easyrealms-restore-", dir=source.parent))
        recovery = source.with_name(source.name + f".before-restore-{stamp}")
        try:
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.infolist():
                    destination = (stage / member.filename).resolve()
                    if stage.resolve() not in destination.parents and destination != stage.resolve():
                        raise ValueError("The backup contains an unsafe file path.")
                zipped.extractall(stage)
            os.replace(source, recovery)
            try:
                os.replace(stage, source)
            except Exception:
                os.replace(recovery, source)
                raise
            return recovery
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
