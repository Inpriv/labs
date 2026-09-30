#!/usr/bin/env python3
"""trns — a tiny interactive translator for your terminal.

Entry point. Handles:

* first-run wizard (asks whether to add the script's directory to user PATH)
* command-line arguments (``--once``, ``--lang``, ``--swap``, ``--settings``…)
* delegating to the REPL or one-shot translation

Invoke it directly as ``python trns.py`` or, once PATH setup has been
accepted, just ``trns``.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

# Make ``import core.*`` work whether you're running ``python trns.py`` from
# the source folder or ``trns`` from anywhere on PATH.
_HERE = os.path.dirname(os.path.realpath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core import config as config_mod
from core import __version__ as VERSION
from core import translator, ui, utils, view
from core.config import Config, add_to_path, remove_from_path
from core.direction import Direction
from core.theme import glyph


# ---------------------------------------------------------------------------
# First-run wizard
# ---------------------------------------------------------------------------


def _maybe_first_run(cfg: Config, script_dir: str) -> Config:
    """First launch only: PATH opt-in and default languages."""

    if cfg.first_run_done:
        return cfg

    print()
    print(utils.primary(ui.BANNER))
    print()
    print(f" {utils.bold('Welcome to trns.')} "
          f"{utils.muted('Two quick questions, then you are in.')}")

    # 1) PATH opt-in ------------------------------------------------------
    ui.step(1, 2, "Add 'trns' to your PATH?")
    print(utils.dim("    Lets you type  trns  in any new terminal."))
    print(utils.dim(f"    {script_dir}"))
    print()

    if ui.confirm("Add to PATH?", default=False):
        if add_to_path(script_dir):
            ui.notify("added to PATH", "ok")
            ui.notify("open a new terminal for this to take effect", "warn")
        else:
            ui.notify("already on PATH", "info")
        cfg.path_opt_in = True
    else:
        print(utils.dim("    no problem - enable it later from /settings."))
        cfg.path_opt_in = False
    cfg.path_dir = script_dir  # remembered so /settings can toggle it later

    # 2) Languages -------------------------------------------------------
    ui.step(2, 2, "Choose your languages")
    print(utils.dim("    Enter accepts the default (English to Polish)."))

    src = ui.pick_language("Translate from", default=config_mod.DEFAULT_SOURCE)
    if src:
        cfg.source = src
    tgt = ui.pick_language(
        "Translate to",
        exclude=cfg.source,
        default=config_mod.DEFAULT_TARGET,
        allow_auto=False,
    )
    if tgt:
        cfg.target = tgt

    print()
    print(f" {utils.success(glyph('ok'))} {utils.bold('All set.')} "
          f"{utils.muted(Direction(cfg.source, cfg.target).label())}")
    print()

    cfg.first_run_done = True
    cfg.save()
    return cfg


# ---------------------------------------------------------------------------
# One-shot translation (so trns is also scriptable)
# ---------------------------------------------------------------------------


def _oneshot(text: str, cfg: Config, *, swap: bool) -> int:
    direction = Direction(cfg.source, cfg.target)
    if swap:
        direction = direction.swapped()
    if not text.strip():
        ui.notify("nothing to translate (empty input)", "err")
        return 2
    try:
        result = translator.translate_with_retry(
            text, direction.source, direction.target
        )
    except translator.TranslationError as e:
        ui.notify(str(e), "err")
        return 1

    # Piped / redirected: emit only the translation so scripts can consume it.
    if not sys.stdout.isatty():
        print(result.text)
        return 0

    cols, _ = ui._terminal_size()
    print()
    for line in view.oneshot_card(
        direction, text, result.text, min(cols, 100),
        detected=result.detected_source_lang,
    ):
        print(line)
    print()
    return 0


# ---------------------------------------------------------------------------
# argparse plumbing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trns",
        description="Interactive terminal translator (translate.googleapis.com).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  trns                          start the interactive REPL\n"
            "  trns hello world              one-shot: translate 'hello world'\n"
            "  trns --swap hello world       one-shot, reversed direction\n"
            "  trns --from pl --to en cześć  one-shot with explicit languages\n"
            "  trns --settings               open the settings menu directly\n"
        ),
    )
    p.add_argument(
        "text", nargs="*",
        help="text to translate (when omitted, opens the interactive REPL)",
    )
    p.add_argument("--from", dest="source", help="source language code (e.g. en, pl, auto)")
    p.add_argument("--to", dest="target", help="target language code (e.g. en, pl)")
    p.add_argument("--swap", action="store_true",
                   help="swap source <-> target for this call only")
    p.add_argument("--settings", action="store_true",
                   help="open the settings menu instead of the REPL")
    p.add_argument("--path-add", action="store_true",
                   help="add this script's directory to user PATH and exit")
    p.add_argument("--path-remove", action="store_true",
                   help="remove this script's directory from user PATH and exit")
    p.add_argument("--where", action="store_true",
                   help="print the install + config paths and exit")
    p.add_argument("--version", action="store_true",
                   help="print the version and exit")
    p.add_argument("--color", choices=("auto", "always", "never"),
                   default="auto",
                   help="control ANSI colour output")
    p.add_argument("--debug-input", nargs="?", const="-", default=None, metavar="PATH",
                   help=("log every byte read from stdin to PATH (or stderr if '-') "
                         "with timestamps. Useful for diagnosing Termux / "
                         "Bluetooth-keyboard issues where a key (Tab, arrows) "
                         "does not reach the parser."))
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.color == "always":
        os.environ["TRNS_COLOR"] = "1"
    elif args.color == "never":
        os.environ.pop("TRNS_COLOR", None)

    # --debug-input: enable byte-level stdin tracing before any REPL runs.
    # "args.debug_input is not None" means the flag was passed; const="-"
    # means "no value" maps to stderr, any other value is treated as a path.
    if args.debug_input is not None:
        from core import keys as _keys_dbg
        _path = None if args.debug_input == "-" else args.debug_input
        _keys_dbg._set_debug_input(True, _path)

    script_dir = _HERE

    # --- early-exit commands ------------------------------------------
    if args.version:
        print(f"trns {VERSION}")
        return 0

    if args.where:
        print(f"script : {os.path.join(script_dir, 'trns.py')}")
        print(f"config : {Config.config_path()}")
        return 0

    if args.path_add:
        cfg = Config.load()
        cfg.path_dir = script_dir
        if add_to_path(script_dir):
            cfg.path_opt_in = True
            cfg.save()
            print(utils.success("added to PATH"))
        else:
            cfg.path_opt_in = True
            cfg.save()
            print(utils.dim("already on PATH"))
        return 0

    if args.path_remove:
        cfg = Config.load()
        if cfg.path_dir and remove_from_path(cfg.path_dir):
            cfg.path_opt_in = False
            cfg.save()
            print(utils.success("removed from PATH"))
        else:
            print(utils.dim("nothing to remove"))
        return 0

    # --- load + apply config -----------------------------------------
    cfg = Config.load()

    if args.source:
        cfg.source = args.source.lower()
    if args.target:
        cfg.target = args.target.lower()

    # --- settings shortcut -------------------------------------------
    if args.settings:
        cfg.first_run_done = True  # don't re-trigger the wizard
        changed = ui.settings_menu(cfg)
        if changed:
            cfg.save()
        return 0

    # --- first-run wizard --------------------------------------------
    # Only run the full interactive wizard when entering the REPL.
    # For one-shot CLI invocations we skip straight to translation so the
    # tool stays scriptable; the user can always run `trns --settings` or
    # `trns --path-add` later.
    if not cfg.first_run_done and not args.text:
        cfg = _maybe_first_run(cfg, script_dir)
        if not cfg.first_run_done:
            # Wizard was declined — adopt defaults so we don't re-ask.
            cfg.first_run_done = True
            cfg.path_dir = script_dir
            cfg.save()
    elif not cfg.first_run_done and args.text:
        cfg.first_run_done = True
        cfg.path_dir = script_dir
        cfg.save()

    # --- offline check -----------------------------------------------
    if translator.is_offline():
        print(utils.warn(
            "trns couldn't reach translate.googleapis.com. "
            "Check your internet connection."
        ))
        # Don't bail — the user might want to browse settings offline.

    # --- one-shot translation ----------------------------------------
    if args.text:
        return _oneshot(" ".join(args.text), cfg, swap=args.swap)

    # --- REPL --------------------------------------------------------
    try:
        rc = ui.repl(cfg)
    except KeyboardInterrupt:
        print()
        rc = 0

    cfg.save()
    return rc


if __name__ == "__main__":
    sys.exit(main())
