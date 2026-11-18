"""Safe integration helpers for the separately installed Playit agent.

Easy Realms never reads or stores Playit's secret file.  Account approval stays
inside the user's browser and Playit's own signed agent.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit


PLAYIT_DOWNLOAD_URL = "https://playit.gg/download/windows"
PLAYIT_DASHBOARD_URL = "https://playit.gg/account/tunnels"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class PlayitStatus:
    installed: bool
    running: bool
    message: str
    executable: str = ""


@dataclass(frozen=True)
class TunnelTarget:
    tunnel_type: str
    local_host: str
    local_port: int
    note: str

    @property
    def local_address(self) -> str:
        return f"{self.local_host}:{self.local_port}"


def _candidate_paths() -> list[Path]:
    candidates = []
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = os.environ.get(variable)
        if not root:
            continue
        base = Path(root)
        candidates.extend(
            [
                base / "playit_gg" / "bin" / "playit.exe",
                base / "playit_gg" / "playit.exe",
                base / "playit" / "playit.exe",
                base / "playit.gg" / "playit.exe",
            ]
        )
    for command in ("playit", "playit.exe"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    return candidates


def _inside_windows_program_files(path: Path) -> bool:
    """Require the machine-protected install area on Windows.

    The official installer is machine scoped.  Refusing user-writable PATH and
    Downloads copies prevents executable-name/path hijacking.  People using a
    standalone Playit binary can still run it themselves outside Easy Realms.
    """

    if os.name != "nt":
        return True
    candidate = os.path.normcase(str(path))
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = os.environ.get(variable)
        if not root:
            continue
        protected = os.path.normcase(str(Path(root).resolve()))
        try:
            if os.path.commonpath((candidate, protected)) == protected:
                return True
        except ValueError:
            continue
    return False


def find_playit_executable(candidates=None, *, require_protected=None) -> Path | None:
    """Find the installed Playit CLI without trusting a user-writable PATH."""

    allowed_names = {"playit", "playit.exe"}
    if require_protected is None:
        require_protected = os.name == "nt"
    source = _candidate_paths() if candidates is None else candidates
    for candidate in source:
        path = Path(candidate).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if (
            resolved.is_file()
            and resolved.name.lower() in allowed_names
            and (not require_protected or _inside_windows_program_files(resolved))
        ):
            return resolved
    return None


def claim_url_from_output(output: str) -> str:
    """Validate a complete Playit claim URL token.

    Easy Realms no longer opens dynamic claim links—the official installed
    Playit command does that itself.  This strict parser remains covered by
    tests as defence-in-depth for any future UI use.
    """

    for token in output.split():
        candidate = token.strip("<>()[]{}\"',.;")
        parsed = urlsplit(candidate)
        if (
            parsed.scheme == "https"
            and parsed.netloc == "playit.gg"
            and not parsed.query
            and not parsed.fragment
            and len(parsed.path) == len("/claim/") + 10
            and parsed.path.startswith("/claim/")
            and all(character in "0123456789abcdefABCDEF" for character in parsed.path[7:])
        ):
            return candidate
    return ""


def tunnel_target(kind: str, properties: dict) -> TunnelTarget:
    default_port = 19132 if kind == "Bedrock" else 25565
    try:
        port = int(properties.get("server-port", default_port))
    except (TypeError, ValueError) as exc:
        raise ValueError("The selected server port is not a number.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("The selected server port must be between 1 and 65535.")

    if kind == "Bedrock":
        return TunnelTarget(
            "Minecraft Bedrock (NetherNet)",
            "127.0.0.1",
            port,
            "Use Playit's current Bedrock NetherNet setup help. Keep any private token in Playit/WaterdogPE only.",
        )
    return TunnelTarget(
        "Minecraft Java",
        "127.0.0.1",
        port,
        "Leave Proxy Protocol off unless you deliberately configure matching server support.",
    )


def check_playit_status(executable: Path | None = None) -> PlayitStatus:
    if executable is not None:
        try:
            executable = Path(executable).resolve(strict=True)
        except OSError:
            executable = None
        if executable is not None and os.name == "nt" and (
            executable.name.lower() != "playit.exe" or not _inside_windows_program_files(executable)
        ):
            executable = None
    else:
        executable = find_playit_executable()
    if executable is None:
        return PlayitStatus(
            False,
            False,
            "No machine-installed Playit command was found. Install it using Playit's official Windows installer.",
        )
    try:
        result = subprocess.run(
            [str(executable), "status"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return PlayitStatus(True, False, "Playit is installed, but its service did not answer.", str(executable))

    if result.returncode == 0:
        return PlayitStatus(True, True, "Playit is installed and its background service is responding.", str(executable))
    return PlayitStatus(True, False, "Playit is installed but is not connected yet. Choose Connect Playit.", str(executable))
