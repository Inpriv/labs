<div align="center">

```
 _
| |_ _ __ _ __  ___
| __| '__| '_ \/ __|
| |_| |  | | | \__ \
 \__|_|  |_| |_|___/
```

### Translate without leaving the terminal.

A tiny, **mobile-first** terminal translator. Tap to swap languages, tap to copy.<br>
No API key. No account. No dependencies.

[![License: MIT](https://img.shields.io/badge/license-MIT-cbbeff?style=flat-square)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-cbbeff?style=flat-square)](https://www.python.org/)
[![Dependencies: none](https://img.shields.io/badge/dependencies-none-abd37a?style=flat-square)](requirements.txt)
[![Platforms](https://img.shields.io/badge/Linux%20%C2%B7%20macOS%20%C2%B7%20Termux%20%C2%B7%20Windows-555?style=flat-square)](#install)
[![Tests](https://img.shields.io/badge/tests-41%20passing-abd37a?style=flat-square)](#development)

[**Install**](#install) &nbsp;·&nbsp; [**Controls**](#controls) &nbsp;·&nbsp; [**Website**](site/) &nbsp;·&nbsp; [**Contribute**](CONTRIBUTING.md) &nbsp;·&nbsp; [**Changelog**](CHANGELOG.md)

<br>

<img src="docs/preview.svg" alt="trns in a narrow terminal: a top bar with an EN to PL language chip, translation cards, tappable action buttons and an input line" width="460">

<sub>Rendered from the real UI code at 42 columns - the width of a phone in portrait.</sub>

</div>

<br>

## Why trns

Most terminal translators assume a wide window and a hardware keyboard. trns
starts from the opposite end: a phone running [Termux](https://termux.dev),
portrait orientation, soft keyboard open (that can be **40 columns by 10
rows**). Everything else is that layout with more room.

- **Tap targets** - the language chip swaps direction, history cards copy,
  action buttons open settings. Soft keyboards have no <kbd>Tab</kbd>; you
  don't need one.
- **Never wraps** - the input line scrolls sideways, so a long sentence can't
  corrupt the screen.
- **Adapts live** - three responsive breakpoints; rotate your phone or resize
  the window and it re-lays out instantly.
- **Search-as-you-type language picker** - by number, code (`pl`) or name
  (`pol`).
- **Scriptable** - `trns hello` prints a card; piped, it prints *only* the
  translation.
- **Zero dependencies** - the Python 3.9+ standard library, nothing else.
- **Polite** - honours [`NO_COLOR`](https://no-color.org), falls back to ASCII
  glyphs (`TRNS_ASCII=1`), and never writes translations to disk.

## Install

### Linux, macOS, WSL, Termux

```bash
curl -fsSL https://raw.githubusercontent.com/Inpriv/labs/main/tools/trns/install.sh | bash
```

The installer detects your distro, installs `python3` if it's missing, drops
the sources in `~/.local/share/trns/`, creates a launcher at
`~/.local/bin/trns` (or `$PREFIX/bin/trns` on Termux), and **asks** before it
touches your PATH (`--path-add` / `--path-skip` to answer up front).

### Windows

```powershell
git clone https://github.com/Inpriv/labs.git
cd labs\tools\trns
.\install.bat        # adds this folder to your PATH; open a new terminal after
```

Or skip the installer and run `python trns.py` straight from the checkout.
Windows Terminal gives the best rendering.

### Try it

```bash
trns                           # interactive
trns hello world               # English -> Polish (default)
trns --swap cześć              # reverse direction
trns --from pl --to en cześć   # explicit languages
```

> **Termux tip:** `pkg install termux-api` (plus the Termux:API app) enables
> one-tap copy. Without it trns falls back to the OSC 52 escape sequence.

## Controls

| Touch / mouse            | Keyboard                          | Action                     |
|--------------------------|-----------------------------------|----------------------------|
| tap the **language chip**| <kbd>Tab</kbd>                    | swap source ⇄ target       |
| tap a **history card**   | `/copy` (most recent)             | copy that translation      |
| tap **menu**             | `/settings`                       | languages & PATH           |
| tap **clear**            | <kbd>Ctrl</kbd>+<kbd>L</kbd>      | clear history              |
| swipe / wheel            | <kbd>PgUp</kbd> <kbd>PgDn</kbd> <kbd>↑</kbd> <kbd>↓</kbd> | scroll back |
| tap the input line       | <kbd>←</kbd> <kbd>→</kbd> <kbd>Home</kbd> <kbd>End</kbd> | move the cursor |
| -                        | <kbd>Enter</kbd>                  | translate                  |
| -                        | <kbd>Ctrl</kbd>+<kbd>C</kbd>      | exit                       |

Slash commands: `/swap` `/copy` `/settings` `/path` `/clear` `/help` `/quit`.

## Command line

```text
trns                            interactive REPL
trns hello world                one-shot translation
trns --swap cześć               one-shot, reversed direction
trns --from pl --to en cześć    explicit source + target
trns --settings                 open the settings menu
trns --path-add | --path-remove add / remove this folder on PATH, then exit
trns --where                    print install + config paths
trns --version                  print version
trns --color always|never|auto  control ANSI colour
trns --debug-input=keys.log     log raw key bytes (Termux keyboard debugging)
```

| Environment   | Effect                                   |
|---------------|------------------------------------------|
| `NO_COLOR`    | disable colour                           |
| `TRNS_ASCII=1`| ASCII glyphs instead of Unicode          |
| `TRNS_HOME`   | relocate the config directory            |

## Configuration

Stored at `~/.trns/config.json` (`%USERPROFILE%\.trns\config.json` on Windows):

```json
{
  "version": 1,
  "first_run_done": true,
  "path_opt_in": true,
  "path_dir": "/home/you/.local/share/trns",
  "source": "en",
  "target": "pl"
}
```

Edit it directly or use `/settings`. UTF-8, two-space indent, no BOM.

## Project website (installable PWA)

[`site/`](site/) is a single static page - no build step - with a live demo of
the interface. It ships a web manifest and a service worker, so it can be
added to a phone's home screen and works offline. Deploy the folder to
GitHub Pages, Cloudflare Pages, or anything that serves static files:

```bash
python -m http.server -d site 8080     # preview at http://localhost:8080
```

## How it's built

```
trns/
├── trns.py            CLI entry point, first-run wizard, argument parsing
├── install.sh         Linux / macOS / Termux bootstrapper
├── install.bat  trns.bat  uninstall.bat      Windows helpers
├── core/
│   ├── translator.py  urllib client for translate.googleapis.com
│   ├── config.py      JSON config + cross-platform PATH handling
│   ├── theme.py       glyph sets + responsive layout breakpoints
│   ├── view.py        pure rendering: frames, cards, tap targets
│   ├── keys.py        raw keyboard / mouse input parser
│   ├── ui.py          REPL, line editor, settings, language picker
│   ├── direction.py   source -> target value object
│   ├── clipboard.py   cross-platform copy
│   └── utils.py       colour tokens + language registry
├── tests/             stdlib unittest, no network
├── site/              project website + PWA
└── docs/              README assets
```

The rendering layer (`view.py`) never touches the terminal: it turns state
into strings and tap rectangles. That is what makes the interface testable -
the suite asserts that **no line is ever wider than the screen** across
eleven sizes from 24 to 102 columns.

## Development

```bash
python -m unittest discover -s tests -t .    # 41 tests, no network
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) first: zero runtime dependencies,
mobile first, and every touch action needs a keyboard equivalent.

## Privacy & limits

- Text you translate is sent to Google's **public, unofficial** web endpoint
  (`translate.googleapis.com`) and nowhere else. It may rate-limit or change
  without notice and offers no guarantees beyond Google's own. **Don't send
  secrets.**
- trns keeps no history on disk; only the small config file above.
- Input is capped at 4,500 characters per request.
- A quick connectivity probe runs at startup; offline you still get a warning
  and a working settings menu.
- Vulnerabilities: see [SECURITY.md](SECURITY.md).

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/Inpriv/labs/main/tools/trns/install.sh | bash -s -- --uninstall
```

Removes the data directory, launcher, `~/.trns`, and the marked block in your
shell rc files. On Windows run `uninstall.bat`.

## License

[MIT](LICENSE) - part of the [Inpriv Labs](https://github.com/Inpriv/labs) family
of privacy-first tooling.
