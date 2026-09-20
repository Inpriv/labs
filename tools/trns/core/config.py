"""JSON-on-disk settings for trns.

Stored at ``%USERPROFILE%\\.trns\\config.json`` (Windows) or
``~/.trns/config.json`` elsewhere. Lives outside the repo so uninstalling the
script doesn't blow away user preferences.

Schema::

    {
      "version": 1,
      "first_run_done": true,
      "path_opt_in": true,        # did the user accept adding trns to PATH?
      "path_dir": "/home/.../trns",  # remembered so we can undo later
      "source": "en",              # ISO-639-1 or 'auto'
      "target": "pl"
    }
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
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
# PATH manipulation (Windows + POSIX).
#
# Windows uses the HKCU\Environment registry. POSIX shells vary:
#
#   * Linux desktop  -> ~/.bashrc / ~/.zshrc / ~/.profile (whichever exists)
#   * Termux         -> $PREFIX/etc/profile.d/trns.sh (system-wide, survives
#                       app data wipes for the user-script folder)
#
# We always restore the previous value, never blindly append, so /path toggle
# is idempotent.
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
    if sys.platform == "win32":
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
    return os.environ.get("PATH", "")


def _set_user_path(new_path: str) -> None:
    """Persist a new PATH to the OS-native location and notify running shells."""
    if sys.platform == "win32":
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
        return

    # POSIX — update the live env first so the change is observable right away.
    os.environ["PATH"] = new_path
    _persist_posix_path(_last_dir_in_path(new_path))


def path_contains(directory: str) -> bool:
    """True if `directory` appears (case-insensitively on Windows) in user PATH."""
    target = os.path.normcase(os.path.abspath(directory))
    parts = current_user_path().split(os.pathsep)
    for p in parts:
        if not p:
            continue
        try:
            if os.path.normcase(os.path.abspath(p)) == target:
                return True
        except OSError:
            pass
    return False


def _last_dir_in_path(path_string: str) -> str:
    """Return the last non-empty entry of a PATH string — i.e. the one we
    most likely just appended, and the one `remove_from_path` should clean up.
    """
    parts = [p for p in path_string.split(os.pathsep) if p]
    return parts[-1] if parts else ""


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
    """Remove `directory` from user PATH. Returns True if a change was made.

    On POSIX, also strips the ``# >>> trns init >>>`` sentinel block we
    previously wrote to the user's shell rc files.

    Note: a fresh --path-remove process inherits its parent's PATH, which
    does NOT include directories that --path-add pushed into the parent's
    shell rc. So we always scrub the rc file on POSIX (idempotent) and let
    the in-memory PATH update only happen when the directory was actually
    present in this process.
    """
    directory_abs = os.path.normcase(os.path.abspath(directory))
    current = current_user_path()
    parts = [p for p in current.split(os.pathsep) if p]
    new_parts: list[str] = []
    path_changed = False
    for p in parts:
        try:
            if os.path.normcase(os.path.abspath(p)) == directory_abs:
                path_changed = True
                continue
        except OSError:
            pass
        new_parts.append(p)
    if path_changed:
        _set_user_path(os.pathsep.join(new_parts))

    if sys.platform == "win32":
        return path_changed

    # POSIX: scrub the rc file sentinel; it lives outside the process and is
    # the source of truth for the user's PATH on next login.
    rc_changed = _remove_posix_persistence(directory)
    return path_changed or rc_changed


# ---------------------------------------------------------------------------
# POSIX persistence — shell-rc edits with a sentinel block.
# ---------------------------------------------------------------------------

# Sentinel markers wrap our PATH export so re-runs (or /path toggle from the
# REPL) can find and remove the previous line instead of accumulating dupes.
_POSIX_SENTINEL_BEGIN = "# >>> trns init >>>"
_POSIX_SENTINEL_END = "# <<< trns init <<<"

# A POSIX shell PATH line that re-applies our directory if it's missing.
# `case` handles the leading/trailing colon and existing entries robustly.
_POSIX_EXPORT_TEMPLATE = (
    'case ":$PATH:" in\n'
    '  *":{path}":*) ;;\n'
    '  *) export PATH="{path}$PATH" ;;\n'
    'esac'
)

_SENTINEL_RE = re.compile(
    re.escape(_POSIX_SENTINEL_BEGIN) + r".*?" + re.escape(_POSIX_SENTINEL_END) + r"\n?",
    re.DOTALL,
)


def _is_termux() -> bool:
    """True when running inside Termux (Android terminal emulator)."""
    # Termux sets ANDROID_ROOT/PREFIX/data/data/com.termux; checking PREFIX
    # alone is enough — every Termux process has it.
    return bool(os.environ.get("PREFIX", "").startswith("/data/data/com.termux"))


def _termux_profile_d_path() -> str:
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    return os.path.join(prefix, "etc", "profile.d", "trns.sh")


def _termux_profile_d_writable() -> Optional[str]:
    """Return the Termux profile.d script path if the directory exists and
    we have write permission; otherwise None."""
    path = _termux_profile_d_path()
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        return None
    if not os.access(d, os.W_OK):
        return None
    return path


def _posix_rc_files() -> list[str]:
    """Ordered list of POSIX shell rc files to update, filtered by existence.

    Order matters: we prefer the most-login-friendly file first so the export
    is available in both interactive and non-interactive shells.
    """
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".profile"),      # login shells (sh, dash, bash --login)
        os.path.join(home, ".bash_profile"), # bash login, overrides .profile
        os.path.join(home, ".bashrc"),       # bash interactive non-login
        os.path.join(home, ".zshrc"),        # zsh interactive
    ]
    return [p for p in candidates if os.path.isfile(p)]


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _write_text(path: str, content: str) -> None:
    """Atomic-ish write: write to .tmp then replace."""
    tmp = path + ".trnstmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    os.replace(tmp, path)


def _strip_sentinel_block(content: str) -> str:
    """Remove a previous trns sentinel block (if any) from the file content."""
    return _SENTINEL_RE.sub("", content)


def _build_sentinel_block(directory: str) -> str:
    body = _POSIX_EXPORT_TEMPLATE.format(path=directory)
    return f"{_POSIX_SENTINEL_BEGIN}\n{body}\n{_POSIX_SENTINEL_END}\n"


def _persist_posix_path(directory: str) -> None:
    """Write the PATH export into every relevant shell rc, idempotently.

    Termux: writes $PREFIX/etc/profile.d/trns.sh (system-wide, survives most
    reinstalls). Desktop Linux: writes ~/.profile / ~/.bashrc / ~/.zshrc so
    both login and interactive shells pick it up.

    The previous sentinel block (if any) is stripped before re-insertion so
    toggling PATH off and back on never accumulates duplicates.

    If the user has no shell rc file at all (a freshly-created user, a Docker
    container, minimal installs) we *create* ~/.bashrc with a header comment
    so the export has somewhere to live — better than silently doing nothing.
    """
    if not directory:
        return

    if _is_termux():
        path = _termux_profile_d_writable()
        if path:
            _write_posix_rc(path, directory)
        return

    rc_files = _posix_rc_files()
    if not rc_files:
        # No rc files exist — create ~/.bashrc as the canonical fallback.
        # ~/.bashrc is sourced by interactive bash, which is what most CLI
        # users run. If they prefer zsh or fish they can move the block.
        candidate = os.path.join(os.path.expanduser("~"), ".bashrc")
        if not os.path.exists(candidate):
            # Idempotent: only create if truly missing. Leave the file alone
            # if it's a broken symlink or unreadable — we don't want to
            # overwrite user data we can't see.
            try:
                with open(candidate, "a", encoding="utf-8", newline="\n") as f:
                    f.write("# ~/.bashrc — created by trns installer.\n"
                            "# Login shells also source ~/.profile; the same\n"
                            "# sentinel block is mirrored there when present.\n")
            except OSError:
                return
        rc_files = [candidate]

    for rc in rc_files:
        _write_posix_rc(rc, directory)


def _write_posix_rc(path: str, directory: str) -> None:
    content = _read_text(path)
    stripped = _strip_sentinel_block(content)
    block = _build_sentinel_block(directory)
    # Ensure trailing newline before the block so we don't append to a
    # half-line of previous content.
    if stripped and not stripped.endswith("\n"):
        stripped += "\n"
    new_content = stripped + ("\n" if stripped else "") + block
    _write_text(path, new_content)


def _remove_posix_persistence(directory: str) -> bool:
    """Strip the trns sentinel from every shell rc it was written to.

    Called by `remove_from_path` so /path toggle cleans up after itself.

    Returns True if any rc file was actually modified.
    """
    directory_abs = os.path.normcase(os.path.abspath(directory))
    candidates = [_termux_profile_d_path()] + _posix_rc_files()
    seen: set[str] = set()
    modified = False
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if not os.path.isfile(path):
            continue
        content = _read_text(path)
        stripped = _strip_sentinel_block(content)
        if stripped != content:
            _write_text(path, stripped)
            modified = True
        # If the file we just edited is the only thing left and it's now
        # effectively empty, leave it alone — users notice disappearing rc
        # files far more than they notice a single empty line.
        _ = directory_abs  # referenced for parity; future toggle-by-dir use
    return modified


__all__ = [
    "Config",
    "add_to_path",
    "remove_from_path",
    "path_contains",
    "current_user_path",
    "DEFAULT_SOURCE",
    "DEFAULT_TARGET",
]