"""
core — building blocks for the air CLI.

    interface  -> monitor-mode + channel control
    scanner    -> AP discovery + client correlation
    injector   -> deauth frame construction + injection
    oui        -> MAC vendor lookup
    utils      -> logging, colors, subprocess helpers
"""

__all__ = ["interface", "scanner", "injector", "oui", "utils"]
__version__ = "0.1.0"
