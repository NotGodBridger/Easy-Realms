"""Safe player access commands and read-only local access-list summaries."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


MAX_ACCESS_FILE = 1024 * 1024
JAVA_NAME = re.compile(r"[A-Za-z0-9_]{3,16}\Z")
BEDROCK_EXTRA = set(" _-.#")


class PlayerAccessError(ValueError):
    pass


@dataclass(frozen=True)
class AccessSnapshot:
    allowed: tuple[str, ...]
    operators: tuple[str, ...]
    note: str = ""


def validate_player_name(kind: str, value: str) -> str:
    """Return a command-safe Java username or Bedrock Gamertag."""

    name = str(value).strip()
    if kind == "Bedrock":
        if not 1 <= len(name) <= 32:
            raise PlayerAccessError("Enter a Bedrock Gamertag between 1 and 32 characters.")
        if name.startswith("@") or any(not (character.isalnum() or character in BEDROCK_EXTRA) for character in name):
            raise PlayerAccessError("Use only letters, numbers, spaces, _, -, . or # in the Bedrock Gamertag.")
        return name
    if not JAVA_NAME.fullmatch(name):
        raise PlayerAccessError("Enter a Java username using 3–16 letters, numbers or underscores.")
    return name


def _command_name(kind: str, name: str) -> str:
    return f'"{name}"' if kind == "Bedrock" and " " in name else name


def player_commands(kind: str, action: str, name: str = "") -> tuple[str, ...]:
    """Build fixed-shape console commands without accepting command syntax."""

    list_command = "allowlist" if kind == "Bedrock" else "whitelist"
    if action == "list":
        return (f"{list_command} list",)
    if action == "enable":
        return (f"{list_command} on",)

    safe_name = validate_player_name(kind, name)
    target = _command_name(kind, safe_name)
    if action == "add":
        return (f"{list_command} on", f"{list_command} add {target}")
    if action == "remove":
        # Revoking operator first avoids leaving elevated permissions behind.
        return (f"deop {target}", f"{list_command} remove {target}")
    if action == "op":
        return (f"op {target}",)
    if action == "deop":
        return (f"deop {target}",)
    raise PlayerAccessError("That player access action is not supported.")


def _read_names(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        return ()
    if path.stat().st_size > MAX_ACCESS_FILE:
        raise PlayerAccessError(f"{path.name} is unexpectedly large, so Easy Realms did not read it.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlayerAccessError(f"{path.name} could not be read safely.") from exc
    if not isinstance(payload, list):
        raise PlayerAccessError(f"{path.name} has an unexpected format.")
    names = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and 1 <= len(name) <= 64 and not any(character in name for character in "\r\n\x00"):
            names.append(name)
    return tuple(sorted(set(names), key=str.casefold))


def load_access_snapshot(folder, kind: str) -> AccessSnapshot:
    """Read the server-owned access files without modifying them."""

    root = Path(folder)
    allowed_file = root / ("allowlist.json" if kind == "Bedrock" else "whitelist.json")
    allowed = _read_names(allowed_file)
    if kind == "Bedrock":
        return AccessSnapshot(
            allowed,
            (),
            "Bedrock operator identities are stored by XUID; use the running server controls below to grant or revoke operator access.",
        )
    return AccessSnapshot(allowed, _read_names(root / "ops.json"))
