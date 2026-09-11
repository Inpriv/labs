"""
core.utils
==========

Cross-platform helpers: ANSI colors, logging, root checks, subprocess,
spinner, MAC normalization, y/n prompt.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Iterator, Optional, Sequence


class C:
    """ANSI color escape codes. Stripped automatically when not a TTY."""
    RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
    RED, GREEN, YELLOW = "\033[31m", "\033[32m", "\033[33m"
    BLUE, MAGENTA, CYAN = "\033[34m", "\033[35m", "\033[36m"
    GRAY, WHITE = "\033[90m", "\033[97m"

    @classmethod
    def wrap(cls, text: str, *codes: str) -> str:
        if not codes or not sys.stdout.isatty():
            return text
        return f"{''.join(codes)}{text}{cls.RESET}"


LOG_FORMAT = "%(asctime)s %(levelname)-5s %(name)s | %(message)s"
LOG_DATEFMT = "%H:%M:%S"


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the `air` logger with a single stderr handler."""
    root = logging.getLogger("air")
    root.setLevel(level)
    if root.handlers:
        return root
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
    root.addHandler(handler)
    root.propagate = False
    return root


log = logging.getLogger("air")


def require_root() -> None:
    """Abort unless the process is running with sufficient privileges."""
    if sys.platform.startswith("win"):
        if not _is_windows_admin():
            raise PermissionError(
                "air must run as Administrator on Windows "
                "(right-click -> Run as administrator)"
            )
        return

    if os.geteuid() != 0:
        raise PermissionError(
            "air requires root. Re-run with sudo:\n"
            f"    sudo {' '.join(sys.argv)}"
        )


def _is_windows_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def require_tool(name: str) -> str:
    """Return the absolute path to an executable, raising on missing."""
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"Required tool '{name}' not found on PATH. "
            f"Install it (e.g. `apt install {name}`) and try again."
        )
    return path


@dataclass
class CmdResult:
    code: int
    stdout: str
    stderr: str
    cmd: Sequence[str]


def run(cmd: Sequence[str], *, check: bool = True, timeout: Optional[float] = 30.0) -> CmdResult:
    """Run a command, returning captured output. Raises on non-zero when check=True."""
    try:
        proc = subprocess.run(
            list(cmd), capture_output=True, text=True, timeout=timeout, check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"Command not found: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(cmd)}") from e

    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"--- stderr ---\n{proc.stderr.strip()}"
        )
    return CmdResult(proc.returncode, proc.stdout, proc.stderr, cmd)


def run_live(cmd: Sequence[str], *, sudo: bool = False) -> int:
    """Run a command attached to the TTY (no capture). Returns exit code."""
    if sudo and not sys.platform.startswith("win") and os.geteuid() != 0:
        cmd = ["sudo", *cmd]
    return subprocess.call(list(cmd))


_SPINNER_FRAMES = "|/-\\"


@contextmanager
def spinner(message: str, *, enabled: bool = True) -> Iterator[threading.Event]:
    """Lightweight stderr spinner; yields a stop event for early termination."""
    if not enabled or not sys.stderr.isatty():
        sys.stderr.write(f"{message}...\n")
        sys.stderr.flush()
        yield threading.Event()
        return

    stop, done = threading.Event(), threading.Event()

    def _run() -> None:
        i = 0
        sys.stderr.write(message + " ")
        sys.stderr.flush()
        while not stop.is_set():
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            sys.stderr.write(f"\r{message} {C.wrap(frame, C.CYAN)}")
            sys.stderr.flush()
            i += 1
            done.wait(timeout=0.1)
        sys.stderr.write("\r" + " " * (len(message) + 4) + "\r")
        sys.stderr.flush()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    try:
        yield stop
    finally:
        stop.set()
        done.set()
        t.join(timeout=0.5)


def human_mac(mac: str) -> str:
    """Normalize a MAC to upper-case colon form."""
    if not mac:
        return ""
    cleaned = mac.replace("-", "").replace(":", "").replace(".", "").upper()
    if len(cleaned) != 12:
        return mac.upper()
    return ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))


def confirm(prompt: str, *, default: bool = False) -> bool:
    """Yes/no prompt. Returns the boolean answer."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{prompt} {suffix}: ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def chunked(seq: Iterable, size: int):
    buf = []
    for item in seq:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf
