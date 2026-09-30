"""Raw keyboard / mouse input for trns.

Turns terminal bytes into structured events:

    bytes -> UTF-8 / VT escape parser -> ("char", "a") | ("ctrl", b"	")
                                       | (action, params) for ESC sequences

Kept free of any drawing code so it can be unit-tested by monkeypatching
:func:`_read_byte`.
"""

from __future__ import annotations

import os
import sys
import time as _time
import unicodedata
from typing import List, Optional, Tuple

TAB = b"\t"
ENTER = (b"\r", b"\n")
CTRL_C = b"\x03"
CTRL_D = b"\x04"
CTRL_L = b"\x0c"
BACKSPACE = (b"\x08", b"\x7f")
ESC = b"\x1b"




# ---------------------------------------------------------------------------
# Raw byte reader + UTF-8 / VT escape-sequence parser
# ---------------------------------------------------------------------------


# Module-level byte queue so we can hand the parser a synthetic multi-byte
# escape sequence when a Windows special key is detected.
_PENDING_BYTES: bytearray = bytearray()

# Debug logging of raw stdin bytes. Opt-in via ``trns --debug-input`` (see
# trns.py) — primarily to diagnose Termux / Bluetooth-keyboard issues where
# the user reports that a key (Tab, arrow, …) doesn't reach the parser.
# Off by default because every keystroke = a log line.
_DEBUG_INPUT: bool = False
_DEBUG_INPUT_STREAM = None  # type: ignore[var-annotated]


def _set_debug_input(enabled: bool, path: Optional[str]) -> None:
    """Toggle byte-level input tracing.

    When enabled, every byte read from stdin is logged to ``stderr`` *and* to
    ``path`` (if given) as a single line per byte:

        +0.000123  0x09 (\\t) [TAB]

    Timestamps are relative to the first byte in the run so the log is
    stable across TZs and clock changes.
    """
    global _DEBUG_INPUT, _DEBUG_INPUT_STREAM
    _DEBUG_INPUT = bool(enabled)
    if _DEBUG_INPUT_STREAM is not None:
        try:
            _DEBUG_INPUT_STREAM.close()
        except Exception:
            pass
        _DEBUG_INPUT_STREAM = None
    if enabled and path:
        try:
            _DEBUG_INPUT_STREAM = open(path, "a", buffering=1, encoding="utf-8")
        except OSError as exc:
            import sys as _sys
            print(f"trns: cannot open debug log at {path!r}: {exc}", file=_sys.stderr)


_DEBUG_INPUT_T0: Optional[float] = None


def _debug_log_byte(b: bytes) -> None:
    if not _DEBUG_INPUT:
        return
    global _DEBUG_INPUT_T0
    if _DEBUG_INPUT_T0 is None:
        _DEBUG_INPUT_T0 = _time.monotonic()
    dt = _time.monotonic() - _DEBUG_INPUT_T0
    if not b:
        label = "<empty>"
        hex_repr = ""
    else:
        b0 = b[0]
        if b0 == 0x09:
            label = "[TAB]"
        elif b0 == 0x0a:
            label = "[LF]"
        elif b0 == 0x0d:
            label = "[CR]"
        elif b0 == 0x1b:
            label = "[ESC]"
        elif b0 == 0x7f:
            label = "[DEL]"
        elif b0 < 0x20:
            label = f"[CTRL+{chr(b0 + 0x40)}]"
        elif b0 == 0x20:
            label = "[SP]"
        elif 0x20 < b0 < 0x7f:
            label = f"'{chr(b0)}'"
        elif b0 >= 0x80:
            label = f"<utf8-prefix 0x{b0:02x}>"
        else:
            label = "?"
        hex_repr = " ".join(f"0x{x:02x}" for x in b)
    line = f"+{dt:7.3f}  {hex_repr:<16} {label}\n"
    import sys as _sys
    _sys.stderr.write(line)
    if _DEBUG_INPUT_STREAM is not None:
        _DEBUG_INPUT_STREAM.write(line)


_MSVC_SPECIAL_TO_VT: dict = {
    0x48: b"\x1b[A",  # Up
    0x50: b"\x1b[B",  # Down
    0x4B: b"\x1b[D",  # Left
    0x4D: b"\x1b[C",  # Right
    0x47: b"\x1b[H",  # Home
    0x4F: b"\x1b[F",  # End
    0x49: b"\x1b[5~",  # PageUp
    0x51: b"\x1b[6~",  # PageDown
    0x52: b"\x1b[2~",  # Insert
    0x53: b"\x1b[3~",  # Delete
}


def _read_byte() -> bytes:
    """Read exactly one byte of input. Windows special-key pairs are
    translated into matching VT escape sequences so the parser below
    stays platform-agnostic.
    """
    if _PENDING_BYTES:
        b = bytes([_PENDING_BYTES.pop(0)])
        _debug_log_byte(b)
        return b
    if sys.platform == "win32":
        import msvcrt  # type: ignore[import-not-found]
        b = msvcrt.getch()
        if b in (b"\x00", b"\xe0"):
            scan = msvcrt.getch()[0]
            vt = _MSVC_SPECIAL_TO_VT.get(scan)
            if vt:
                if len(vt) > 1:
                    _PENDING_BYTES.extend(vt[1:])
                first = vt[:1]
                _debug_log_byte(first)
                return first
            _debug_log_byte(b"")
            return b""
        _debug_log_byte(b)
        return b
    b = os.read(sys.stdin.fileno(), 1)
    _debug_log_byte(b)
    return b


def char_width(ch: str) -> int:
    """Approximate terminal column width of a single grapheme."""

    if not ch:
        return 0
    cat = unicodedata.category(ch)
    if cat.startswith("M") or cat == "Cf":
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    cp = ord(ch)
    if (
        0x1F000 <= cp <= 0x1FFFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2700 <= cp <= 0x27FF
    ):
        return 2
    return 1


def buffered_width(buf: List[str], start: int = 0) -> int:
    """Sum of column widths for ``buf[start:]``."""

    return sum(char_width(c) for c in buf[start:])


def column_to_index(buf: List[str], col: int) -> int:
    """Map a 0-based terminal column offset to a logical-character index.

    Used for mouse-click → cursor-position calculations. Wide characters
    (emoji, CJK) take two columns; we snap to the nearest boundary.
    """

    if col <= 0:
        return 0
    cumulative = 0
    for i, ch in enumerate(buf):
        w = char_width(ch)
        # Before this char's first column → place cursor at i.
        if col <= cumulative:
            return i
        # Inside this char's column range → snap to start or end of it.
        if col < cumulative + w:
            if col >= cumulative + (w + 1) // 2:
                cumulative += w
                continue
            return i
        cumulative += w
    return len(buf)


def read_input_unit():
    """Read one logical input unit — either a 1-byte control char or a
    fully-assembled UTF-8 grapheme.

    Returns ``("ctrl", bytes)``, ``("char", str)`` or ``(None, None)``.
    """

    try:
        first = _read_byte()
    except (EOFError, OSError):
        return None, None
    if not first:
        return None, None

    b0 = first[0]
    if b0 < 0x20 or b0 == 0x7F:
        return "ctrl", first

    if b0 < 0x80:
        return "char", first.decode("ascii")
    if b0 < 0xC0:
        return None, None
    if b0 < 0xE0:
        n_extra = 1
    elif b0 < 0xF0:
        n_extra = 2
    else:
        n_extra = 3

    parts = [first]
    for _ in range(n_extra):
        try:
            nxt = _read_byte()
        except (EOFError, OSError):
            return None, None
        parts.append(nxt)

    try:
        return "char", b"".join(parts).decode("utf-8")
    except UnicodeDecodeError:
        return None, None


def read_escape() -> Tuple[Optional[str], Optional[dict]]:
    """Consume the body of an escape sequence starting after ESC.

    Returns ``(action, params)``:
        * action is one of "up", "down", "left", "right", "home", "end",
          "pageup", "pagedown", "insert", "delete", "mouse_event",
          or None on EOF.
        * params is a dict for "mouse_event" (button, x, y, motion, release)
          or ``None`` otherwise.
    """

    try:
        nxt = _read_byte()
    except (EOFError, OSError):
        return None, None

    if nxt == b"O":
        try:
            fb = _read_byte()
        except (EOFError, OSError):
            return None, None
        action = {
            b"A": "up", b"B": "down", b"C": "right", b"D": "left",
            b"H": "home", b"F": "end",
        }.get(fb)
        return action, None

    if nxt != b"[":
        for _ in range(8):
            try:
                b = _read_byte()
            except (EOFError, OSError):
                return None, None
            if 0x40 <= b[0] <= 0x7E:
                return "unknown", None
        return "unknown", None

    params_bytes = bytearray()
    while True:
        try:
            b = _read_byte()
        except (EOFError, OSError):
            return None, None
        b0 = b[0]
        if 0x40 <= b0 <= 0x7E:
            final = chr(b0)
            break
        params_bytes.extend(b)

    param_str = params_bytes.decode("ascii", errors="replace")

    if final in ("A", "B", "C", "D", "H", "F") and not param_str:
        return {
            "A": "up", "B": "down", "C": "right", "D": "left",
            "H": "home", "F": "end",
        }[final], None

    if final == "~":
        digit = param_str.split(";")[0]
        return {
            "1": "home",
            "2": "insert",
            "3": "delete",
            "4": "end",
            "5": "pageup",
            "6": "pagedown",
            "7": "home",
            "8": "end",
        }.get(digit, "unknown"), None

    if final == "M" and not param_str:
        # xterm mouse: ESC [ M Cb Cx Cy, encoded as offset by 0x20.
        try:
            cb = _read_byte()[0]
            cx = _read_byte()[0] - 0x20
            cy = _read_byte()[0] - 0x20
        except (EOFError, OSError):
            return None, None
        return "mouse_event", {
            "button": cb, "x": cx, "y": cy,
            "motion": False, "release": False,
        }

    if final in ("M", "m") and param_str[:1] in ("<", ">"):
        # SGR mouse: ESC [ < Cb ; Cx ; Cy M (press) / m (release).
        # For motion-with-button-held, the same M/m is reported each
        # time the pointer moves while the button is down, with the
        # button code ORed with 32.
        try:
            parts = param_str.lstrip("<>").split(";")
            cb = int(parts[0])
            cx = int(parts[1]) if len(parts) > 1 else 0
            cy = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            return None, None
        if cb & 64:
            # Wheel (and touch-scroll on Termux): 64 = up, 65 = down.
            return ("mouse_wheel_down" if cb & 1 else "mouse_wheel_up"), None
        motion = cb >= 32
        # Mask off bit 5 (0x20) which marks a motion-with-button-held
        # event so we recover the underlying button code (0=left, 1=middle,
        # 2=right). Using ``& 0x3F`` would have preserved the motion bit.
        button = cb & 0xDF
        return "mouse_event", {
            "button": button, "x": cx, "y": cy,
            "motion": motion,
            "release": final == "m",
        }

    return "unknown", None


