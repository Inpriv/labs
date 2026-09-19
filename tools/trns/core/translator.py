"""Thin wrapper around Google's free /translate_a/single endpoint.

We deliberately avoid any third-party dependency so `trns` stays a single-file
install on Windows. The endpoint is the same one the public Google Translate
web app uses; it returns a non-standard nested JSON array, which we unwrap.

Returns:
    Translation(text=..., detected_source_lang=...)
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

# Conservative limits. The endpoint caps requests loosely; smaller = safer.
TIMEOUT_S = 10
MAX_CHARS = 4500  # Google's web UI uses ~5000; stay below to avoid 414/413.

ENDPOINT = "https://translate.googleapis.com/translate_a/single"


@dataclass
class Translation:
    """Result of a single translation call."""

    text: str
    detected_source_lang: Optional[str] = None  # only when source='auto'


class TranslationError(RuntimeError):
    """Raised when the endpoint is unreachable or returns junk."""


def _unwrap(payload) -> str:
    """Translate.googleapis.com returns a 3-level nested array.

    [
        [ [ "translated text", "source text", null, null, 10, ... ], ... ],
        null,
        "detected source lang (when sl=auto)",
        ...
    ]

    Each outer entry corresponds to one "sentence" the API split on, so we
    concatenate them with no separator (the API already inserts spaces where
    required between chunks).
    """

    try:
        sentences = payload[0]
        detected = payload[2] if len(payload) > 2 else None
    except (TypeError, IndexError):
        raise TranslationError("Malformed response from translation endpoint")

    out: list[str] = []
    for chunk in sentences:
        # chunks may be the empty list (rare) — skip cleanly
        if not isinstance(chunk, list) or not chunk:
            continue
        out.append(chunk[0] or "")
    return "".join(out), (detected or None)


def translate(text: str, source: str, target: str) -> Translation:
    """Translate `text` from `source` to `target`. `source` may be 'auto'."""

    text = text.strip()
    if not text:
        return Translation(text="", detected_source_lang=None)
    if source == target:
        return Translation(text=text, detected_source_lang=source)

    if len(text) > MAX_CHARS:
        raise TranslationError(
            f"Input is {len(text)} chars; the limit is {MAX_CHARS}. "
            "Try a shorter phrase."
        )

    params = {
        "client": "gtx",
        "sl": source,
        "tl": target,
        "dt": "t",          # we only need the translated text
        "ie": "UTF-8",
        "oe": "UTF-8",
        "q": text,
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        url,
        headers={
            # The endpoint is happy with a desktop UA. Anything that looks like
            # a real browser works; a bare python-urllib one gets blank 4xx.
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise TranslationError(
            f"Translation endpoint returned HTTP {e.code}. "
            "Check your internet connection or try a shorter phrase."
        ) from e
    except urllib.error.URLError as e:
        raise TranslationError(
            f"Could not reach translation endpoint: {e.reason}. "
            "Are you offline?"
        ) from e
    except TimeoutError:
        raise TranslationError("Translation request timed out.") from None
    except OSError as e:
        raise TranslationError(f"Network error: {e}") from e

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise TranslationError(f"Bad JSON from endpoint: {e}") from e

    translated, detected = _unwrap(payload)
    return Translation(text=translated, detected_source_lang=detected)


def translate_with_retry(text: str, source: str, target: str, *,
                         attempts: int = 3) -> Translation:
    """Retry once or twice on transient network blips."""

    last_exc: Optional[TranslationError] = None
    for i in range(attempts):
        try:
            return translate(text, source, target)
        except TranslationError as e:
            last_exc = e
            # Only retry on obvious transient failures.
            msg = str(e).lower()
            transient = (
                "timed out" in msg
                or "could not reach" in msg
                or "network error" in msg
                or "http 5" in msg
            )
            if not transient or i == attempts - 1:
                break
            time.sleep(0.6 * (i + 1))
    assert last_exc is not None
    raise last_exc


def is_offline() -> bool:
    """Quick connectivity probe — used at startup to surface a friendly error."""

    try:
        urllib.request.urlopen(
            "https://translate.googleapis.com/generate_204",
            timeout=3,
        )
        return False
    except Exception:
        return True


# Re-export for callers that prefer ``from translator import translate``.
__all__ = [
    "Translation",
    "TranslationError",
    "translate",
    "translate_with_retry",
    "is_offline",
    "MAX_CHARS",
]
