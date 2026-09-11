"""
core.oui
=========

Two-tier MAC vendor lookup:

  1. Local override file (data/oui-overrides.txt) for known lab gear.
  2. Scapy's bundled IEEE OUI database (scapy.data.manuf).

Both tiers are cached in-process.
"""

from __future__ import annotations

import os
import threading
from typing import Iterable, Optional

from .utils import human_mac, log

_LOCK = threading.Lock()
_CACHE: dict[str, str] = {}
_MANUF = None
_OVERRIDES: dict[str, str] = {}


def _load_manuf():
    """Lazily import Scapy's manuf parser; returns None if unavailable."""
    global _MANUF
    if _MANUF is not None:
        return _MANUF

    try:
        from scapy.data import manuf  # type: ignore
    except Exception as e:  # pragma: no cover
        log.debug("scapy.data.manuf unavailable: %s", e)
        _MANUF = False  # sentinel so we don't retry
        return None

    _MANUF = manuf
    return _MANUF


def _load_overrides(path: str = "data/oui-overrides.txt") -> None:
    """Load local vendor overrides. Format per line: `00:11:22 Vendor Name`."""
    global _OVERRIDES
    if _OVERRIDES or not os.path.isfile(path):
        return

    out: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    oui, name = line.split("=", 1)
                elif "," in line:
                    oui, name = line.split(",", 1)
                else:
                    parts = line.split(maxsplit=1)
                    if len(parts) != 2:
                        continue
                    oui, name = parts
                out[human_mac(oui).rstrip(":")[:8]] = name.strip()
    except OSError as e:
        log.debug("Could not load %s: %s", path, e)
        return

    _OVERRIDES = out
    if out:
        log.debug("Loaded %d OUI overrides", len(out))


def lookup(mac: str) -> str:
    """Return the vendor name for a MAC address, or 'Unknown'."""
    normalized = human_mac(mac)
    if not normalized or len(normalized) < 8:
        return "Unknown"

    oui_key = normalized[:8]  # OUI = first 24 bits

    with _LOCK:
        if oui_key in _CACHE:
            return _CACHE[oui_key]

    _load_overrides()
    name: Optional[str] = _OVERRIDES.get(oui_key)

    if name is None:
        manuf = _load_manuf()
        if manuf is not None:
            try:
                hit = manuf.manuf.get(normalized.replace(":", "")[:6])  # type: ignore[union-attr]
                if hit and not hit.startswith("Private"):
                    name = hit.replace("_", " ").strip()
            except Exception:
                pass

    if not name:
        name = "Unknown"

    with _LOCK:
        _CACHE[oui_key] = name
    return name


def warm_cache(macs: Iterable[str]) -> None:
    """Pre-populate the vendor cache for a batch of MACs."""
    for mac in macs:
        lookup(mac)
