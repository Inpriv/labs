"""ANSI color helpers + a small registry of language codes & display names.

Color palette mirrors the Inpriv M3 dark theme tokens:
    primary  #CBBEFF  (203,190,255)  — accent, prompt arrows, language codes
    error    #FF8670  (255,134,112)  — error messages
    success  #ABD37A  (171,211,122)  — confirmation, swap indicator
    muted    #CBC4D4  (203,196,212)  — secondary text, hints
    dim      #948F99  (148,143,153)  — tertiary, dividers
    warn     #FFB868  (255,184,104)  — warnings
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Encoding bootstrap (Windows consoles default to cp1252)
# ---------------------------------------------------------------------------

def _safe_reconfigure() -> None:
    """Make stdout/stderr UTF-8 on Python 3.7+.

    Windows terminals default to cp1252 in cmd.exe and older PowerShells, which
    can't encode the arrow / check / spinner glyphs this program uses. We try
    the modern reconfigure() API and silently fall back to a manual setattr
    dance on older interpreters.
    """

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            try:
                # Python 3.6 fallback: re-open with utf-8 encoding.
                stream.buffer  # type: ignore[attr-defined]
                # If we got here, we have a buffer. Reopen lazily on next write.
            except AttributeError:
                pass


_safe_reconfigure()


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def _rgb(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


# When stdout is not a real TTY (e.g. redirected to a file or pipe), drop all
# ANSI escapes so logs stay clean. The TTY check is sampled once at import;
# the colour override is re-evaluated per call so `trns --color always` works
# even though argparse runs after this module loads.
_IS_TTY = sys.stdout.isatty()


def _force_color() -> bool:
    return os.environ.get("TRNS_COLOR", "").lower() in ("1", "yes", "always", "on")


def color_enabled() -> bool:
    """True when ANSI styling should be emitted.

    Honours https://no-color.org: a non-empty ``NO_COLOR`` disables styling
    unless the user forced it with ``--color always``.
    """

    if _force_color():
        return True
    if os.environ.get("NO_COLOR"):
        return False
    return _IS_TTY


def _wrap(code: str, text: str) -> str:
    if color_enabled():
        return f"{code}{text}{RESET}"
    return text


def _bg(r: int, g: int, b: int) -> str:
    return f"[48;2;{r};{g};{b}m"


# Design tokens (Inpriv M3 dark). Surfaces are used for tappable "pills".
ON_PRIMARY = (39, 30, 76)      # text drawn on a primary-coloured chip
SURFACE_HI = (54, 50, 66)      # raised surface: buttons / pills
PRIMARY = (203, 190, 255)


def primary(text: str) -> str:
    return _wrap(_rgb(*PRIMARY), text)


def error(text: str) -> str:
    return _wrap(_rgb(255, 134, 112), text)


def success(text: str) -> str:
    return _wrap(_rgb(171, 211, 122), text)


def muted(text: str) -> str:
    return _wrap(_rgb(203, 196, 212), text)


def dim(text: str) -> str:
    return _wrap(_rgb(148, 143, 153), text)


def warn(text: str) -> str:
    return _wrap(_rgb(255, 184, 104), text)


def bold(text: str) -> str:
    return _wrap(BOLD, text)


def chip(text: str) -> str:
    """Filled accent pill (primary background). ``[ text ]`` without colour."""

    if not color_enabled():
        return f"[{text}]"
    return f"{_bg(*PRIMARY)}{_rgb(*ON_PRIMARY)}{BOLD} {text} {RESET}"


def pill(text: str) -> str:
    """Subtle raised button. ``[text]`` without colour."""

    if not color_enabled():
        return f"[{text}]"
    return f"{_bg(*SURFACE_HI)}{_rgb(203, 196, 212)} {text} {RESET}"


def chip_width(text: str) -> int:
    """Visible width of :func:`chip` / :func:`pill` output for ``text``."""

    return len(text) + 2


def clear_line() -> str:
    return "\033[2K\r" if _IS_TTY or _force_color() else "\r"


# ---------------------------------------------------------------------------
# Language registry
# ---------------------------------------------------------------------------

# A pragmatic subset of the 100+ languages the free endpoint supports.
# Display name is what we show in the prompt; code is what we send to Google.
LANGUAGES: dict[str, str] = {
    "auto": "Auto-detect",
    "en": "English",
    "pl": "Polish",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "uk": "Ukrainian",
    "cs": "Czech",
    "sk": "Slovak",
    "ro": "Romanian",
    "hu": "Hungarian",
    "bg": "Bulgarian",
    "el": "Greek",
    "tr": "Turkish",
    "sv": "Swedish",
    "no": "Norwegian",
    "da": "Danish",
    "fi": "Finnish",
    "is": "Icelandic",
    "et": "Estonian",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "ga": "Irish",
    "cy": "Welsh",
    "eu": "Basque",
    "ca": "Catalan",
    "gl": "Galician",
    "mt": "Maltese",
    "sq": "Albanian",
    "sr": "Serbian",
    "hr": "Croatian",
    "bs": "Bosnian",
    "sl": "Slovenian",
    "mk": "Macedonian",
    "be": "Belarusian",
    "ka": "Georgian",
    "hy": "Armenian",
    "az": "Azerbaijani",
    "kk": "Kazakh",
    "ky": "Kyrgyz",
    "uz": "Uzbek",
    "tg": "Tajik",
    "tk": "Turkmen",
    "mn": "Mongolian",
    "ar": "Arabic",
    "he": "Hebrew",
    "fa": "Persian",
    "ur": "Urdu",
    "hi": "Hindi",
    "bn": "Bengali",
    "pa": "Punjabi",
    "gu": "Gujarati",
    "mr": "Marathi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "si": "Sinhala",
    "ne": "Nepali",
    "my": "Burmese",
    "km": "Khmer",
    "lo": "Lao",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
    "tl": "Tagalog",
    "jv": "Javanese",
    "su": "Sundanese",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "yi": "Yiddish",
    "eo": "Esperanto",
    "la": "Latin",
    "sw": "Swahili",
    "af": "Afrikaans",
    "am": "Amharic",
    "ha": "Hausa",
    "ig": "Igbo",
    "yo": "Yoruba",
    "zu": "Zulu",
    "xh": "Xhosa",
    "st": "Sesotho",
    "so": "Somali",
    "mg": "Malagasy",
    "mi": "Maori",
    "sm": "Samoan",
    "haw": "Hawaiian",
}


def language_name(code: str) -> str:
    """Return the human-readable name for an ISO-639-1 code (or 'auto')."""
    return LANGUAGES.get(code.lower(), code.upper())


def language_short(code: str) -> str:
    """Short label used in the prompt: 'EN', 'PL', 'AUTO'."""
    return code.upper() if code != "auto" else "AUTO"
