"""Interactive REPL, line editor and menus for trns.

Layered like this (each layer only talks to the one below it):

    keys.py    raw bytes  -> key / mouse events
    ui.py      events     -> editor state, commands, screens   (this module)
    view.py    state      -> strings + tap targets             (pure, tested)
    theme.py   glyphs and responsive breakpoints

The REPL is mobile-first. It runs in the alternate screen, never lets the
input line wrap (it scrolls horizontally instead), reacts to taps on the
language chip / action pills / history cards, follows terminal rotation
(SIGWINCH), and keeps every action reachable without a hardware keyboard.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import sys
import threading
import time
from typing import Callable, List, Optional, Tuple

from . import clipboard, keys, utils, view
from .direction import Direction
from .theme import Layout, MAX_CONTENT, clamp_size, glyph, spinner_frames
from .translator import (
    MAX_CHARS,
    Translation,
    TranslationError,
    translate_with_retry,
)

BANNER = r""" _
| |_ _ __ _ __  ___
| __| '__| '_ \/ __|
| |_| |  | | | \__ \
 \__|_|  |_| |_|___/"""

PROMPT_W = 3          # " ❯ "

# ---------------------------------------------------------------------------
# Terminal plumbing
# ---------------------------------------------------------------------------

_MOUSE_ON = "\033[?1000h\033[?1006h"
_MOUSE_OFF = "\033[?1006l\033[?1000l"
_ALT_ON = "\033[?1049h"
_ALT_OFF = "\033[?1049l"

_saved_tty = None


def _tty_cbreak_on() -> None:
    """Deliver keys byte-by-byte without echo (POSIX). No-op on Windows,
    where ``msvcrt`` already does exactly that."""

    global _saved_tty
    if sys.platform == "win32" or _saved_tty is not None:
        return
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        _saved_tty = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    except (ImportError, OSError, ValueError):
        _saved_tty = None


def _tty_cbreak_off() -> None:
    global _saved_tty
    if _saved_tty is None:
        return
    try:
        import termios

        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _saved_tty)
    except (ImportError, OSError, ValueError):
        pass
    _saved_tty = None


def _terminal_size(default: Tuple[int, int] = (80, 24)) -> Tuple[int, int]:
    try:
        size = shutil.get_terminal_size(default)
        cols, rows = size.columns, size.lines
    except (OSError, ValueError):
        cols, rows = default
    return clamp_size(cols or default[0], rows or default[1])


def _layout() -> Layout:
    cols, rows = _terminal_size()
    return Layout(min(cols, MAX_CONTENT + 2), rows)


def _content_width() -> int:
    """Width for line-oriented screens (menus, help, wizard)."""

    return _layout().width


@contextlib.contextmanager
def plain_screen():
    """Temporarily leave the TUI for a normal line-oriented screen.

    Mouse reporting is switched off (otherwise taps would be typed into
    ``input()`` as escape garbage) and the tty returns to cooked mode.
    """

    was_cbreak = _saved_tty is not None
    if was_cbreak:
        _tty_cbreak_off()
    if utils._IS_TTY:
        sys.stdout.write(_MOUSE_OFF + "\033[2J\033[H\033[?25h")
        sys.stdout.flush()
    try:
        yield
    finally:
        if was_cbreak:
            _tty_cbreak_on()
        if utils._IS_TTY:
            sys.stdout.write(_MOUSE_ON)
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# Small printing helpers
# ---------------------------------------------------------------------------


def emit(lines: List[str]) -> None:
    print("\n".join(lines))


def heading(title: str, subtitle: str = "") -> None:
    print()
    emit(view.heading(title, _content_width(), subtitle))


def step(n: int, total: int, title: str) -> None:
    print()
    print(f" {utils.primary(f'{n}/{total}')}  {utils.bold(title)}")


def notify(message: str, kind: str = "info") -> None:
    icon = {
        "info": utils.muted(glyph("info")),
        "ok": utils.success(glyph("ok")),
        "warn": utils.warn(glyph("warn")),
        "err": utils.error(glyph("err")),
    }.get(kind, utils.muted(glyph("info")))
    print(f"  {icon} {message}")


def confirm(question: str, *, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            raw = input(f"  {utils.bold(question)} {utils.dim(suffix)} ").strip().lower()
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
        input(utils.dim("  press Enter to continue" + glyph("ellipsis")))
    except (EOFError, KeyboardInterrupt):
        print()


def _ask(prompt: str = "") -> str:
    return input(f" {utils.primary(glyph('prompt'))} {prompt}").strip()


# ---------------------------------------------------------------------------
# Language picker
# ---------------------------------------------------------------------------

_COMMON = [
    "en", "pl", "de", "fr", "es", "it", "pt", "nl",
    "ru", "uk", "cs", "sk", "ro", "hu", "tr", "sv",
    "ja", "ko", "zh", "ar", "hi",
]


def pick_language(question: str, *, exclude: Optional[str] = None,
                  default: Optional[str] = None,
                  allow_auto: bool = True) -> Optional[str]:
    """Numbered picker with search: a number, a code, or part of a name."""

    def universe() -> List[str]:
        codes = sorted(utils.LANGUAGES, key=lambda c: (c != "auto", c))
        return [c for c in codes if c != exclude and (allow_auto or c != "auto")]

    shown = [c for c in _COMMON if c != exclude]
    if allow_auto and "auto" not in shown:
        shown.insert(0, "auto")
    if default and default not in shown and default != exclude:
        shown.insert(0, default)

    while True:
        heading(question)
        emit(view.language_grid(shown, _content_width()))
        default_name = utils.language_name(default) if default else "auto"
        print()
        print(utils.dim(
            f"  number, code or name {glyph('dot')} Enter = {default_name} "
            f"{glyph('dot')} 'all' {glyph('dot')} 'q'"))
        try:
            raw = _ask().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if not raw:
            return default
        if raw in ("q", "quit", "cancel", "exit"):
            return None
        if raw in ("all", "more", "m"):
            shown = universe()
            continue
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(shown):
                return shown[idx]
            notify(f"pick a number between 1 and {len(shown)}", "err")
            continue
        if raw in utils.LANGUAGES and raw in universe():
            return raw

        matches = view.match_languages(raw, universe())
        if len(matches) == 1:
            return matches[0]
        if not matches:
            notify(f"nothing matches {raw!r}", "err")
        else:
            shown = matches


# ---------------------------------------------------------------------------
# Prompt rendering (single line, scrolls horizontally, never wraps)
# ---------------------------------------------------------------------------


def _prompt_prefix() -> str:
    return f" {utils.primary(glyph('prompt'))} "


def prompt_window(buf: List[str], cursor: int, avail: int) -> Tuple[int, int, int, int]:
    """Choose which slice of ``buf`` is visible on the input row.

    Returns ``(start, end, left_marker_cols, right_marker_cols)``. When the
    text fits, the window is everything and no markers are drawn; otherwise
    it follows the cursor and ``‹`` / ``›`` mark the clipped sides.
    """

    if keys.buffered_width(buf) <= avail:
        return 0, len(buf), 0, 0

    inner = max(4, avail - 2)
    left_budget = inner * 2 // 3
    s, w = cursor, 0
    while s > 0 and w + keys.char_width(buf[s - 1]) <= left_budget:
        s -= 1
        w += keys.char_width(buf[s])
    e = cursor
    while e < len(buf) and w + keys.char_width(buf[e]) <= inner:
        w += keys.char_width(buf[e])
        e += 1
    while s > 0 and w + keys.char_width(buf[s - 1]) <= inner:   # leftover room
        s -= 1
        w += keys.char_width(buf[s])
    return s, e, (1 if s > 0 else 0), (1 if e < len(buf) else 0)


def _avail(cols: int) -> int:
    return cols - PROMPT_W - 1


def _redraw_prompt(
    buf: List[str],
    cursor_pos: int,
    sel_start: Optional[int] = None,
    sel_end: Optional[int] = None,
) -> None:
    """Single source of truth for the input row (always the last row)."""

    cols, rows = _terminal_size()
    s, e, lm, rm = prompt_window(buf, cursor_pos, _avail(cols))

    out = [f"\033[{rows};1H\033[2K", _prompt_prefix()]
    if lm:
        out.append(utils.dim(glyph("more_left")))

    has_sel = sel_start is not None and sel_end is not None and sel_start != sel_end
    if has_sel:
        lo = max(s, min(sel_start, sel_end))
        hi = min(e, max(sel_start, sel_end))
    if has_sel and lo < hi:
        out += ["".join(buf[s:lo]), "\033[7m", "".join(buf[lo:hi]), "\033[27m",
                "".join(buf[hi:e])]
    else:
        out.append("".join(buf[s:e]))

    if rm:
        out.append(utils.dim(glyph("more_right")))
    back = keys.buffered_width(buf[cursor_pos:e]) + rm
    if back > 0:
        out.append(f"\033[{back}D")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def _erase_columns(width: int) -> None:
    if width <= 0:
        return
    sys.stdout.write(f"\033[{width}D" + " " * width + f"\033[{width}D")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Frame painting
# ---------------------------------------------------------------------------


def paint(direction: Direction, history: List[dict], buf: List[str],
          cursor: int, *, scroll_offset: int = 0,
          toast: Optional[Tuple[str, str]] = None,
          clear: bool = False) -> view.Frame:
    """Draw the whole screen (rows are addressed absolutely: no scrolling,
    no flicker) and return the frame so callers can hit-test taps."""

    lay = _layout()
    frame = view.render_frame(
        lay, direction, history, scroll_offset=scroll_offset, toast=toast,
    )
    out = ["\033[?25l"]
    if clear:
        out.append("\033[2J")
    for i, line in enumerate(frame.lines, 1):
        out.append(f"\033[{i};1H{line}\033[K")
    sys.stdout.write("".join(out))
    _redraw_prompt(buf, cursor)
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()
    return frame


# ---------------------------------------------------------------------------
# Line editor
# ---------------------------------------------------------------------------


def _read_line_at_prompt(
    initial: str = "",
    *,
    on_ctrl_l: Optional[Callable[[], None]] = None,
    on_scroll: Optional[Callable[[str], None]] = None,
    on_tab: Optional[Callable[[], None]] = None,
    on_text_change: Optional[Callable[[List[str], int], None]] = None,
    on_click: Optional[Callable[[int, int], Optional[str]]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Mouse-aware single-line editor on the bottom row.

    Returns ``(text, command)``:

    * ``(None, None)``   Ctrl+C / Ctrl+D / EOF -> leave the REPL
    * ``(text, None)``   Enter pressed
    * ``(text, "/cmd")`` a tap target asked for a slash command; the caller
                         keeps ``text`` so nothing the user typed is lost

    Selection is half-open ``[sel_start, sel_end)``; an empty range means
    "no selection".
    """

    buf: List[str] = list(initial)
    cursor_pos = len(buf)
    sel_start: Optional[int] = None
    sel_end: Optional[int] = None

    def publish() -> None:
        if on_text_change is not None:
            on_text_change(buf, cursor_pos)

    def has_selection() -> bool:
        return sel_start is not None and sel_end is not None and sel_start != sel_end

    def clear_selection() -> None:
        nonlocal sel_start, sel_end
        sel_start = sel_end = None

    def redraw() -> None:
        _redraw_prompt(buf, cursor_pos, sel_start, sel_end)
        publish()

    def delete_selection() -> None:
        nonlocal cursor_pos
        lo, hi = sorted([sel_start, sel_end])   # type: ignore[type-var]
        del buf[lo:hi]
        cursor_pos = lo
        clear_selection()

    redraw()

    while True:
        kind, payload = keys.read_input_unit()
        if kind is None:
            return None, None

        if kind == "char":
            if has_selection():
                delete_selection()
            width_after = keys.buffered_width(buf) + keys.char_width(payload)
            at_end = cursor_pos == len(buf)
            buf.insert(cursor_pos, payload)
            cursor_pos += 1
            cols, _ = _terminal_size()
            if at_end and width_after <= _avail(cols):
                sys.stdout.write(payload)        # fast path: no flicker
                sys.stdout.flush()
                publish()
            else:
                redraw()
            continue

        ch = payload

        if ch in (keys.CTRL_C, keys.CTRL_D):
            return None, None

        if ch in keys.CTRL_L:
            buf.clear()
            cursor_pos = 0
            clear_selection()
            publish()
            if on_ctrl_l is not None:
                on_ctrl_l()
            continue

        if ch == keys.ESC:
            action, params = keys.read_escape()
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
                redraw()
                continue

            if action == "delete":
                if has_selection():
                    delete_selection()
                elif cursor_pos < len(buf):
                    del buf[cursor_pos]
                redraw()
                continue

            if action in ("up", "down", "pageup", "pagedown",
                          "mouse_wheel_up", "mouse_wheel_down"):
                if on_scroll is not None:
                    on_scroll(action)
                continue

            if action == "mouse_event" and params is not None:
                x, y = params["x"], params["y"]
                _, rows = _terminal_size()
                if params["button"] != 0:
                    continue
                if y == rows:
                    cols, _ = _terminal_size()
                    s, _e, lm, _rm = prompt_window(buf, cursor_pos, _avail(cols))
                    col = max(0, x - PROMPT_W - 1 - lm)
                    pos = s + keys.column_to_index(buf[s:], col)
                    if params.get("release"):
                        if sel_start == sel_end:
                            clear_selection()
                            cursor_pos = pos
                    elif params.get("motion"):
                        if sel_start is None:
                            sel_start = cursor_pos
                        sel_end = pos
                    else:
                        sel_start = sel_end = pos
                    redraw()
                elif not params.get("motion") and not params.get("release"):
                    cmd = on_click(x, y) if on_click is not None else None
                    if cmd:
                        return "".join(buf), cmd
            continue

        if ch == keys.TAB:
            if on_tab is not None:
                on_tab()
            continue

        if ch in keys.ENTER:
            sys.stdout.write("\r\033[2K")     # leave the row for the spinner
            sys.stdout.flush()
            return "".join(buf), None

        if ch in keys.BACKSPACE:
            if has_selection():
                delete_selection()
                redraw()
                continue
            if cursor_pos == 0:
                continue
            cols, _ = _terminal_size()
            was_clipped = keys.buffered_width(buf) > _avail(cols)
            at_end = cursor_pos == len(buf)
            removed = buf.pop(cursor_pos - 1)
            cursor_pos -= 1
            if at_end and not was_clipped:
                _erase_columns(keys.char_width(removed))
                publish()
            else:
                redraw()
            continue

        # Everything else (unbound control keys): ignore.


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def settings_menu(cfg) -> bool:
    """Line-oriented settings screen. Returns True if anything changed."""

    mutated = False
    while True:
        w = _content_width()
        d = Direction(cfg.source, cfg.target)
        heading("Settings")
        print()
        rows = [
            ("1", "From", f"{utils.success(utils.language_name(cfg.source))} "
                          f"{utils.dim('(' + cfg.source + ')')}"),
            ("2", "To", f"{utils.success(utils.language_name(cfg.target))} "
                        f"{utils.dim('(' + cfg.target + ')')}"),
            ("3", "Swap", d.label()),
            ("4", "Add to PATH", utils.success("on") if cfg.path_opt_in
             else utils.warn("off")),
            ("5", "Config file", utils.dim(str(cfg.config_path()))),
            ("q", "Back", ""),
        ]
        for key, label, value in rows:
            emit(view.menu_row(key, label, value, w))
        print()

        try:
            choice = _ask().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice in ("q", "quit", "exit", "back", "0", ""):
            break
        elif choice == "1":
            new = pick_language("From language", exclude=cfg.target,
                                default=cfg.source)
            if new:
                cfg.source = new
                mutated = True
                notify(f"from {utils.language_name(new)}", "ok")
        elif choice == "2":
            new = pick_language("To language", exclude=cfg.source,
                                default=cfg.target, allow_auto=False)
            if new:
                cfg.target = new
                mutated = True
                notify(f"to {utils.language_name(new)}", "ok")
        elif choice == "3":
            swapped = d.swapped()
            cfg.source, cfg.target = swapped.source, swapped.target
            mutated = True
            notify(f"swapped {glyph('arrow')} {swapped.label()}", "ok")
        elif choice == "4":
            toggle_path(cfg)
            mutated = True
        elif choice == "5":
            notify(str(cfg.config_path()), "info")
            pause()
        else:
            notify("unknown option", "err")

    return mutated


def toggle_path(cfg) -> None:
    from . import config  # avoid import cycle

    if cfg.path_opt_in:
        if cfg.path_dir and config.path_contains(cfg.path_dir):
            if confirm(f"Remove trns from your PATH? ({cfg.path_dir})",
                       default=False):
                config.remove_from_path(cfg.path_dir)
                cfg.path_opt_in = False
                notify("removed from PATH", "ok")
                notify("open a new terminal for this to take effect", "warn")
            else:
                notify("cancelled", "info")
        else:
            cfg.path_opt_in = False
            notify("PATH entry was already gone", "info")
    else:
        if cfg.path_dir is None:
            notify("cannot enable: install directory not recorded", "err")
            return
        if confirm(f"Add trns to your PATH?\n  {utils.muted(cfg.path_dir)}\n ",
                   default=True):
            if config.add_to_path(cfg.path_dir):
                notify("added to PATH", "ok")
                notify("open a new terminal for this to take effect", "warn")
            else:
                notify("already on PATH", "info")
            cfg.path_opt_in = True
        else:
            notify("cancelled", "info")


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


class _Spinner:
    """Braille (or ASCII) spinner drawn on the input row while we wait."""

    def __init__(self, label: str) -> None:
        self.label = label
        self._stop = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "_Spinner":
        if utils.color_enabled():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        sys.stdout.write("\r\033[2K" if utils.color_enabled() else "\r")
        sys.stdout.flush()

    def _run(self) -> None:
        frames = spinner_frames()
        i = 0
        while not self._stop:
            sys.stdout.write(
                f"\r\033[2K {utils.primary(frames[i % len(frames)])} "
                f"{utils.dim(self.label)}"
            )
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1


def _help_lines() -> List[str]:
    w = _content_width()
    cmds = [
        ("/swap", "swap source and target"),
        ("/copy", "copy the last translation"),
        ("/settings", "languages and PATH"),
        ("/clear", "clear the history"),
        ("/help", "this screen"),
        ("/quit", "exit trns"),
    ]
    out = view.heading("Help", w)
    out.append("")
    for name, desc in cmds:
        out.append(f" {utils.primary(view.pad(name, 10))} {desc}")
    out += [
        "",
        utils.dim(f" tap   chip = swap {glyph('dot')} card = copy {glyph('dot')} "
                  "scroll = older"),
        utils.dim(f" keys  Tab swap {glyph('dot')} ^L clear {glyph('dot')} ^C quit"),
        "",
    ]
    return out


def repl(cfg) -> int:
    if not (utils._IS_TTY and sys.stdin.isatty()):
        print(utils.warn(
            "trns interactive mode needs a real terminal. "
            "Try `trns <phrase>` for one-shot translation."
        ))
        return 2

    if sys.platform == "win32":
        os.system("")          # enables ANSI/VT processing on Windows 10+

    direction = Direction(cfg.source, cfg.target)
    history: List[dict] = []
    carry = ""
    scroll_offset = 0
    toast: Optional[Tuple[str, str]] = None
    frame = view.Frame([])
    in_tui = True

    current_input: List[str] = []
    current_cursor = 0

    def repaint(*, clear: bool = False) -> None:
        nonlocal frame
        frame = paint(direction, history, current_input, current_cursor,
                      scroll_offset=scroll_offset, toast=toast, clear=clear)

    def capture(buf: List[str], cursor_pos: int) -> None:
        nonlocal current_input, current_cursor
        current_input = list(buf)
        current_cursor = cursor_pos

    def do_swap() -> None:
        nonlocal direction, toast
        direction = direction.swapped()
        cfg.source, cfg.target = direction.source, direction.target
        toast = None
        repaint()

    def do_clear() -> None:
        nonlocal scroll_offset, toast
        history.clear()
        scroll_offset = 0
        toast = None
        repaint()

    def do_copy(entry_index: Optional[int] = None) -> None:
        nonlocal toast
        if entry_index is None:
            done = [e for e in history if e["kind"] == "exchange"]
            entry = done[-1] if done else None
        else:
            entry = history[entry_index] if 0 <= entry_index < len(history) else None
        if not entry or entry["kind"] != "exchange":
            toast = ("nothing to copy yet", "warn")
        elif clipboard.copy(entry["output"]):
            toast = ("copied translation", "ok")
        else:
            toast = ("no clipboard available", "err")
        repaint()

    def on_scroll(action: str) -> None:
        nonlocal scroll_offset
        if not history:
            return
        lay = _layout()
        limit = view.max_scroll(history, lay, direction)
        page = max(1, lay.history_height - 1)
        step_ = {"up": 1, "mouse_wheel_up": 3, "pageup": page,
                 "down": -1, "mouse_wheel_down": -3, "pagedown": -page}.get(action)
        if step_ is None:
            return
        scroll_offset = max(0, min(scroll_offset + step_, limit))
        repaint()

    def on_click(x: int, y: int) -> Optional[str]:
        hit = view.hit_at(frame.hits, x, y)
        if hit is None:
            return None
        if hit.action == "swap":
            do_swap()
        elif hit.action == "copy":
            do_copy(hit.arg)
        elif hit.action == "menu":
            return "/settings"
        elif hit.action == "clear":
            return "/clear"
        return None

    def run_screen(render: Callable[[], None]) -> None:
        """Run a line-oriented screen, then return to the TUI."""
        nonlocal in_tui, direction
        in_tui = False
        with plain_screen():
            render()
        in_tui = True
        direction = Direction(cfg.source, cfg.target)

    def command(text: str) -> bool:
        """Run a slash command. Returns False to leave the REPL."""
        nonlocal toast
        cmd = text.split()[0].lower()
        if cmd in ("/quit", "/exit", "/q"):
            return False
        if cmd in ("/clear", "/cls"):
            do_clear()
        elif cmd in ("/swap", "/s"):
            do_swap()
        elif cmd in ("/copy", "/c"):
            do_copy()
        elif cmd in ("/help", "/?", "/h"):
            run_screen(lambda: (emit(_help_lines()), pause()))
        elif cmd in ("/settings", "/config", "/set"):
            def screen() -> None:
                if settings_menu(cfg):
                    cfg.save()
            run_screen(screen)
        elif cmd == "/path":
            def screen() -> None:
                heading("PATH")
                toggle_path(cfg)
                cfg.save()
                pause()
            run_screen(screen)
        else:
            toast = (f"unknown command {cmd} {glyph('dot')} try /help", "err")
        return True

    def on_winch(_sig, _frm) -> None:
        if in_tui:
            repaint(clear=True)

    old_winch = None
    if hasattr(signal, "SIGWINCH"):
        old_winch = signal.signal(signal.SIGWINCH, on_winch)

    _tty_cbreak_on()
    sys.stdout.write(_ALT_ON + _MOUSE_ON)
    sys.stdout.flush()

    try:
        while True:
            repaint(clear=True)
            try:
                text, cmd = _read_line_at_prompt(
                    initial=carry,
                    on_ctrl_l=do_clear,
                    on_scroll=on_scroll,
                    on_tab=do_swap,
                    on_text_change=capture,
                    on_click=on_click,
                )
            except (EOFError, KeyboardInterrupt):
                return 0
            if text is None:
                return 0

            if cmd:                               # tap target -> command
                carry = text                      # keep what was typed
                capture(list(carry), len(carry))
                if not command(cmd):
                    return 0
                continue

            carry = ""
            capture([], 0)
            toast = None
            text = text.strip()
            if not text:
                continue

            if text.startswith("/"):
                if not command(text):
                    return 0
                continue

            if len(text) > MAX_CHARS:
                history.append({
                    "kind": "error",
                    "message": f"input is {len(text)} chars (limit {MAX_CHARS}); "
                               "shorten it",
                })
                scroll_offset = 0
                continue

            spinner = _Spinner(
                f"translating {direction.label()}"
            ).start()
            try:
                result: Translation = translate_with_retry(
                    text, direction.source, direction.target,
                )
            except TranslationError as e:
                history.append({"kind": "error", "message": str(e)})
                scroll_offset = 0
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
        if old_winch is not None:
            signal.signal(signal.SIGWINCH, old_winch)
        sys.stdout.write(_MOUSE_OFF + "\033[?25h" + _ALT_OFF)
        sys.stdout.flush()
        _tty_cbreak_off()


__all__ = [
    "Direction",
    "BANNER",
    "repl",
    "settings_menu",
    "confirm",
    "pick_language",
    "notify",
    "heading",
    "step",
]
