"""trns — a tiny offline-feeling translator that talks to Google's free endpoint.

Modules:
    translator   — HTTP client for translate.googleapis.com
    config       — JSON-on-disk settings (languages, PATH opt-in, …)
    utils        — ANSI colour helpers, language names
    theme        — glyph sets and responsive layout breakpoints
    view         — pure rendering (frames, cards, tap targets)
    keys         — raw keyboard / mouse input parser
    ui           — REPL, line editor, settings menu
    clipboard    — best-effort cross-platform copy
"""

__version__ = "0.2.0"
__all__ = ["translator", "config", "utils", "theme", "view", "keys", "ui", "clipboard"]
