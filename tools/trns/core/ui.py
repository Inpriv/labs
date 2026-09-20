"""Interactive REPL + settings menu for trns.

The REPL draws a true TUI inside the alternate screen buffer:

* a static **header** at the top (banner, brand row, divider, language
  indicator with codes + names + ``Tab to swap`` hint);
* a **scrollable history** area in the middle (last N exchanges that fit
  in the available height; newest entry auto-anchored at the bottom);
* a static **footer** (key hints) just above the prompt;
* a **persistent bottom input** that re-arms after every submission
  with mouse-aware selection / cursor placement.

Input pipeline (the critical part):

    terminal bytes
         ↓
    escape / UTF-8 parser (this module)
         ↓
    structured key / mouse events
         ↓
    input state machine (text + cursor + selection)
         ↓
    prompt renderer

This separation is what makes Backspace delete only the previous
character, what stops arrow keys from producing garbage, and what lets
mouse-button-drag highlight a real selection range inside the input.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from . import utils
from . import __version__ as CORE_VERSION
from .translator import (
    MAX_CHARS,
    Translation,
    TranslationError,
    translate_with_retry,
)


# ---------------------------------------------------------------------------
# Cross-platform getch
# ---------------------------------------------------------------------------


def _getch():
    if sys.platform == "win32":
        try:
            import msvcrt  # type: ignore[import-not-found]
            return msvcrt.getch
        except ImportError:
            pass
    import termios
    import tty

    def _posix_getch():
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = os.read(fd, 1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return ch

    return _posix_getch


_GETCH = _getch()

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
    stays platform-agnostic."""

    if _PENDING_BYTES:
        return bytes([_PENDING_BYTES.pop(0)])
    if sys.platform == "win32":
        import msvcrt  # type: ignore[import-not-found]
        b = msvcrt.getch()
        if b in (b"\x00", b"\xe0"):
            scan = msvcrt.getch()[0]
            vt = _MSVC_SPECIAL_TO_VT.get(scan)
            if vt:
                if len(vt) > 1:
                    _PENDING_BYTES.extend(vt[1:])
                return vt[:1]
            return b""
        return b
    return os.read(sys.stdin.fileno(), 1)


def _char_width(ch: str) -> int:
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


def _buffered_width(buf: List[str], start: int = 0) -> int:
    """Sum of column widths for ``buf[start:]``."""

    return sum(_char_width(c) for c in buf[start:])


def _column_to_buf_index(buf: List[str], col: int) -> int:
    """Map a 0-based terminal column offset to a logical-character index.

    Used for mouse-click → cursor-position calculations. Wide characters
    (emoji, CJK) take two columns; we snap to the nearest boundary.
    """

    if col <= 0:
        return 0
    cumulative = 0
    for i, ch in enumerate(buf):
        w = _char_width(ch)
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


def _read_n(n: int) -> bytes:
    """Read ``n`` bytes (legacy helper, kept for compatibility)."""

    out = bytearray()
    while len(out) < n:
        b = _read_byte()
        if not b:
            continue
        out.extend(b)
    return bytes(out)


def _read_one_input_unit():
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


def _read_after_esc() -> Tuple[Optional[str], Optional[dict]]:
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

    if final == "M" and param_str and param_str[0] in "<>":
        try:
            cb = int(param_str.lstrip("<>").split(";")[0])
        except ValueError:
            return None, None
        if cb in (64, 65):
            return ("mouse_wheel_up" if cb == 64 else "mouse_wheel_down"), None

    return "unknown", None


# ---------------------------------------------------------------------------
# Prompt state
# ---------------------------------------------------------------------------


@dataclass
class Direction:
    source: str
    target: str

    def swapped(self) -> "Direction":
        if self.source == "auto":
            return Direction(source=self.target, target="auto")
        if self.target == "auto":
            return Direction(source="auto", target=self.source)
        return Direction(source=self.target, target=self.source)

    def label(self) -> str:
        s = utils.language_short(self.source)
        t = utils.language_short(self.target)
        return f"{s} → {t}"

    def detailed(self) -> str:
        s = f"{utils.language_short(self.source)} ({utils.language_name(self.source)})"
        t = f"{utils.language_short(self.target)} ({utils.language_name(self.target)})"
        return f"{s} → {t}"


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------


BANNER = r""" _____  ____        _      ____
|_   _||  _ \      | |    / ____|
  | |  | |_) |_   _| |__ | (___  _ __   ___  _ __
  | |  |  _ <| | | | '_ \ \___ \| '_ \ / _ \| '_ \
 _| |_ | |_) | |_| | |_) |____) | | | | (_) | | | |
|_____|____/ \__,_|_.__/|_____/|_| |_|\___/|_| |_|
          translate · Inpriv        v""" + VERSION


# ---------------------------------------------------------------------------
# Layout primitives
# ---------------------------------------------------------------------------


def _banner_lines() -> List[str]:
    return BANNER.strip("\n").split("\n")


def _brand_line(cols: int) -> str:
    brand_left = "translate · Inpriv"
    brand_right = f"v{CORE_VERSION}"
    gap = max(
        2,
        cols - _visible_length(brand_left) - _visible_length(brand_right) - 2,
    )
    return (
        f" {utils.dim(brand_left)}"
        f"{' ' * gap}"
        f"{utils.dim(brand_right)}"
    )


def _divider_line(cols: int) -> str:
    return f" {utils.dim('─' * max(20, cols - 2))}"


def _language_line(direction: Direction) -> str:
    s_short = utils.language_short(direction.source)
    t_short = utils.language_short(direction.target)
    s_name = utils.language_name(direction.source)
    t_name = utils.language_name(direction.target)
    arrow = utils.muted('→')
    codes = (
        f"{utils.bold(utils.primary(s_short))} "
        f"{arrow} "
        f"{utils.bold(utils.primary(t_short))}"
    )
    names = (
        f"{utils.dim(s_name)} {arrow} {utils.dim(t_name)}"
    )
    sep = f"  {utils.dim('·')}  "
    hint = utils.dim("Tab to swap")
    return f" {codes}{sep}{names}{sep}{hint}"


def _status_line() -> str:
    items = [
        (utils.success('◉'), utils.dim('ready')),
        (utils.muted('⏎'), utils.dim('translate')),
        (utils.muted('⇄'), utils.dim('swap')),
        (utils.muted('^L'), utils.dim('clear')),
    ]
    sep = f"  {utils.dim('·')}  "
    return f" " + sep.join(f"{icon} {label}" for icon, label in items)


def _swap_line(direction: Direction) -> str:
    return (
        f" {utils.dim('·')} {utils.muted('swapped')} "
        f"{utils.muted('→')} {utils.bold(direction.label())}"
    )


def _error_line(message: str) -> str:
    return f" {utils.error('✗')} {message}"


def _exchange_lines(direction: Direction, user_text: str, translated: str,
                   *, detected: Optional[str] = None) -> List[str]:
    cols, _ = _terminal_size()

    user_block = _wrap_paragraph(
        user_text,
        first_indent=f"{utils.primary('>')} ",
        rest_indent="   ",
        width=cols - 1,
    )
    resp_block = _wrap_paragraph(
        translated,
        first_indent=f"{utils.primary('→')} ",
        rest_indent="    ",
        width=cols - 3,
    )

    lines: List[str] = []
    for ln in user_block.split("\n"):
        lines.append(" " + ln)
    lines.append("")
    for ln in resp_block.split("\n"):
        lines.append("   " + ln)
    return lines


def _history_lines(history: List[dict]) -> List[str]:
    rows: List[str] = []
    for entry in history:
        if entry["kind"] == "exchange":
            rows.extend(_exchange_lines(
                entry["direction"], entry["input"], entry["output"],
                detected=entry.get("detected"),
            ))
            rows.append("")
        elif entry["kind"] == "error":
            rows.append(_error_line(entry["message"]))
            rows.append("")
    while rows and rows[-1] == "":
        rows.pop()
    return rows


def _fit_history_to_viewport(
    rows: List[str],
    height: int,
    *,
    scroll_offset: int = 0,
) -> List[str]:
    """Return the visible slice of history rows for the current frame."""

    if height <= 0:
        return []
    if scroll_offset > 0 and len(rows) > height:
        offset = min(scroll_offset, len(rows) - height)
        end = len(rows) - offset
        start = end - height
        return rows[start:end]
    if len(rows) >= height:
        return rows[-height:]
    return rows + [""] * (height - len(rows))


_HEADER_ROWS = 12
_FOOTER_ROWS = 5


def _redraw_full(direction: Direction, history: List[dict],
                 carry: str, *,
                 scroll_offset: int = 0) -> None:
    cols, rows = _terminal_size()

    sys.stdout.write("\033[H\033[J")

    for line in _banner_lines():
        sys.stdout.write(utils.primary(line) + "\n")
    sys.stdout.write(_brand_line(cols) + "\n")
    sys.stdout.write(_divider_line(cols) + "\n")
    sys.stdout.write("\n")
    sys.stdout.write(_language_line(direction) + "\n")
    sys.stdout.write("\n")

    history_height = max(1, rows - _HEADER_ROWS - _FOOTER_ROWS)
    history_rows = _history_lines(history)
    visible = _fit_history_to_viewport(
        history_rows, history_height, scroll_offset=scroll_offset,
    )
    for line in visible:
        sys.stdout.write(line + "\n")

    sys.stdout.write("\n")
    sys.stdout.write(_divider_line(cols) + "\n")
    sys.stdout.write(_status_line() + "\n")
    sys.stdout.write("\n")
    sys.stdout.write(f" > {carry}")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Prompt rendering with optional selection highlight
# ---------------------------------------------------------------------------


def _erase_columns(width: int) -> None:
    """Erase ``width`` columns ending at the current cursor position.

    Move the cursor left by ``width``, overwrite the cells with spaces,
    then return the cursor to where it started. Used by the fast
    Backspace-at-end path so the erased glyph is actually removed from
    the screen, not just left behind under the cursor.
    """

    if width <= 0:
        return
    sys.stdout.write(f"\033[{width}D")
    sys.stdout.write(" " * width)
    sys.stdout.write(f"\033[{width}D")
    sys.stdout.flush()


def _redraw_prompt(
    buf: List[str],
    cursor_pos: int,
    sel_start: Optional[int] = None,
    sel_end: Optional[int] = None,
) -> None:
    """Single source of truth for prompt rendering.

    Always clear-then-redraw so the visual state is byte-identical to
    the logical state — that's what kills the long-standing class of
    bugs where Backspace 'left behind' the erased character or where a
    mid-buffer edit ghosted the previous tail. Selection is rendered via
    ANSI reverse video.
    """

    sys.stdout.write("\r\033[K")
    sys.stdout.write(" > ")
    if (
        sel_start is not None
        and sel_end is not None
        and sel_start != sel_end
    ):
        lo = min(sel_start, sel_end)
        hi = max(sel_start, sel_end)
        sys.stdout.write("".join(buf[:lo]))
        sys.stdout.write("\033[7m")  # reverse video on
        sys.stdout.write("".join(buf[lo:hi]))
        sys.stdout.write("\033[27m")  # reverse video off
        sys.stdout.write("".join(buf[hi:]))
    else:
        sys.stdout.write("".join(buf))
    if cursor_pos < len(buf):
        n_back = _buffered_width(buf, cursor_pos)
        if n_back > 0:
            sys.stdout.write(f"\033[{n_back}D")
    sys.stdout.flush()


def _prompt_append_char(ch: str) -> None:
    """Fast path for typing at the very end of the buffer (no flicker)."""

    sys.stdout.write(ch)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# One-shot helpers
# ---------------------------------------------------------------------------


def confirm(question: str, *, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            raw = input(f"{utils.bold(question)} {utils.dim(suffix)} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if not raw:
            return default
        if raw in ("y", "yes", "tak"):
            return True
        if raw in ("n", "no", "nie"):
            return False
        print(utils.error("  please answer y or n"))


def pause() -> None:
    try:
        input(utils.dim("press Enter to continue…"))
    except (EOFError, KeyboardInterrupt):
        print()


def notify(message: str, kind: str = "info") -> None:
    icon = {
        "info": utils.muted("i"),
        "ok": utils.success("✓"),
        "warn": utils.warn("!"),
        "err": utils.error("✗"),
    }.get(kind, utils.muted("i"))
    print(f"  {icon} {message}")


# ---------------------------------------------------------------------------
# Language picker
# ---------------------------------------------------------------------------


def pick_language(question: str, *, exclude: Optional[str] = None,
                  default: Optional[str] = None) -> Optional[str]:
    common = [
        "en", "pl", "de", "fr", "es", "it", "pt", "nl",
        "ru", "uk", "cs", "sk", "ro", "hu", "tr", "sv",
        "ja", "ko", "zh", "ar", "hi",
    ]
    if exclude:
        common = [c for c in common if c != exclude]
    if default and default not in common:
        common.insert(0, default)

    while True:
        print()
        print(utils.bold(question))
        print(utils.dim(
            f"(press Enter for default: "
            f"{utils.language_name(default) if default else 'auto'}, "
            "'more' for the full list, 'q' to cancel)"
        ))
        line_parts: List[str] = []
        for j, code in enumerate(common):
            idx = j + 1
            line_parts.append(
                f"{utils.dim(f'{idx:>3}')} {utils.primary(code):<8} "
                f"{utils.dim(utils.language_name(code)):<22}"
            )
        for i in range(0, len(line_parts), 4):
            print("  " + "  ".join(line_parts[i:i + 4]))

        raw = input(f"\n{utils.bold('→ ')}").strip().lower()
        if not raw:
            return default
        if raw in ("q", "quit", "cancel", "exit"):
            return None
        if raw in ("more", "m"):
            common = sorted(utils.LANGUAGES.keys())
            if exclude:
                common = [c for c in common if c != exclude]
            continue
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(common):
                return common[idx]
        if raw in utils.LANGUAGES:
            return raw
        notify(f"unknown choice: {raw!r}", "err")


# ---------------------------------------------------------------------------
# Persistent-prompt line reader
# ---------------------------------------------------------------------------


def _read_line_at_prompt(
    initial: str = "",
    *,
    on_ctrl_l: Optional[Callable[[], None]] = None,
    on_scroll: Optional[Callable[[str], None]] = None,
    on_tab: Optional[Callable[[], None]] = None,
    on_text_change: Optional[Callable[[List[str], int], None]] = None,
    input_row: Optional[int] = None,
) -> Tuple[Optional[str], bool]:
    """Interactive line reader with selection + mouse-aware editing.

    Returns ``(text, swapped)``:
        * ``(None, False)``        → Ctrl+C / Ctrl+D → exit REPL
        * ``(text, False)``        → Enter on text
        * ``(text, True)``         → legacy Tab-as-swap (retained for
                                    back-compat; the real Tab handler is
                                    the ``on_tab`` callback which keeps
                                    the buffer / cursor / selection
                                    exactly intact while the language
                                    pair toggles silently).

    Selection state is half-open ``[sel_start, sel_end)``; an empty
    selection (anchor == head) is treated as "no selection" by all
    editing code paths.
    """

    buf: List[str] = list(initial)  # one logical grapheme per element
    cursor_pos = len(buf)
    sel_start: Optional[int] = None
    sel_end: Optional[int] = None
    dragging = False

    def _publish() -> None:
        """Tell the caller the current buffer state. The ``on_tab`` and
        ``_redraw_full`` paths in ``repl`` rely on this to render the
        prompt with whatever the user has actually typed — including
        across Tab, which must not lose any input content."""
        if on_text_change is not None:
            on_text_change(buf, cursor_pos)

    def clear_selection() -> None:
        nonlocal sel_start, sel_end
        sel_start = sel_end = None

    def set_selection(a: Optional[int], b: Optional[int]) -> None:
        nonlocal sel_start, sel_end
        sel_start = a
        sel_end = b

    _redraw_prompt(buf, cursor_pos, sel_start, sel_end)
    _publish()

    def _delete_range(lo: int, hi: int) -> None:
        del buf[lo:hi]

    def _buf_full_redraw() -> None:
        _redraw_prompt(buf, cursor_pos, sel_start, sel_end)
        _publish()

    while True:
        kind, payload = _read_one_input_unit()
        if kind is None:
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None, False

        if kind == "char":
            decoded = payload
            # Always wipe any active selection when a printable arrives.
            if (
                sel_start is not None
                and sel_end is not None
                and sel_start != sel_end
            ):
                lo, hi = sorted([sel_start, sel_end])
                _delete_range(lo, hi)
                buf[lo:lo] = [decoded]
                cursor_pos = lo + 1
                clear_selection()
                _buf_full_redraw()
                _publish()
                continue
            if cursor_pos < len(buf):
                buf.insert(cursor_pos, decoded)
                cursor_pos += 1
                _buf_full_redraw()
                _publish()
            else:
                buf.append(decoded)
                cursor_pos += 1
                _prompt_append_char(decoded)
                _publish()
            continue

        ch = payload

        if ch in CTRL_C or ch in CTRL_D:
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None, False

        if ch in CTRL_L:
            buf.clear()
            cursor_pos = 0
            clear_selection()
            if on_ctrl_l is not None:
                on_ctrl_l()
            _publish()
            continue

        if ch == ESC:
            action, params = _read_after_esc()
            if action is None:
                continue

            if action in ("left", "right", "home", "end"):
                clear_selection()
                if action == "left" and cursor_pos > 0:
                    cursor_pos -= 1
                elif action == "right" and cursor_pos < len(buf):
                    cursor_pos += 1
                elif action == "home":
                    cursor_pos = 0
                elif action == "end":
                    cursor_pos = len(buf)
                _buf_full_redraw()
                continue

            if action in ("up", "down", "pageup", "pagedown",
                          "mouse_wheel_up", "mouse_wheel_down"):
                if on_scroll is not None:
                    on_scroll(action)
                continue

            if action == "mouse_event" and params is not None:
                # Mouse press / drag / release. The input row is the
                # bottom row; clicks outside it are ignored. Wheel
                # events are routed above to ``on_scroll`` via the
                # ``mouse_wheel_up`` / ``mouse_wheel_down`` actions.
                if (
                    input_row is not None
                    and params["y"] == input_row
                    and params["button"] == 0
                ):
                    # SGR mouse coords are 1-based; subtract the prompt
                    # prefix (3 cols) and the 1-based offset.
                    col = params["x"] - 4
                    pos = _column_to_buf_index(buf, max(0, col))
                    if params.get("release"):
                        # Left button released.
                        dragging = False
                        if sel_start == sel_end:
                            # Plain click — move cursor, no selection.
                            sel_start = sel_end = None
                            cursor_pos = pos
                    elif params.get("motion"):
                        # Drag — extend selection to the new position.
                        if sel_start is None:
                            sel_start = cursor_pos
                        sel_end = pos
                    else:
                        # Press — anchor the selection start here.
                        sel_start = sel_end = pos
                        dragging = True
                    _buf_full_redraw()
                continue

            # insert/delete/unknown: silently dropped
            continue

        if ch in TAB:
            # Application-level shortcut: swap source/target languages.
            # Tab is fully consumed here — no newline, no return, no buffer
            # mutation. The text and cursor stay exactly where they were.
            # The ``on_tab`` callback handles the swap (and redraws the
            # language indicator at the top of the frame).
            if on_tab is not None:
                on_tab()
            continue

        if ch in ENTER:
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(buf), False

        if ch in BACKSPACE:
            # Selection present → delete entire range.
            if (
                sel_start is not None
                and sel_end is not None
                and sel_start != sel_end
            ):
                lo, hi = sorted([sel_start, sel_end])
                _delete_range(lo, hi)
                cursor_pos = lo
                clear_selection()
                _buf_full_redraw()
                _publish()
                continue
            # At the very start → no-op.
            if cursor_pos == 0:
                continue
            removed = buf[cursor_pos - 1]
            removed_w = _char_width(removed)
            if cursor_pos == len(buf):
                # Fast path: classic ``\b \b`` actually erases the glyph.
                buf.pop()
                cursor_pos -= 1
                _erase_columns(removed_w)
                _publish()
            else:
                buf.pop(cursor_pos - 1)
                cursor_pos -= 1
                _buf_full_redraw()
                _publish()
            continue

        # Everything else: drop silently (no buffer mutation, no output).
        continue


# ---------------------------------------------------------------------------
# Settings menu
# ---------------------------------------------------------------------------


def settings_menu(cfg) -> bool:
    mutated = False
    while True:
        print()
        print(utils.bold("Settings") + utils.dim("  — choose a number"))
        print(utils.dim("─" * 44))
        print(
            f"  {utils.primary('1')}  Source language        "
            f"{utils.dim('→')} {utils.success(utils.language_name(cfg.source))}"
            f" {utils.dim('(' + cfg.source + ')')}"
        )
        print(
            f"  {utils.primary('2')}  Target language        "
            f"{utils.dim('→')} {utils.success(utils.language_name(cfg.target))}"
            f" {utils.dim('(' + cfg.target + ')')}"
        )
        print(
            f"  {utils.primary('3')}  Swap source <-> target "
            f"{utils.dim('→')} {Direction(cfg.source, cfg.target).label()}"
        )
        print(
            f"  {utils.primary('4')}  Add trns to PATH       "
            f"{utils.dim('→')} "
            + (
                utils.success("enabled") if cfg.path_opt_in else utils.warn("disabled")
            )
        )
        print(
            f"  {utils.primary('5')}  Show config file path  "
            f"{utils.dim('→')} {utils.muted(cfg.config_path())}"
        )
        print(f"  {utils.primary('q')}  Back to translator")
        print(utils.dim("─" * 44))

        choice = input(f"{utils.bold('→ ')}").strip().lower()
        if choice in ("q", "quit", "exit", "back", "0"):
            break
        elif choice == "1":
            new = pick_language("Pick a source language",
                                exclude=cfg.target, default=cfg.source)
            if new:
                cfg.source = new
                mutated = True
                notify(f"source language set to {utils.language_name(new)}", "ok")
        elif choice == "2":
            new = pick_language("Pick a target language",
                                exclude=cfg.source, default=cfg.target)
            if new:
                cfg.target = new
                mutated = True
                notify(f"target language set to {utils.language_name(new)}", "ok")
        elif choice == "3":
            swapped = Direction(cfg.source, cfg.target).swapped()
            cfg.source, cfg.target = swapped.source, swapped.target
            mutated = True
            notify(f"swapped → {Direction(cfg.source, cfg.target).label()}", "ok")
        elif choice == "4":
            toggle_path(cfg)
            mutated = True
        elif choice == "5":
            notify(cfg.config_path(), "info")
            pause()
        else:
            notify("unknown option", "err")

    return mutated


def toggle_path(cfg) -> None:
    from . import config  # avoid cycle

    if cfg.path_opt_in:
        if cfg.path_dir and config.path_contains(cfg.path_dir):
            if confirm(
                f"Remove trns from your user PATH? ({cfg.path_dir})",
                default=False,
            ):
                config.remove_from_path(cfg.path_dir)
                cfg.path_opt_in = False
                notify("removed from PATH", "ok")
                notify(
                    "open a new terminal window for the change to take effect",
                    "warn",
                )
            else:
                notify("cancelled", "info")
        else:
            cfg.path_opt_in = False
            notify("PATH entry was already gone", "info")
    else:
        if cfg.path_dir is None:
            notify("cannot enable: install directory not recorded", "err")
            return
        if confirm(
            f"Add trns to your user PATH?\n  {utils.muted(cfg.path_dir)}",
            default=True,
        ):
            if config.add_to_path(cfg.path_dir):
                notify("added to PATH", "ok")
                notify(
                    "open a new terminal window for the change to take effect",
                    "warn",
                )
            else:
                notify("already on PATH", "info")
            cfg.path_opt_in = True
        else:
            notify("cancelled", "info")


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


def repl(cfg) -> int:
    if not utils._IS_TTY:
        print(utils.warn(
            "trns interactive mode needs a real terminal. "
            "Try `trns <phrase>` for one-shot translation."
        ))
        return 2

    direction = Direction(cfg.source, cfg.target)
    history: List[dict] = []
    carry: str = ""
    scroll_offset: int = 0

    # Read the input row position once and remember it — anything else
    # would shift around the moment the user types a single character.
    _, rows = _terminal_size()
    input_row = rows

    sys.stdout.write("\033[?1049h\033[?1000h\033[?1006h")
    sys.stdout.flush()

    def _on_ctrl_l() -> None:
        nonlocal scroll_offset
        history.clear()
        scroll_offset = 0
        _redraw_full(direction, history, "", scroll_offset=0)

    def _on_scroll(action: str) -> None:
        nonlocal scroll_offset
        if not history:
            return
        _, rows_count = _terminal_size()
        viewport_h = max(1, rows_count - _HEADER_ROWS - _FOOTER_ROWS)
        current_rows = _history_lines(history)
        max_offset = max(0, len(current_rows) - viewport_h)

        if action in ("up", "mouse_wheel_up"):
            scroll_offset = min(scroll_offset + 1, max_offset)
        elif action in ("down", "mouse_wheel_down"):
            scroll_offset = max(scroll_offset - 1, 0)
        elif action == "pageup":
            scroll_offset = min(scroll_offset + max(1, viewport_h - 1), max_offset)
        elif action == "pagedown":
            scroll_offset = max(scroll_offset - max(1, viewport_h - 1), 0)
        else:
            return

        _redraw_full(direction, history, carry, scroll_offset=scroll_offset)

    # Mouse wheel events are handled by ``on_scroll`` above; press /
    # drag / release for the input row are handled inside
    # ``_read_line_at_prompt`` itself.

    # Live mirror of the line-reader's buffer and cursor. The reader
    # pushes a fresh copy via the on_text_change callback every time it
    # mutates the buffer or moves the cursor, so redraws always have
    # the latest state even when the user is mid-edit.
    current_input: List[str] = []
    current_cursor: int = 0

    def _capture_text(buf: List[str], cursor_pos: int) -> None:
        nonlocal current_input, current_cursor
        current_input = list(buf)
        current_cursor = cursor_pos

    def _on_tab() -> None:
        """Swap direction and re-render the frame.

        The text buffer, selection and logical cursor position are all
        preserved. Re-rendering through ``_redraw_full`` (the same path
        the repl loop top uses) keeps the language selector at exactly
        one fixed row of the layout — there is never a duplicate
        selector stacked on top of itself.
        """
        nonlocal direction
        direction = direction.swapped()
        cfg.source, cfg.target = direction.source, direction.target
        _redraw_full(
            direction, history, "".join(current_input),
            scroll_offset=scroll_offset,
        )

    try:
        while True:
            # The line reader owns the prompt line via ``on_text_change``
            # updates to ``current_input``. We render that mirror here so
            # nothing the user has typed is ever wiped by a redraw.
            _redraw_full(
                direction, history, "".join(current_input),
                scroll_offset=scroll_offset,
            )
            _, rows_count = _terminal_size()
            input_row = rows_count  # bottom row

            try:
                text, swapped = _read_line_at_prompt(
                    initial=carry,
                    on_ctrl_l=_on_ctrl_l,
                    on_scroll=_on_scroll,
                    on_tab=_on_tab,
                    on_text_change=_capture_text,
                    input_row=input_row,
                )
            except (EOFError, KeyboardInterrupt):
                return 0
            if text is None:
                return 0

            # Note: there is no longer a ``swapped=True`` return path
            # in the line reader. Tab is handled entirely in-loop via
            # the ``on_tab`` callback, so the historical "if swapped:"
            # block that used to re-swap the direction here is gone.
            # Keeping it would have been dead code today, but it's
            # safer to remove it outright so that no future change to
            # the line reader can accidentally introduce a *second*
            # language swap for a single physical Tab key press.
            carry = ""

            text = text.strip()
            if not text:
                continue

            if text.startswith("/"):
                cmd = text.split()[0].lower()
                if cmd in ("/clear", "/cls"):
                    history.clear()
                    scroll_offset = 0
                    continue
                handled = _handle_command(text, cfg, direction)
                if handled is None:
                    return 0
                if handled is True:
                    direction = Direction(cfg.source, cfg.target)
                continue

            if len(text) > MAX_CHARS:
                history.append({
                    "kind": "error",
                    "message": (
                        f"input is {len(text)} chars (limit {MAX_CHARS}); "
                        "shorten it"
                    ),
                })
                continue

            spinner = _Spinner(
                f"translating via {utils.language_short(direction.source)}"
                f"{utils.muted('→')}"
                f"{utils.language_short(direction.target)}"
            ).start()
            try:
                result: Translation = translate_with_retry(
                    text, direction.source, direction.target,
                )
            except TranslationError as e:
                spinner.stop()
                history.append({"kind": "error", "message": str(e)})
                continue
            finally:
                spinner.stop()

            history.append({
                "kind": "exchange",
                "direction": direction,
                "input": text,
                "output": result.text,
                "detected": result.detected_source_lang,
            })
            scroll_offset = 0
    finally:
        sys.stdout.write("\033[?1006l\033[?1000l\033[?1049l")
        sys.stdout.flush()


def _handle_command(text: str, cfg, direction: Direction) -> Optional[bool]:
    parts = text.split()
    cmd = parts[0].lower()

    if cmd in ("/quit", "/exit", "/q"):
        return None
    if cmd in ("/swap", "/s"):
        new_dir = direction.swapped()
        cfg.source, cfg.target = new_dir.source, new_dir.target
        return True
    if cmd in ("/help", "/?", "/h"):
        _print_help()
        return False
    if cmd in ("/settings", "/config", "/set"):
        changed = settings_menu(cfg)
        return True if changed else False
    if cmd in ("/path",):
        toggle_path(cfg)
        return True
    notify(f"unknown command: {cmd!r}  (try /help)", "err")
    return False


def _print_help() -> None:
    print()
    print(utils.bold("Commands") + utils.dim("  (start with /)"))
    print(utils.dim("─" * 44))
    print(f"  {utils.primary('/swap')}      swap source <-> target")
    print(f"  {utils.primary('/settings')}   open the settings menu")
    print(f"  {utils.primary('/path')}       toggle PATH entry")
    print(f"  {utils.primary('/clear')}      clear the screen and history")
    print(f"  {utils.primary('/help')}       show this help")
    print(f"  {utils.primary('/quit')}       exit trns")
    print(utils.dim("─" * 44))
    print(f"  {utils.dim('Tip: press Tab while typing to swap direction instantly.')}")
    print()


# ---------------------------------------------------------------------------
# Spinner
# ---------------------------------------------------------------------------


class _Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, label: str) -> None:
        self.label = label

    def start(self) -> "_Spinner":
        self._stop = False
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        self._thread = t
        return self

    def stop(self) -> None:
        self._stop = True
        t = getattr(self, "_thread", None)
        if t and t.is_alive():
            t.join(timeout=0.2)
        if utils._IS_TTY or utils._force_color():
            sys.stdout.write("\r\033[2K")
        else:
            sys.stdout.write("\r")
        sys.stdout.flush()

    def _run(self) -> None:
        if not (utils._IS_TTY or utils._force_color()):
            return
        i = 0
        while not self._stop:
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r  {utils.dim(frame)} {utils.dim(self.label)}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1


# ---------------------------------------------------------------------------
# Missing helpers (filled from prior implementation)
# ---------------------------------------------------------------------------


def _terminal_size(default: Tuple[int, int] = (40, 24)) -> Tuple[int, int]:
    try:
        size = shutil.get_terminal_size(default)
    except (OSError, ValueError):
        size = shutil.os.terminal_size(default)
    cols = size.columns if isinstance(size.columns, int) else default[0]
    rows = size.lines if isinstance(size.lines, int) else default[1]
    if cols <= 0:
        cols = default[0]
    if rows <= 0:
        rows = default[1]
    return max(40, min(cols, 200)), max(18, min(rows, 200))


def _visible_length(text: str) -> int:
    return len(re.sub(r"\x1b\[[0-9;]*m", "", text))


def _wrap_paragraph(text: str, *, first_indent: str, rest_indent: str,
                    width: int) -> str:
    inner_width = max(10, width - len(rest_indent))
    rendered: List[str] = []
    for i, paragraph in enumerate(text.split("\n")):
        if i > 0:
            rendered.append("")
        if not paragraph:
            rendered.append("")
            continue
        wrapped = textwrap.fill(
            paragraph,
            width=inner_width,
            break_long_words=False,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=False,
        )
        lines = wrapped.split("\n")
        for j, ln in enumerate(lines):
            prefix = first_indent if j == 0 else rest_indent
            rendered.append(prefix + ln)
    return "\n".join(rendered)


__all__ = [
    "Direction",
    "repl",
    "settings_menu",
    "confirm",
    "pick_language",
    "BANNER",
]
