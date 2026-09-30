"""Design tokens for the trns TUI: glyph sets and responsive breakpoints.

Colours live in :mod:`core.utils`; this module owns everything else that
defines how the interface *looks* — which glyphs to draw and how the layout
adapts to the terminal size.

The layout is designed mobile-first: the ``compact`` breakpoint targets a
phone in portrait (Termux, ~35-50 columns, and as few as 8 rows while the
soft keyboard is open). Larger terminals only ever *add* to it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Dict


# ---------------------------------------------------------------------------
# Glyphs
# ---------------------------------------------------------------------------

_UNICODE: Dict[str, str] = {
    "brand": "◆",
    "arrow": "→",
    "swap": "⇄",
    "rail": "▎",
    "prompt": "❯",
    "ellipsis": "…",
    "rule": "─",
    "dot": "·",
    "ok": "✓",
    "err": "✗",
    "warn": "!",
    "info": "i",
    "up": "↑",
    "down": "↓",
    "more_left": "‹",
    "more_right": "›",
}

_ASCII: Dict[str, str] = {
    "brand": "*",
    "arrow": "->",
    "swap": "<>",
    "rail": "|",
    "prompt": ">",
    "ellipsis": "...",
    "rule": "-",
    "dot": ".",
    "ok": "+",
    "err": "x",
    "warn": "!",
    "info": "i",
    "up": "^",
    "down": "v",
    "more_left": "<",
    "more_right": ">",
}

SPINNER_UNICODE = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
SPINNER_ASCII = ["|", "/", "-", "\\"]


def use_ascii() -> bool:
    """True when the terminal cannot be trusted with box-drawing glyphs."""

    if os.environ.get("TRNS_ASCII"):
        return True
    if os.environ.get("TERM") == "linux":  # bare Linux VT console
        return True
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "utf" not in enc


def glyph(name: str) -> str:
    return (_ASCII if use_ascii() else _UNICODE)[name]


def spinner_frames() -> list:
    return SPINNER_ASCII if use_ascii() else SPINNER_UNICODE


# ---------------------------------------------------------------------------
# Responsive layout
# ---------------------------------------------------------------------------

COMPACT_MAX = 51      # < 52 columns  -> phone portrait
REGULAR_MAX = 89      # 52..89        -> phone landscape / small window
MAX_CONTENT = 100     # never stretch text wider than this

MIN_COLS = 24
MIN_ROWS = 6


@dataclass(frozen=True)
class Layout:
    """Everything the renderer needs to know about the screen."""

    cols: int
    rows: int

    @property
    def mode(self) -> str:
        if self.cols <= COMPACT_MAX:
            return "compact"
        if self.cols <= REGULAR_MAX:
            return "regular"
        return "wide"

    @property
    def width(self) -> int:
        """Usable content width (columns drawn on, margins excluded)."""

        return min(self.cols, MAX_CONTENT) - 2

    @property
    def show_footer(self) -> bool:
        """Hide the action bar when the soft keyboard leaves very few rows."""

        return self.rows >= 10

    @property
    def input_row(self) -> int:
        return self.rows

    @property
    def footer_row(self) -> int:
        return self.rows - 1 if self.show_footer else 0

    @property
    def bottom_rule_row(self) -> int:
        return self.rows - 2 if self.show_footer else self.rows - 1

    @property
    def history_top(self) -> int:
        return 3

    @property
    def history_height(self) -> int:
        return max(1, self.bottom_rule_row - self.history_top)


def clamp_size(cols: int, rows: int) -> tuple:
    return max(MIN_COLS, cols), max(MIN_ROWS, rows)
