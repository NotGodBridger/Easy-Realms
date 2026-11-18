"""Lightweight process monitoring for the Minecraft server process.

Easy Realms ships without psutil, so this module reads the small amount of
information it needs directly from Windows or Linux.  The public
``ProcessMonitor`` class keeps the platform-specific details out of the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import time
from typing import Callable


GIBIBYTE = 1024**3


@dataclass(frozen=True)
class ProcessSample:
    """One display-ready sample from a running server process."""

    cpu_percent: float
    memory_bytes: int
    uptime_seconds: float


def format_memory(byte_count: int) -> str:
    """Format resident memory using the most useful unit for the value."""

    if byte_count >= GIBIBYTE:
        return f"{byte_count / GIBIBYTE:.1f} GB"
    return f"{byte_count / 1024**2:.0f} MB"


def format_uptime(seconds: float) -> str:
    """Format an elapsed duration without noisy seconds after the first minute."""

    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def load_message(cpu_percent: float, memory_bytes: int, memory_limit_gb: int | None) -> str:
    """Return a friendly interpretation of the current load."""

    if cpu_percent >= 90:
        return "CPU usage is very high. Expect lag if it stays here."
    if memory_limit_gb and memory_bytes >= memory_limit_gb * GIBIBYTE * 0.9:
        return "Memory is close to the configured limit."
    if cpu_percent >= 70:
        return "The server is busy, but still within a normal range."
    return "Server load looks healthy."


class ProcessMonitor:
    """Sample CPU, memory and uptime for one process ID."""

    def __init__(
        self,
        reader: Callable[[int], tuple[float, int]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        cpu_count: int | None = None,
    ):
        self._reader = reader or _read_process
        self._clock = clock
        self._cpu_count = max(1, cpu_count or os.cpu_count() or 1)
        self.reset()

    def reset(self, process_id: int | None = None) -> None:
        self.process_id = int(process_id or 0)
        self.started_at = self._clock() if self.process_id else None
        self._last_wall_time = None
        self._last_process_time = None
        if self.process_id:
            self._prime()

    def _prime(self) -> None:
        process_time, _ = self._reader(self.process_id)
        self._last_process_time = process_time
        self._last_wall_time = self._clock()

    def sample(self) -> ProcessSample | None:
        if not self.process_id or self.started_at is None:
            return None

        try:
            process_time, memory_bytes = self._reader(self.process_id)
        except (OSError, ProcessLookupError, ValueError):
            return None

        now = self._clock()
        cpu_percent = 0.0
        if self._last_wall_time is not None and self._last_process_time is not None:
            elapsed = now - self._last_wall_time
            if elapsed > 0:
                used = max(0.0, process_time - self._last_process_time)
                cpu_percent = min(100.0, used / elapsed / self._cpu_count * 100)

        self._last_wall_time = now
        self._last_process_time = process_time
        return ProcessSample(cpu_percent, memory_bytes, now - self.started_at)


def _read_process(process_id: int) -> tuple[float, int]:
    if sys.platform == "win32":
        return _read_windows_process(process_id)
    if sys.platform.startswith("linux"):
        return _read_linux_process(process_id)
    raise OSError("Live process monitoring is not available on this platform")


def _filetime_seconds(value: wintypes.FILETIME) -> float:
    ticks = (value.dwHighDateTime << 32) | value.dwLowDateTime
    return ticks / 10_000_000


def _read_windows_process(process_id: int) -> tuple[float, int]:
    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000 | 0x0010, False, process_id)
    if not handle:
        raise ProcessLookupError(process_id)

    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise OSError(ctypes.get_last_error(), "Could not read process CPU time")

        memory = ProcessMemoryCounters()
        memory.cb = ctypes.sizeof(memory)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
            raise OSError(ctypes.get_last_error(), "Could not read process memory")
        return _filetime_seconds(kernel) + _filetime_seconds(user), int(memory.WorkingSetSize)
    finally:
        kernel32.CloseHandle(handle)


def _read_linux_process(process_id: int) -> tuple[float, int]:
    stat = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
    fields = stat[stat.rfind(")") + 2 :].split()
    clock_ticks = os.sysconf("SC_CLK_TCK")
    page_size = os.sysconf("SC_PAGE_SIZE")
    process_time = (int(fields[11]) + int(fields[12])) / clock_ticks
    resident_memory = int(fields[21]) * page_size
    return process_time, resident_memory
