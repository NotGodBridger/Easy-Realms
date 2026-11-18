"""Edition-aware, read-only checks used by Easy Realms Server Doctor."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import zipfile

from server_manager import read_properties


@dataclass(frozen=True)
class HealthCheck:
    level: str
    title: str
    detail: str


def _check(level, title, detail):
    return HealthCheck(level, title, detail)


def _safe_file(folder, configured, label):
    root = folder.resolve()
    candidate = (root / str(configured)).resolve()
    if candidate != root and root not in candidate.parents:
        return None, _check("error", label, "The configured path points outside the server folder.")
    if not candidate.is_file():
        return candidate, _check("error", label, f"Missing file: {candidate.name}")
    return candidate, _check("pass", label, candidate.name)


def check_server(folder, config=None):
    """Return checks without changing the server or starting any process."""
    path = Path(folder).expanduser().resolve()
    checks = []
    if not path.is_dir():
        return [_check("error", "Server folder", "The server folder no longer exists.")]
    checks.append(_check("pass", "Server folder", str(path)))

    if config is None:
        metadata = path / "easyservers.json"
        try:
            config = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return checks + [_check("error", "Easy Realms information", "easyservers.json is missing or damaged.")]
    kind = str(config.get("kind", ""))
    if kind not in {"Vanilla", "Fabric", "Paper", "Bedrock"}:
        checks.append(_check("error", "Server edition", "The server type is missing or unsupported."))
    else:
        checks.append(_check("pass", "Server edition", kind))

    properties = read_properties(path)
    try:
        port = int(properties.get("server-port", 19132 if kind == "Bedrock" else 25565))
        if not 1 <= port <= 65535:
            raise ValueError
        checks.append(_check("pass", "Server port", str(port)))
    except (TypeError, ValueError):
        checks.append(_check("error", "Server port", "Use a number from 1 to 65535 in server.properties."))

    if kind == "Bedrock":
        executable, result = _safe_file(path, config.get("executable", "bedrock_server.exe"), "Bedrock program")
        checks.append(result)
        if properties.get("transport", "nethernet").strip().lower() == "nethernet":
            checks.append(_check("pass", "Bedrock transport", "NetherNet"))
        else:
            checks.append(_check("warning", "Bedrock transport", "This server is using legacy RakNet."))
    else:
        jar, result = _safe_file(path, config.get("jar", "server.jar"), "Server JAR")
        checks.append(result)
        if jar and jar.is_file() and not zipfile.is_zipfile(jar):
            checks.append(_check("error", "Server JAR integrity", "The configured JAR is not a valid Java archive."))
        elif jar and jar.is_file():
            checks.append(_check("pass", "Server JAR integrity", "Java archive structure looks valid."))
        java = str(config.get("java", "java")).strip()
        resolved = shutil.which(java) if java and not Path(java).is_absolute() and "/" not in java and "\\" not in java else java
        if resolved and Path(resolved).is_file():
            checks.append(_check("pass", "Java runtime", str(resolved)))
        else:
            checks.append(_check("error", "Java runtime", "The configured Java program could not be found."))
        try:
            ram = int(config.get("ram", 4))
            if not 1 <= ram <= 128:
                raise ValueError
            checks.append(_check("pass", "Memory allocation", f"{ram} GB"))
        except (TypeError, ValueError):
            checks.append(_check("error", "Memory allocation", "Choose between 1 GB and 128 GB."))

    if properties.get("online-mode", "true").strip().lower() == "true":
        checks.append(_check("pass", "Account authentication", "Only authenticated Minecraft accounts can join."))
    else:
        checks.append(_check("warning", "Account authentication", "online-mode is off. Do not expose this server publicly unless you understand the impersonation risk."))
    list_key = "allow-list" if kind == "Bedrock" else "white-list"
    if properties.get(list_key, "false").strip().lower() == "true":
        checks.append(_check("pass", "Player access list", "Only approved players can join."))
    else:
        checks.append(_check("warning", "Player access list", "No allow-list is enabled. Anyone with the public address may try to join."))

    try:
        free = shutil.disk_usage(path).free
        if free < 2 * 1024**3:
            checks.append(_check("warning", "Free storage", f"Only {free / 1024**3:.1f} GB remains."))
        else:
            checks.append(_check("pass", "Free storage", f"{free / 1024**3:.1f} GB available."))
    except OSError:
        checks.append(_check("warning", "Free storage", "Easy Realms could not read available storage."))

    if config.get("auto_port_forward"):
        checks.append(_check("warning", "Internet sharing", "Direct UPnP forwarding is enabled. playit.gg is recommended when you do not want to share your home IP."))
    else:
        checks.append(_check("pass", "Internet sharing", "No direct router port will be opened by Easy Realms."))
    return checks


def blocking_issues(checks):
    return [item for item in checks if item.level == "error"]


def format_report(server_name, checks):
    labels = {"pass": "PASS", "warning": "CHECK", "error": "FIX"}
    lines = [f"Easy Realms Server Doctor — {server_name}", ""]
    lines.extend(f"[{labels.get(item.level, item.level.upper())}] {item.title}: {item.detail}" for item in checks)
    errors = len(blocking_issues(checks));warnings = sum(item.level == "warning" for item in checks)
    lines.extend(["", f"Result: {errors} blocking issue(s), {warnings} recommendation(s)."])
    return "\n".join(lines)
