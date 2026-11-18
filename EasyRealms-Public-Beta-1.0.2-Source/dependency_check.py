"""First-launch checks shared by the source and portable launchers."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent
MINIMUM_PYTHON = (3, 11)
MINIMUM_PYSIDE = (6, 8)
MAXIMUM_PYSIDE = (7, 0)
REQUIRED_FILES = (
    'app.py',
    'backend.py',
    'diagnostics.py',
    'legal.py',
    'ui_guidance.py',
    'assets/app-icon.ico',
    'assets/logo.png',
    'assets/MinecraftTen-VGORe.ttf',
    'assets/Minecraft-Seven_v2.ttf',
)


def version_tuple(value: str) -> tuple[int, ...]:
    """Return the numeric release portion of a package version."""
    numbers = re.match(r'^(\d+(?:\.\d+)*)', str(value).strip())
    return tuple(int(part) for part in numbers.group(1).split('.')) if numbers else ()


def check_dependencies() -> list[str]:
    problems: list[str] = []
    if sys.version_info[:2] < MINIMUM_PYTHON:
        problems.append(
            f'Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer is required; '
            f'found {sys.version_info.major}.{sys.version_info.minor}.'
        )
    try:
        pyside = importlib.import_module('PySide6')
        for name in ('QtCore', 'QtGui', 'QtWidgets'):
            importlib.import_module(f'PySide6.{name}')
        installed = version_tuple(getattr(pyside, '__version__', ''))
        if not installed or not (MINIMUM_PYSIDE <= installed < MAXIMUM_PYSIDE):
            shown = getattr(pyside, '__version__', 'unknown')
            problems.append(f'PySide6 6.8 or newer, but lower than 7, is required; found {shown}.')
    except Exception as exc:
        problems.append(f'PySide6 interface components are unavailable: {exc}')
    return problems


def check_files(root: Path = ROOT) -> list[str]:
    return [f'Required application file is missing: {relative}'
            for relative in REQUIRED_FILES if not (root / relative).is_file()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Check Easy Realms first-launch requirements.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--dependencies-only', action='store_true')
    group.add_argument('--files-only', action='store_true')
    options = parser.parse_args(argv)
    problems: list[str] = []
    if not options.files_only:
        problems.extend(check_dependencies())
    if not options.dependencies_only:
        problems.extend(check_files())
    if problems:
        print('Easy Realms dependency check failed:')
        for problem in problems:
            print(f'- {problem}')
        return 1
    print('Easy Realms dependency check: OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
