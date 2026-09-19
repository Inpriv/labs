"""JSON-on-disk settings for trns.

Stored at ``%USERPROFILE%\\.trns\\config.json`` (Windows) or
``~/.trns/config.json`` elsewhere. Lives outside the repo so uninstalling the
script doesn't blow away user preferences.

Schema::

    {
      "version": 1,
      "first_run_done": true,
      "path_opt_in": true,        # did the user accept adding trns to PATH?
      "path_dir": "C:\\\\...\\\\..trns",  # remembered so we can undo later
      "source": "en",              # ISO-639-1 or 'auto'
      "target": "pl"
    }
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Optional

CONFIG_DIRNAME = ".trns"
CONFIG_FILENAME = "config.json"
SCHEMA_VERSION = 1

DEFAULT_SOURCE = "en"
DEFAULT_TARGET = "pl"


@dataclass
class Config:
    version: int = SCHEMA_VERSION
    first_run_done: bool = False
    path_opt_in: bool = False
    path_dir: Optional[str] = None
    source: str = DEFAULT_SOURCE
    target: str = DEFAULT_TARGET

    # --- paths --------------------------------------------------------

    @staticmethod
    def config_dir() -> str:
        """Return the absolute config directory, creating it on first use."""
        base = os.environ.get("TRNS_HOME")
        if base:
            d = os.path.join(base, CONFIG_DIRNAME)
        else:
            d = os.path.join(os.path.expanduser("~"), CONFIG_DIRNAME)
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def config_path() -> str:
        return os.path.join(Config.config_dir(), CONFIG_FILENAME)

    # --- persistence --------------------------------------------------

    @classmethod
    def load(cls) -> "Config":
        """Load from disk; if missing/corrupt, return defaults (no raise)."""
        path = cls.config_path()
        if not os.path.isfile(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            # Corrupt or unreadable — start fresh but keep the file around
            # so the user can recover it manually if they care.
            return cls()
        if not isinstance(raw, dict):
            return cls()
        # Forward-compatible: only copy known fields, ignore unknowns.
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: raw[k] for k in known if k in raw}
        clean.setdefault("version", SCHEMA_VERSION)
        try:
            return cls(**clean)
        except TypeError:
            return cls()

    def save(self) -> None:
        path = self.config_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)


# ---------------------------------------------------------------------------
# PATH manipulation (Windows-only).
# ---------------------------------------------------------------------------


def _windows_path_lib():
    """Lazy import winreg so non-Windows platforms can still import this module."""
    if sys.platform != "win32":
        return None
    try:
        import winreg  # noqa: F401  (local import is intentional)
        return winreg
    except ImportError:
        return None


def current_user_path() -> str:
    """Read the user PATH environment variable as a single string."""
    if sys.platform != "win32":
        return os.environ.get("PATH", "")
    winreg = _windows_path_lib()
    if winreg is None:
        return os.environ.get("PATH", "")
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
        ) as k:
            value, _ = winreg.QueryValueEx(k, "Path")
            return value or ""
    except OSError:
        return ""


def _set_user_path(new_path: str) -> None:
    """Write a new PATH to HKCU\\Environment and broadcast WM_SETTINGCHANGE."""
    if sys.platform != "win32":
        os.environ["PATH"] = new_path
        return
    winreg = _windows_path_lib()
    if winreg is None:
        os.environ["PATH"] = new_path
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
        winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
    # Let new shells see the change immediately (best-effort).
    try:
        import ctypes
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x001A, 0, "Environment")
    except Exception:
        pass


def path_contains(directory: str) -> bool:
    """True if `directory` appears (case-insensitively on Windows) in user PATH."""
    target = os.path.normcase(os.path.abspath(directory))
    parts = current_user_path().split(os.pathsep)
    for p in parts:
        if not p:
            continue
        if os.path.normcase(os.path.abspath(p)) == target:
            return True
    return False


def add_to_path(directory: str) -> bool:
    """Append `directory` to user PATH. Returns True if a change was made."""
    directory = os.path.abspath(directory)
    if path_contains(directory):
        return False
    current = current_user_path()
    new = (current + os.pathsep + directory) if current else directory
    _set_user_path(new)
    return True


def remove_from_path(directory: str) -> bool:
    """Remove `directory` from user PATH. Returns True if a change was made."""
    directory_abs = os.path.normcase(os.path.abspath(directory))
    current = current_user_path()
    parts = [p for p in current.split(os.pathsep) if p]
    new_parts: list[str] = []
    changed = False
    for p in parts:
        try:
            if os.path.normcase(os.path.abspath(p)) == directory_abs:
                changed = True
                continue
        except OSError:
            pass
        new_parts.append(p)
    if not changed:
        return False
    _set_user_path(os.pathsep.join(new_parts))
    return True


__all__ = [
    "Config",
    "add_to_path",
    "remove_from_path",
    "path_contains",
    "current_user_path",
    "DEFAULT_SOURCE",
    "DEFAULT_TARGET",
]
