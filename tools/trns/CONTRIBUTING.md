# Contributing to trns

Thanks for helping! trns is deliberately small: **standard library only**,
Python 3.9+, one code path for Linux, macOS, Termux and Windows.

## Ground rules

- No third-party runtime dependencies. Dev tools are fine but not required.
- **Mobile first.** Any UI change must work at 40x12 before you look at 120x40.
- Everything visual goes through `core/view.py` (pure functions) so it can be
  tested. Terminal I/O belongs in `core/ui.py`; byte parsing in `core/keys.py`.
- Every action reachable by touch must also be reachable by keyboard, and
  vice versa.
- Respect `NO_COLOR` and the ASCII fallback: use the `utils.*` colour helpers
  and `theme.glyph(...)`, never raw escape codes or literal box-drawing glyphs.

## Running the tests

```bash
python -m unittest discover -s tests -t .
```

Tests must not touch the network. The layout tests assert that no rendered
line is ever wider than the screen across many sizes - if you fix a layout
bug, add your size to `SIZES` in `tests/test_view.py`.

## Trying the TUI

```bash
python trns.py            # then resize the terminal window
```

Termux input problems: `python trns.py --debug-input=keys.log`.

## Pull requests

1. Keep changes focused; update `CHANGELOG.md`.
2. Add or update tests.
3. Say what you tested and on which terminal(s).

By contributing you agree your work is released under the MIT license.
