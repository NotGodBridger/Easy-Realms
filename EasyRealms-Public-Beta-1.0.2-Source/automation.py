from __future__ import annotations

import ctypes
import os
import re
import sys


def total_memory_gb() -> float:
    """Return installed physical memory without adding a third-party dependency."""
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]
        status = MemoryStatus(); status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total_physical / (1024 ** 3)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return pages * page_size / (1024 ** 3)
    except (AttributeError, OSError, ValueError):
        pass
    return 8.0


def recommend_resources(memory_gb: float, kind: str, hosting_and_playing: bool = True) -> dict:
    memory_gb = max(1.0, float(memory_gb))
    reserve = 4 if hosting_and_playing else 2
    usable = max(1, int(memory_gb) - reserve)
    target = {"Vanilla": 4, "Fabric": 6, "Paper": 4}.get(kind, 4)
    ram = max(1, min(target, usable, max(1, int(memory_gb * (0.42 if hosting_and_playing else 0.62)))))
    if memory_gb < 6:
        view, simulation, level = 5, 4, "limited"
    elif memory_gb < 10:
        view, simulation, level = 6, 5, "balanced"
    elif memory_gb < 16:
        view, simulation, level = 8, 6, "balanced"
    elif memory_gb < 24:
        view, simulation, level = 10, 8, "comfortable"
    else:
        view, simulation, level = 12, 10, "comfortable"
    if kind == "Paper":
        view = min(12, view + 1)
    if kind == "Fabric":
        view = max(5, view - 1)
    if kind == "Bedrock":
        ram = 0
        view = min(32, max(8, view * 2))
        simulation = max(4, min(12, simulation))
    warning = ""
    if memory_gb < 8 and hosting_and_playing:
        warning = "This PC may struggle to host and play Minecraft at the same time. Close other apps and keep player counts low."
    return {
        "memory_gb": round(memory_gb, 1),
        "ram_gb": ram,
        "view_distance": view,
        "simulation_distance": simulation,
        "profile": level,
        "warning": warning,
    }


PLAYER_PATTERNS = (
    re.compile(r"There are\s+(\d+)\s+of a max of\s+\d+\s+players online", re.I),
    re.compile(r"There are\s+(\d+)\s+out of a maximum of\s+\d+\s+players online", re.I),
    re.compile(r"There are\s+(\d+)\s*/\s*\d+\s+players online", re.I),
    re.compile(r"players online\s*:\s*(\d+)\s*/\s*\d+", re.I),
)


def parse_player_count(text: str):
    matches = []
    for pattern in PLAYER_PATTERNS:
        matches.extend(int(match.group(1)) for match in pattern.finditer(text))
    return matches[-1] if matches else None


def restart_decision(crash_times, now: float, limit: int = 3, window_seconds: int = 600):
    recent = [float(value) for value in crash_times if now - float(value) < window_seconds]
    allowed = len(recent) < limit
    if allowed:
        recent.append(float(now))
    return allowed, recent
