"""Translation direction (source -> target) value object."""

from __future__ import annotations

from dataclasses import dataclass

from . import utils
from .theme import glyph


@dataclass
class Direction:
    source: str
    target: str

    def swapped(self) -> "Direction":
        """Reverse the pair. ``auto`` can't be a target, so it degrades:
        auto -> X becomes X -> auto (detect-and-return), and vice versa."""

        if self.source == "auto":
            return Direction(source=self.target, target="auto")
        if self.target == "auto":
            return Direction(source="auto", target=self.source)
        return Direction(source=self.target, target=self.source)

    def label(self) -> str:
        s = utils.language_short(self.source)
        t = utils.language_short(self.target)
        return f"{s} {glyph('arrow')} {t}"

    def detailed(self) -> str:
        s = f"{utils.language_short(self.source)} ({utils.language_name(self.source)})"
        t = f"{utils.language_short(self.target)} ({utils.language_name(self.target)})"
        return f"{s} {glyph('arrow')} {t}"
