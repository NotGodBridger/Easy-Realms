"""Local, privacy-conscious diagnostics for Easy Realms.

Every application session gets its own log in ``data/logs``.  Logs are never
uploaded by this module.  A session that ends normally receives an explicit
footer; if the process is killed or crashes, the incomplete file is retained
for the next troubleshooting session.
"""
from __future__ import annotations

import atexit
from datetime import datetime, timezone
import faulthandler
import logging
import os
from pathlib import Path
import platform
import re
import sys
import threading
import time
import zipfile


MAX_LOG_FILES = 30
SUPPORT_LOG_FILES = 5
SUPPORT_LOG_BYTES = 1024 * 1024
_session: "DiagnosticSession | None" = None


def _scrub_support_text(value: str, data_dir: Path) -> str:
    """Remove common personal identifiers and secrets from exported diagnostics."""
    text = str(value).replace(str(Path(data_dir).resolve()), "<DATA>")
    home = str(Path.home())
    if home:
        text = text.replace(home, "<HOME>")
    substitutions = (
        (r"(?i)\b[A-Z]:\\Users\\[^\\\r\n]+", "<USER_HOME>"),
        (r"(?i)(?<![A-Za-z0-9])/(?:home|Users)/[^/\s]+", "<USER_HOME>"),
        (r"(?i)https://playit\.gg/claim/[A-Za-z0-9_-]+(?:\?[^\s]*)?", "<PLAYIT_CLAIM>"),
        (r"(?i)\b[A-Za-z0-9.-]+\.playit\.gg(?::\d{1,5})?\b", "<TUNNEL_ADDRESS>"),
        (r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "<EMAIL>"),
        (r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\w.])", "<IP_ADDRESS>"),
        (r"(?i)([?&](?:token|key|secret|code)=)[^&\s]+", r"\1<REDACTED>"),
        (r"(?i)\b((?:password|token|secret|api[-_ ]?key|authorization)\s*[:=]\s*)[^\s,;]+", r"\1<REDACTED>"),
        (r"(?im)^(\s*(?:password|token|secret|contact|api[-_ ]?key|authorization)\s*[:=]\s*).+$", r"\1<REDACTED>"),
        (r"(?m)^Easy Realms Server Doctor — .+$", "Easy Realms Server Doctor — <SERVER>"),
    )
    for pattern, replacement in substitutions:
        text = re.sub(pattern, replacement, text)
    return text


def _support_log_text(path: Path, data_dir: Path) -> str:
    with path.open("rb") as stream:
        size = path.stat().st_size
        if size > SUPPORT_LOG_BYTES:
            stream.seek(size - SUPPORT_LOG_BYTES)
        content = stream.read(SUPPORT_LOG_BYTES).decode("utf-8", errors="replace")
    if size > SUPPORT_LOG_BYTES:
        content = "[Earlier content omitted by Easy Realms]\n" + content
    return _scrub_support_text(content, data_dir)


def _safe_support_source(path: Path, data_dir: Path) -> bool:
    """Accept only ordinary files directly inside data or data/logs."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        resolved = path.resolve(strict=True)
        allowed = {data_dir.resolve(), (data_dir / "logs").resolve()}
        return resolved.parent in allowed
    except OSError:
        return False


def create_support_bundle(data_dir: Path, destination: Path, version: str, doctor_report: str = "") -> Path:
    """Create a local, redacted troubleshooting ZIP without uploading anything."""
    data_dir = Path(data_dir).expanduser().resolve()
    destination = Path(destination).expanduser()
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    logs = data_dir / "logs"
    candidates = []
    if logs.is_dir():
        candidates.extend(logs.glob("easy-realms-*.log"))
        for name in ("launcher-last.log", "setup.log"):
            path = logs / name
            if path.is_file():
                candidates.append(path)
    candidates.extend(path for path in (data_dir / "app.log", data_dir / "app-error.log") if path.is_file())
    candidates = [path for path in set(candidates) if _safe_support_source(path, data_dir)]
    candidates = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[:SUPPORT_LOG_FILES]
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    readme = (
        "Easy Realms privacy-scrubbed support bundle\n\n"
        "This ZIP was created locally and was not uploaded. It contains basic runtime details, "
        "up to five recent Easy Realms diagnostic logs and an optional Server Doctor report.\n\n"
        "It deliberately excludes worlds, server console output, settings.ini, servers.json, "
        "server.properties, player lists, add-ons, backups, Java runtimes and Playit account data.\n"
        "Common home paths, email addresses, IP addresses, Playit addresses and secret-like values "
        "were replaced. Review the files before sharing them.\n"
    )
    system = (
        f"Easy Realms version: {version}\n"
        f"Created (UTC): {created}\n"
        f"Operating system: {platform.system()} {platform.release()}\n"
        f"Architecture: {platform.machine()}\n"
        f"Python: {platform.python_version()}\n"
        f"Included diagnostic logs: {len(candidates)}\n"
    )
    try:
        temporary.unlink(missing_ok=True)
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("README.txt", readme)
            archive.writestr("system.txt", system)
            if doctor_report.strip():
                archive.writestr("server-doctor.txt", _scrub_support_text(doctor_report, data_dir))
            used_names = set()
            for index, path in enumerate(candidates, 1):
                safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name)
                if safe_name in used_names:
                    safe_name = f"{index}-{safe_name}"
                used_names.add(safe_name)
                archive.writestr("logs/" + safe_name, _support_log_text(path, data_dir))
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def application_data_dir() -> Path:
    """Return the same writable data directory used by the main application."""
    configured = os.environ.get("EASY_REALMS_DATA")
    return Path(configured) if configured else Path(__file__).resolve().parent / "data"


def _has_clean_footer(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 4096))
            return b"SESSION END status=clean" in stream.read()
    except OSError:
        return False


def _prune_logs(log_dir: Path, keep: int = MAX_LOG_FILES) -> None:
    files = sorted(
        log_dir.glob("easy-realms-*.log"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    for old_log in files[max(0, keep):]:
        try:
            old_log.unlink()
        except OSError:
            pass


class DiagnosticSession:
    """Own one launch log and the exception hooks that write to it."""

    def __init__(self, version: str, data_dir: Path | None = None, keep: int = MAX_LOG_FILES):
        self.version = version
        self.data_dir = Path(data_dir) if data_dir is not None else application_data_dir()
        self.log_dir = self.data_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        previous_logs = sorted(self.log_dir.glob("easy-realms-*.log"), key=lambda path: path.stat().st_mtime)
        self.previous_unclean = previous_logs[-1] if previous_logs and not _has_clean_footer(previous_logs[-1]) else None
        _prune_logs(self.log_dir, max(0, keep - 1))

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        self.path = self.log_dir / f"easy-realms-{stamp}-{os.getpid()}.log"
        self.logger = logging.getLogger(f"easy_realms.session.{os.getpid()}.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.handler = logging.FileHandler(self.path, mode="a", encoding="utf-8", delay=False)
        formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        self.handler.setFormatter(formatter)
        self.logger.addHandler(self.handler)

        self._finished = False
        self._fault_handler_enabled = False
        self._old_sys_hook = sys.excepthook
        self._old_thread_hook = getattr(threading, "excepthook", None)
        self._old_unraisable_hook = getattr(sys, "unraisablehook", None)
        self._install_exception_hooks()
        try:
            faulthandler.enable(file=self.handler.stream, all_threads=True)
            self._fault_handler_enabled = True
        except (OSError, RuntimeError, AttributeError):
            pass

        self.logger.info("SESSION START Easy Realms %s", version)
        self.logger.info("Runtime Python %s; %s %s", platform.python_version(), platform.system(), platform.machine())
        if self.previous_unclean is not None:
            self.logger.warning("The previous session did not record a clean shutdown; its log was kept as %s", self.previous_unclean.name)

    def _install_exception_hooks(self) -> None:
        def sys_hook(exc_type, value, traceback):
            self.logger.critical("Unhandled application exception", exc_info=(exc_type, value, traceback))
            self.flush()
            if self._old_sys_hook is not None:
                self._old_sys_hook(exc_type, value, traceback)

        def thread_hook(args):
            self.logger.critical(
                "Unhandled thread exception in %s",
                getattr(args.thread, "name", "unknown thread"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            self.flush()
            if self._old_thread_hook is not None:
                self._old_thread_hook(args)

        def unraisable_hook(args):
            self.logger.error(
                "Unraisable application exception",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            self.flush()
            if self._old_unraisable_hook is not None:
                self._old_unraisable_hook(args)

        self._sys_hook = sys_hook
        self._thread_hook = thread_hook
        self._unraisable_hook = unraisable_hook
        sys.excepthook = sys_hook
        if hasattr(threading, "excepthook"):
            threading.excepthook = thread_hook
        if hasattr(sys, "unraisablehook"):
            sys.unraisablehook = unraisable_hook

    def install_qt_handler(self, installer) -> None:
        """Record Qt warnings and failures without storing application data."""
        levels = {0: logging.DEBUG, 1: logging.WARNING, 2: logging.ERROR, 3: logging.CRITICAL, 4: logging.INFO}

        def qt_handler(message_type, context, message):
            try:
                value = int(message_type.value)
            except (AttributeError, TypeError, ValueError):
                try:
                    value = int(message_type)
                except (TypeError, ValueError):
                    value = 1
            self.logger.log(levels.get(value, logging.WARNING), "Qt: %s", message)
            if value >= 2:
                self.flush()

        self._qt_handler = qt_handler
        installer(qt_handler)

    def exception(self, context: str, error: BaseException) -> None:
        self.logger.error(
            "%s: %s",
            context,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )
        self.flush()

    def warning(self, message: str, *args) -> None:
        self.logger.warning(message, *args)
        self.flush()

    def info(self, message: str, *args) -> None:
        self.logger.info(message, *args)

    def flush(self) -> None:
        try:
            self.handler.flush()
        except (OSError, ValueError):
            pass

    def finish(self, exit_code: int = 0) -> None:
        if self._finished:
            return
        self._finished = True
        self.logger.info("SESSION END status=clean exit_code=%s", exit_code)
        self.flush()
        if self._fault_handler_enabled:
            try:
                faulthandler.disable()
            except RuntimeError:
                pass
        if sys.excepthook is self._sys_hook:
            sys.excepthook = self._old_sys_hook
        if hasattr(threading, "excepthook") and threading.excepthook is self._thread_hook:
            threading.excepthook = self._old_thread_hook
        if hasattr(sys, "unraisablehook") and sys.unraisablehook is self._unraisable_hook:
            sys.unraisablehook = self._old_unraisable_hook
        self.logger.removeHandler(self.handler)
        self.handler.close()


def start_diagnostics(version: str) -> DiagnosticSession:
    global _session
    if _session is None:
        _session = DiagnosticSession(version)
        atexit.register(_session.finish)
    return _session


def log_exception(context: str, error: BaseException) -> None:
    if _session is not None:
        _session.exception(context, error)


def log_warning(message: str, *args) -> None:
    if _session is not None:
        _session.warning(message, *args)


def finish_diagnostics(exit_code: int = 0) -> None:
    if _session is not None:
        _session.finish(exit_code)
