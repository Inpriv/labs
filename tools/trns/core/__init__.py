"""trns — a tiny offline-feeling translator that talks to Google's free endpoint.

Modules:
    translator   — HTTP client for translate.googleapis.com
    config       — JSON-on-disk settings (languages, PATH opt-in, …)
    utils        — ANSI color helpers, language names
    ui           — interactive prompts, REPL with Tab-to-swap, settings menu
"""

__version__ = "0.1.0"
__all__ = ["translator", "config", "utils", "ui"]
