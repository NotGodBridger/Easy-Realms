"""Safe, same-Minecraft-version server software updates."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import zipfile


@dataclass(frozen=True)
class UpdatePlan:
    kind: str
    minecraft_version: str
    installed_build: str
    available_build: str
    update_available: bool
    managed_build: bool
    spec: dict


@dataclass(frozen=True)
class UpgradePlan:
    kind: str
    current_version: str
    target_version: str
    available_build: str
    addon_roots: tuple[str, ...]
    addon_summary: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    spec: dict

    @property
    def can_upgrade(self):
        return not self.blockers


def _identity(spec):
    return {
        key: spec.get(key)
        for key in ("kind", "version", "detail", "url", "checksum", "algorithm")
    }


def _build_label(spec):
    detail = str(spec.get("detail") or "").strip()
    return detail or str(spec.get("version") or "Unknown build")


def check_update(catalog, config):
    """Resolve the newest build for a server without changing Minecraft versions."""
    kind = str(config.get("kind") or "")
    version = str(config.get("version") or "")
    if kind not in {"Vanilla", "Fabric", "Paper", "Bedrock"}:
        raise ValueError("Easy Realms does not recognise this server type.")
    if not version or version == "Unknown":
        raise ValueError("This imported server has no known Minecraft version. Set up its version before using automatic updates.")
    latest = catalog.resolve(kind, version)
    installed_identity = config.get("installed_build")
    managed = isinstance(installed_identity, dict)
    if managed:
        update_available = installed_identity != _identity(latest)
        installed = _build_label(installed_identity)
    else:
        # Servers created before update tracking can safely adopt the current
        # same-version build after the user confirms and a backup is made.
        update_available = True
        installed = _build_label(config) or "Untracked build"
    return UpdatePlan(
        kind=kind,
        minecraft_version=version,
        installed_build=installed,
        available_build=_build_label(latest),
        update_available=update_available,
        managed_build=managed,
        spec=latest,
    )


def version_key(version):
    """Return a comparison key for release-like Minecraft version labels."""
    text = str(version).removeprefix("Preview ")
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:[-+].*)?", text)
    if not match:
        raise ValueError(f"Minecraft version {version!r} cannot be compared safely.")
    parts = tuple(int(value) for value in match.group(1).split("."))
    return parts + (0,) * (4 - len(parts))


def upgrade_versions(catalog, kind, current_version):
    """List only newer versions on the same stable/Preview channel."""
    current_preview = str(current_version).startswith("Preview ")
    current_key = version_key(current_version)
    result = []
    for version in catalog.versions(kind):
        if str(version).startswith("Preview ") != current_preview:
            continue
        try:
            if version_key(version) > current_key:
                result.append(str(version))
        except ValueError:
            continue
    return result


def check_upgrade(catalog, folder, config, target_version, addon_client=None):
    """Preflight a forward-only Minecraft version change."""
    folder = Path(folder).expanduser().resolve()
    kind = str(config.get("kind") or "")
    current = str(config.get("version") or "")
    target = str(target_version or "")
    if not current or current == "Unknown":
        raise ValueError("This server's current Minecraft version is unknown, so Easy Realms cannot upgrade it safely.")
    if str(current).startswith("Preview ") != target.startswith("Preview "):
        raise ValueError("Stable and Preview Bedrock servers must stay on separate upgrade paths.")
    if version_key(target) <= version_key(current):
        raise ValueError("Choose a Minecraft version newer than the server's current version. Downgrades are blocked.")
    spec = catalog.resolve(kind, target)
    blockers = []
    warnings = ["Minecraft worlds cannot be safely downgraded after they open in a newer version."]
    addon_roots = []
    addon_summary = []
    if kind in {"Fabric", "Paper"}:
        from addons import AddonError, AddonManager, addon_folder_for_kind

        current_manager = AddonManager(folder, kind, current, client=addon_client)
        try:
            installed = current_manager.installed()
        except AddonError as exc:
            blockers.append(str(exc));installed = []
        addon_roots = [str(item.get("project_id")) for item in installed if not item.get("installed_as_dependency")]
        managed_files = {str(item.get("file")) for item in installed if item.get("file")}
        addon_folder = folder / addon_folder_for_kind(kind)
        unmanaged = sorted(item.name for item in addon_folder.glob("*.jar") if item.name not in managed_files) if addon_folder.is_dir() else []
        if unmanaged:
            sample = ", ".join(unmanaged[:4]) + ("…" if len(unmanaged) > 4 else "")
            blockers.append(f"Unmanaged add-ons cannot be compatibility-checked: {sample}")
        if addon_roots and not blockers:
            try:
                target_manager = AddonManager(folder, kind, target, client=addon_client)
                preview = target_manager.preview_many(addon_roots)
                addon_summary = [f"{item['name']} {item['version_number']}" for item in preview if not item["is_dependency"]]
            except AddonError as exc:
                blockers.append(str(exc))
        if not installed and not unmanaged:
            warnings.append("No Easy Realms-managed mods or plugins need migration.")
    return UpgradePlan(
        kind=kind,
        current_version=current,
        target_version=target,
        available_build=_build_label(spec),
        addon_roots=tuple(addon_roots),
        addon_summary=tuple(addon_summary),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        spec=spec,
    )


def _safe_jar_name(config):
    name = str(config.get("jar") or "server.jar")
    if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.jar", name):
        raise ValueError("The configured server JAR name is unsafe. Choose the server again before updating.")
    return name


def _download(catalog, spec, destination, progress, cancel, opener):
    digest = hashlib.new(str(spec.get("algorithm") or "sha256"))
    response_context=catalog.open(spec["url"],timeout=60) if opener is None else opener(catalog.request(spec["url"]),timeout=60)
    with response_context as response, destination.open("wb") as output:
        total = int(response.headers.get("Content-Length", 0))
        received = 0
        while True:
            if cancel.is_set():
                raise ValueError("Update cancelled before any server files were changed.")
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            received += len(chunk)
            percent = min(75, int(received * 75 / total)) if total else 0
            progress(percent, f"Downloaded {received / 1048576:.1f} MB")
        if total and received != total:
            raise ValueError("The server update download was incomplete. No server files were changed.")
    expected = spec.get("checksum")
    if expected and digest.hexdigest().lower() != str(expected).lower():
        raise ValueError("The server update checksum did not match. No server files were changed.")


def _write_config(folder, original, spec):
    config = dict(original)
    # Catalog ``java`` is a required major version, while config ``java`` is
    # the user's executable path. Keep all launch and automation settings and
    # update only catalog-owned build fields.
    for key in ("kind", "version", "detail", "url", "checksum", "algorithm"):
        if key in spec:
            config[key] = spec[key]
    config["installed_build"] = _identity(spec)
    target = folder / "easyservers.json"
    temporary = target.with_suffix(".update.tmp")
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return config


def _install_java(folder, config, spec, downloaded, progress):
    if not zipfile.is_zipfile(downloaded):
        raise ValueError("The downloaded update is not a valid server JAR. No server files were changed.")
    jar = folder / _safe_jar_name(config)
    rollback = folder / ".easyrealms-previous-server.jar"
    staged = folder / ".easyrealms-new-server.jar"
    shutil.copy2(downloaded, staged)
    old_config = (folder / "easyservers.json").read_bytes()
    if jar.is_file():
        shutil.copy2(jar, rollback)
    try:
        os.replace(staged, jar)
        _write_config(folder, config, spec)
    except Exception:
        if rollback.is_file():
            os.replace(rollback, jar)
        (folder / "easyservers.json").write_bytes(old_config)
        staged.unlink(missing_ok=True)
        raise
    progress(100, "Server software updated and previous JAR retained for recovery.")
    return {"rollback_file": str(rollback) if rollback.is_file() else "", "config": _identity(spec)}


_BEDROCK_PRESERVE_FILES = {
    "easyservers.json", "server.properties", "allowlist.json", "whitelist.json",
    "permissions.json", "valid_known_packs.json",
}
_BEDROCK_PRESERVE_FOLDERS = {
    "worlds", "behavior_packs", "resource_packs", "world_templates",
    "development_behavior_packs", "development_resource_packs", "treatments",
}


def _install_bedrock(folder, config, spec, downloaded, progress, temporary_root):
    if not zipfile.is_zipfile(downloaded):
        raise ValueError("The downloaded update is not a valid Bedrock server ZIP. No server files were changed.")
    stage = temporary_root / "bedrock"
    stage.mkdir()
    with zipfile.ZipFile(downloaded) as archive:
        root = stage.resolve()
        for member in archive.infolist():
            destination = (stage / member.filename).resolve()
            if root not in destination.parents and destination != root:
                raise ValueError("The Bedrock update contains an unsafe path. No server files were changed.")
        archive.extractall(stage)
    if not (stage / "bedrock_server.exe").is_file():
        raise ValueError("The Bedrock update does not contain bedrock_server.exe. No server files were changed.")
    old_config = (folder / "easyservers.json").read_bytes()
    copied = []
    try:
        files = [item for item in stage.rglob("*") if item.is_file()]
        for index, source in enumerate(files, 1):
            relative = source.relative_to(stage)
            if relative.name.lower() in _BEDROCK_PRESERVE_FILES:
                continue
            if relative.parts and relative.parts[0].lower() in _BEDROCK_PRESERVE_FOLDERS:
                continue
            destination = folder / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".easyrealms-update")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
            copied.append(destination)
            progress(75 + int(index * 20 / max(1, len(files))), f"Updating {relative.name}…")
        _write_config(folder, config, spec)
    except Exception:
        (folder / "easyservers.json").write_bytes(old_config)
        raise ValueError("The Bedrock update could not finish. Restore the automatic backup before launching.")
    progress(100, "Bedrock server software updated; worlds and settings were preserved.")
    return {"updated_files": len(copied), "config": _identity(spec)}


def install_update(catalog, folder, config, spec, progress=None, cancel=None, opener=None, allow_version_change=False):
    """Download, verify and install an already-confirmed same-version update."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir() or not (folder / "easyservers.json").is_file():
        raise ValueError("The selected server folder is incomplete.")
    kind_changed = str(spec.get("kind")) != str(config.get("kind"))
    version_changed = str(spec.get("version")) != str(config.get("version"))
    if kind_changed or (version_changed and not allow_version_change):
        raise ValueError("Easy Realms refused an update that would change the server type or Minecraft version.")
    if version_changed and version_key(spec.get("version")) <= version_key(config.get("version")):
        raise ValueError("Easy Realms refused a Minecraft downgrade.")
    progress = progress or (lambda *_: None)
    cancel = cancel or threading.Event()
    with tempfile.TemporaryDirectory(prefix=".easyrealms-update-", dir=folder.parent) as temporary_value:
        temporary_root = Path(temporary_value)
        downloaded = temporary_root / ("bedrock.zip" if config.get("kind") == "Bedrock" else "server.jar")
        progress(0, "Downloading the verified server update…")
        _download(catalog, spec, downloaded, progress, cancel, opener)
        if cancel.is_set():
            raise ValueError("Update cancelled before any server files were changed.")
        progress(78, "Download verified. Preparing the server files…")
        if config.get("kind") == "Bedrock":
            return _install_bedrock(folder, config, spec, downloaded, progress, temporary_root)
        return _install_java(folder, config, spec, downloaded, progress)
