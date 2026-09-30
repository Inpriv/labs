"""Pure rendering for the trns TUI.

Nothing in here touches the terminal: every function takes plain data and
returns strings (plus tap targets), so the whole interface can be unit-tested
at any screen size — see ``tests/test_view.py``.

Screen anatomy (rows are 1-based; ``R`` = terminal height)::

    1      ◆ trns  translate · Inpriv              [ EN ⇄ PL ]   <- top bar
    2      ───────────────────────────────────────────────────
    3..    EN ▎ Hello, how are you?                             <- history
           PL ▎ Cześć, jak się masz?                               (cards)
    R-2    ───────────────────────────────────────────────────
    R-1     swap   copy   menu   clear                          <- action bar
    R      ❯ type here…                                         <- input

Every accent element is also a *tap target* (``Hit``): the language chip and
action pills for touch screens, history cards to copy a translation. Keyboard
users get the same actions through Tab, ``^L`` and slash commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from . import utils
from .direction import Direction
from .keys import char_width
from .theme import Layout, glyph

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

LABEL_W = 3                 # language code column on history cards
CARD_PREFIX = 1 + LABEL_W + 1 + 1 + 1   # margin, label, space, rail, space


# ---------------------------------------------------------------------------
# Text primitives (width-aware, ANSI-aware)
# ---------------------------------------------------------------------------


def visible_width(text: str) -> int:
    """Terminal columns occupied by ``text`` (ANSI codes and wide chars)."""

    return sum(char_width(c) for c in _ANSI.sub("", text))


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - visible_width(text))


def truncate(text: str, width: int) -> str:
    """Shorten plain ``text`` to ``width`` columns with a trailing ellipsis."""

    if width <= 0:
        return ""
    if visible_width(text) <= width:
        return text
    ell = glyph("ellipsis")
    budget = width - visible_width(ell)
    out, used = [], 0
    for ch in text:
        w = char_width(ch)
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return "".join(out) + ell


def truncate_middle(text: str, width: int) -> str:
    """Keep both ends of a long path: ``/home/…/config.json``."""

    if visible_width(text) <= width:
        return text
    ell = glyph("ellipsis")
    keep = max(2, width - len(ell))
    head = keep // 3
    tail = keep - head
    return text[:head] + ell + text[-tail:]


def wrap(text: str, width: int) -> List[str]:
    """Greedy word-wrap that understands wide characters.

    Paragraph breaks are preserved; words longer than ``width`` are broken
    by column so nothing can ever overflow the screen (CJK has no spaces).
    """

    width = max(4, width)
    out: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            out.append("")
            continue
        line, used = "", 0
        for word in paragraph.split(" "):
            w = visible_width(word)
            if w > width:
                # flush, then hard-break the long token
                if line:
                    out.append(line)
                    line, used = "", 0
                chunk, cused = "", 0
                for ch in word:
                    cw = char_width(ch)
                    if cused + cw > width:
                        out.append(chunk)
                        chunk, cused = "", 0
                    chunk += ch
                    cused += cw
                line, used = chunk, cused
                continue
            extra = w if not line else w + 1
            if used + extra > width:
                out.append(line)
                line, used = word, w
            else:
                line = word if not line else f"{line} {word}"
                used += extra
        out.append(line)
    return out


def rule(width: int, label: str = "") -> str:
    """Dim horizontal divider with a 1-column margin, optional right label."""

    ch = glyph("rule")
    if label and visible_width(label) + 6 < width:
        left = ch * (width - visible_width(label) - 4)
        return f" {utils.dim(left)} {utils.dim(label)} {utils.dim(ch)}"
    return f" {utils.dim(ch * width)}"


# ---------------------------------------------------------------------------
# Tap targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    """A clickable/tappable rectangle. Rows/cols are 1-based and inclusive."""

    row0: int
    row1: int
    x0: int
    x1: int
    action: str
    arg: Optional[int] = None

    def contains(self, x: int, y: int) -> bool:
        return self.row0 <= y <= self.row1 and self.x0 <= x <= self.x1


def hit_at(hits: Sequence[Hit], x: int, y: int) -> Optional[Hit]:
    for h in hits:
        if h.contains(x, y):
            return h
    return None


@dataclass
class Frame:
    """One fully-rendered screen minus the input row."""

    lines: List[str]                    # rows 1 .. rows-1
    hits: List[Hit] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Top bar
# ---------------------------------------------------------------------------


def _lang_chip_text(lay: Layout, d: Direction) -> str:
    swap = glyph("swap")
    if lay.mode == "wide":
        s, t = utils.language_name(d.source), utils.language_name(d.target)
    else:
        s, t = utils.language_short(d.source), utils.language_short(d.target)
    return f"{s} {swap} {t}"


def top_bar(lay: Layout, d: Direction) -> Tuple[str, List[Hit]]:
    brand_plain = f" {glyph('brand')} trns"
    left = f" {utils.primary(glyph('brand'))} {utils.bold('trns')}"
    if lay.mode != "compact":
        tag = f"  translate {glyph('dot')} Inpriv"
        left += utils.dim(tag)
        brand_plain += tag

    chip_text = _lang_chip_text(lay, d)
    chip_w = visible_width(chip_text) + 2
    max_chip = lay.cols - visible_width(brand_plain) - 3
    if chip_w > max_chip:
        chip_text = truncate(chip_text, max(4, max_chip - 2))
        chip_w = visible_width(chip_text) + 2

    gap = max(1, lay.cols - visible_width(brand_plain) - chip_w - 1)
    x0 = visible_width(brand_plain) + gap + 1
    x1 = x0 + chip_w - 1
    line = left + " " * gap + utils.chip(chip_text)
    # Two rows tall (bar + rule) and 1 column of slop each side: easy to tap.
    return line, [Hit(1, 2, max(1, x0 - 1), min(lay.cols, x1 + 1), "swap")]


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    text: str
    entry: Optional[int] = None    # index into history, for tap-to-copy


def _label(code: str) -> str:
    return code.split("-")[0].upper()[:LABEL_W]


def _card_rows(idx: int, entry: dict, lay: Layout) -> List[Row]:
    d: Direction = entry["direction"]
    text_w = min(lay.cols, 100) - CARD_PREFIX - 1
    rail = glyph("rail")
    src_code = d.source
    if src_code == "auto" and entry.get("detected"):
        src_code = entry["detected"]
    src_label = _label(src_code)
    dst_label = _label(d.target)

    rows: List[Row] = []
    for i, ln in enumerate(wrap(entry["input"], text_w)):
        label = pad(utils.dim(src_label), LABEL_W) if i == 0 else " " * LABEL_W
        rows.append(Row(f" {label} {utils.dim(rail)} {utils.muted(ln)}", idx))
    for i, ln in enumerate(wrap(entry["output"], text_w)):
        label = (pad(utils.bold(utils.primary(dst_label)), LABEL_W)
                 if i == 0 else " " * LABEL_W)
        rows.append(Row(f" {label} {utils.primary(rail)} {utils.bold(ln)}", idx))
    return rows


def _error_rows(entry: dict, lay: Layout) -> List[Row]:
    text_w = min(lay.cols, 100) - CARD_PREFIX - 1
    rail = utils.error(glyph("rail"))
    rows = []
    for i, ln in enumerate(wrap(entry["message"], text_w)):
        label = pad(utils.error("ERR"), LABEL_W) if i == 0 else " " * LABEL_W
        rows.append(Row(f" {label} {rail} {utils.error(ln)}"))
    return rows


def _empty_rows(lay: Layout, d: Direction) -> List[Row]:
    w = min(lay.cols, 100) - 4
    blocks = [
        ("Translate anything.", utils.bold),
        ("Type below, press Enter.", utils.muted),
        ("", utils.dim),
        (f"{d.label()}  {glyph('dot')}  tap the chip to flip", utils.dim),
        ("Tab swaps too. /help for commands.", utils.dim),
    ]
    rows: List[Row] = [Row("")]
    for text, paint in blocks:
        for ln in wrap(text, w):
            rows.append(Row(f"  {paint(ln)}" if ln else ""))
    return rows


def history_rows(history: Sequence[dict], lay: Layout, d: Direction) -> List[Row]:
    """All history as display rows (unclipped), cards separated by a blank."""

    if not history:
        return _empty_rows(lay, d)
    rows: List[Row] = []
    for idx, entry in enumerate(history):
        if entry["kind"] == "exchange":
            rows.extend(_card_rows(idx, entry, lay))
        elif entry["kind"] == "error":
            rows.extend(_error_rows(entry, lay))
        rows.append(Row(""))
    if rows:
        rows.pop()
    return rows


def max_scroll(history: Sequence[dict], lay: Layout, d: Direction) -> int:
    return max(0, len(history_rows(history, lay, d)) - lay.history_height)


def _viewport(rows: List[Row], height: int, offset: int,
              *, anchor_bottom: bool) -> Tuple[List[Row], int]:
    """Slice ``rows`` to ``height``; returns (visible, rows_hidden_below)."""

    if len(rows) <= height:
        blanks = [Row("")] * (height - len(rows))
        return (blanks + rows if anchor_bottom else rows + blanks), 0
    offset = max(0, min(offset, len(rows) - height))
    end = len(rows) - offset
    return rows[end - height:end], offset


# ---------------------------------------------------------------------------
# Action bar
# ---------------------------------------------------------------------------

_ACTIONS = (("swap", "swap"), ("copy", "copy"),
            ("menu", "settings"), ("clear", "clear"))


def action_bar(lay: Layout) -> Tuple[str, List[Hit]]:
    """Tappable pills, dropping the least important ones when space is tight."""

    avail = lay.cols - 2
    items = list(_ACTIONS)
    while items:
        total = sum(utils.chip_width(lbl) for lbl, _ in items) + (len(items) - 1)
        if total <= avail:
            break
        items.pop()                      # clear, then copy, then menu…
    x = 2
    parts: List[str] = []
    hits: List[Hit] = []
    row = lay.footer_row
    for lbl, action in items:
        w = utils.chip_width(lbl)
        parts.append(utils.pill(lbl))
        hits.append(Hit(row - 1, row, max(1, x - 1), x + w, action))
        x += w + 1
    line = " " + " ".join(parts)

    if lay.mode == "wide":
        hint = f"Tab swap {glyph('dot')} ^L clear {glyph('dot')} /help"
        used = sum(utils.chip_width(lbl) for lbl, _ in items) + len(items)
        if used + visible_width(hint) + 4 < lay.cols:
            gap = lay.cols - 1 - used - visible_width(hint) - 1
            line += " " * gap + utils.dim(hint)
    return line, hits


def toast_line(lay: Layout, message: str, kind: str) -> str:
    icon = {"ok": utils.success(glyph("ok")),
            "err": utils.error(glyph("err")),
            "warn": utils.warn(glyph("warn"))}.get(kind, utils.muted(glyph("info")))
    paint = {"ok": utils.success, "err": utils.error, "warn": utils.warn}.get(kind, utils.muted)
    return f" {icon} {paint(truncate(message, lay.cols - 5))}"


# ---------------------------------------------------------------------------
# Full frame
# ---------------------------------------------------------------------------


def render_frame(
    lay: Layout,
    d: Direction,
    history: Sequence[dict],
    *,
    scroll_offset: int = 0,
    toast: Optional[Tuple[str, str]] = None,
) -> Frame:
    """Render rows ``1 .. rows-1``. The input row is drawn by the editor."""

    lines: List[str] = [""] * (lay.rows - 1)
    hits: List[Hit] = []

    bar, bar_hits = top_bar(lay, d)
    lines[0] = bar
    hits.extend(bar_hits)
    lines[1] = rule(lay.width)

    rows = history_rows(history, lay, d)
    visible, below = _viewport(
        rows, lay.history_height, scroll_offset, anchor_bottom=bool(history),
    )
    for i, r in enumerate(visible):
        row_no = lay.history_top + i
        lines[row_no - 1] = r.text
        if r.entry is not None:
            hits.append(Hit(row_no, row_no, 1, lay.cols, "copy", r.entry))

    label = f"{glyph('down')} {below} newer" if below else ""
    lines[lay.bottom_rule_row - 1] = rule(lay.width, label)

    if lay.show_footer:
        if toast:
            lines[lay.footer_row - 1] = toast_line(lay, *toast)
        else:
            text, footer_hits = action_bar(lay)
            lines[lay.footer_row - 1] = text
            hits.extend(footer_hits)
    return Frame(lines, hits)


# ---------------------------------------------------------------------------
# One-shot card (CLI, non-interactive)
# ---------------------------------------------------------------------------


def oneshot_card(d: Direction, text: str, translated: str, cols: int,
                 detected: Optional[str] = None) -> List[str]:
    lay = Layout(cols, 24)
    entry = {"direction": d, "input": text, "output": translated,
             "detected": detected}
    return [r.text for r in _card_rows(0, entry, lay)]


# ---------------------------------------------------------------------------
# Menu / wizard building blocks (line-oriented screens)
# ---------------------------------------------------------------------------


def heading(title: str, width: int, subtitle: str = "") -> List[str]:
    out = [f" {utils.primary(glyph('brand'))} {utils.bold(title)}"]
    if subtitle:
        out[0] += "  " + utils.dim(truncate(subtitle, max(4, width - visible_width(title) - 6)))
    out.append(rule(width))
    return out


def menu_row(key: str, label: str, value: str, width: int) -> List[str]:
    """``1  Source language   English (en)`` — value drops below when narrow."""

    key_col = f" {utils.primary(pad(key, 2))} "
    plain_value = _ANSI.sub("", value)
    label_w = 16
    inline = 4 + label_w + visible_width(plain_value) <= width
    if inline:
        return [f"{key_col}{pad(label, label_w)}{value}"]
    out = [f"{key_col}{label}"]
    if value:
        out.append("    " + truncate_middle_styled(value, width - 5))
    return out


def truncate_middle_styled(value: str, width: int) -> str:
    plain = _ANSI.sub("", value)
    if visible_width(plain) <= width:
        return value
    return utils.dim(truncate_middle(plain, width))


def language_grid(codes: Sequence[str], width: int) -> List[str]:
    """Numbered picker cells, flowed into as many columns as fit."""

    if not codes:
        return []
    num_w = len(str(len(codes)))
    code_w = max(len(c) for c in codes)
    cells = [
        f"{utils.dim(pad(str(i), num_w))} {utils.primary(pad(c, code_w))} "
        f"{utils.language_name(c)}"
        for i, c in enumerate(codes, 1)
    ]
    cell_w = max(visible_width(c) for c in cells) + 3
    ncols = max(1, min(4, (width - 1) // cell_w))
    rows = []
    for i in range(0, len(cells), ncols):
        chunk = cells[i:i + ncols]
        rows.append(" " + "".join(pad(c, cell_w) for c in chunk[:-1]) + chunk[-1])
    return rows


def match_languages(query: str, codes: Sequence[str]) -> List[str]:
    """Filter ``codes`` by code or name; prefix matches first."""

    q = query.strip().lower()
    if not q:
        return list(codes)
    starts, contains = [], []
    for c in codes:
        name = utils.language_name(c).lower()
        if c == q or c.startswith(q) or name.startswith(q):
            starts.append(c)
        elif q in name or q in c:
            contains.append(c)
    return starts + contains
