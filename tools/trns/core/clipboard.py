"""Best-effort clipboard access, stdlib only.

trns captures the mouse for tap targets, which disables the terminal's own
text selection — so copying has to be first-class. Backends are tried in
order; the first that works wins:

1. ``termux-clipboard-set`` (Termux:API)   - Android
2. ``pbcopy``                              - macOS
3. ``wl-copy`` / ``xclip`` / ``xsel``      - Linux (Wayland / X11)
4. ``clip``                                - Windows
5. OSC 52 escape sequence                  - many modern terminals, over SSH
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys

_COMMANDS = (
    ("termux-clipboard-set",),
    ("pbcopy",),
    ("wl-copy",),
    ("xclip", "-selection", "clipboard"),
    ("xsel", "--clipboard", "--input"),
    ("clip",),
)


def copy(text: str) -> bool:
    """Copy ``text``; returns True if some backend accepted it."""

    for cmd in _COMMANDS:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            # clip.exe expects UTF-16; everything else takes UTF-8.
            data = text.encode("utf-16-le" if cmd[0] == "clip" else "utf-8")
            subprocess.run(cmd, input=data, check=True, timeout=3,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            continue

    if sys.stdout.isatty():
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        sys.stdout.write(f"\033]52;c;{payload}\a")
        sys.stdout.flush()
        return True  # cannot be confirmed; terminals silently ignore it
    return False
