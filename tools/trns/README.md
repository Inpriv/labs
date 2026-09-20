# trns — terminal translator

```
 _
| |_ _ __ _ __  ___
| __| '''_\''_ \/ __|
| |_| |  | | | \__ \
 \__|_|  |_| |_|___/
```

A tiny interactive translator for your terminal. Backed by Google's free
`/translate_a/single` endpoint, so there is **no API key** and **no
dependency to install** beyond Python itself.

> Part of the [Inpriv](https://github.com/Inpriv) labs suite. See
> [`../inpriv-labs/inpriv-labs.md`](../inpriv-labs.md) for the design
> language this CLI borrows.

## Features

- **Interactive REPL** — type a phrase, get a translation, hit `Tab` to
  reverse the source/target direction in place. The text buffer, the
  caret and the selection survive the swap — only the language indicator
  in the header changes.
- **One-shot mode** — `trns hello world` prints a translation and exits,
  so the tool stays scriptable.
- **Tab-aware shortcuts** — `Tab` (swap direction), `Enter` (submit),
  `Ctrl+L` (clear the screen), `Ctrl+C` (quit), `Esc` (cancel mouse
  drag).
- **First-run PATH wizard** — on first launch, asks if you want `trns`
  available everywhere on the command line.
- **Settings menu** — `/settings` lets you change languages, swap
  direction, or toggle the PATH entry at any time.
- **Mouse selection & wheel scroll** — click-and-drag the prompt to
  select text; the wheel scrolls the translation history.
- **Polish, emoji, multi-byte UTF-8** — all editing operates on
  logical characters, not raw bytes.
- **No third-party dependencies** — pure Python 3.9+ standard library
  (`urllib`, `json`, `msvcrt`, …).
- **M3 dark colour palette** — matches the Inpriv web UI.

## Quick start

### Linux / macOS

```bash
git clone https://github.com/Inpriv/labs.git
cd labs/tools/trns
chmod +x install.sh
./install.sh                          # adds tools/trns/ to your user PATH
trns                                  # open the REPL
trns hello world                      # one-shot translation
trns --from pl --to en "dzień dobry"  # explicit source/target
trns --swap cześć                     # one-shot, reversed direction
```

Open a fresh terminal after `install.sh` so the updated `PATH` is picked
up by your shell.

### Windows

```cmd
git clone https://github.com/Inpriv/labs.git
cd labs\tools\trns
install.bat
:: (open a new terminal window afterwards)
trns
```

The first launch prints a tiny wizard:

1. **Add `trns` to your PATH?** (y/n)
2. **Pick default languages** (press Enter for English → Polish)

After that, the REPL starts. Type a phrase, press Enter, and the
translation appears below. Press `Tab` at any time to swap the
language direction.

## Keyboard cheatsheet

| Key       | Action                                                |
|-----------|-------------------------------------------------------|
| `Enter`   | translate the buffered line                           |
| `Tab`     | swap source/target (the prompt text never changes)    |
| `Ctrl+L`  | clear the screen (preserves history & input)          |
| `Ctrl+C`  | exit cleanly                                          |
| Mouse     | click + drag to select; wheel scrolls translation list |

Slash commands also work at the prompt:

| Command       | What it does                                    |
|---------------|-------------------------------------------------|
| `/swap`       | swap source/target                              |
| `/settings`   | open the settings menu                          |
| `/path`       | toggle the PATH entry                           |
| `/clear`      | clear the screen                                |
| `/help`       | show command help                               |
| `/quit`       | exit trns                                       |

## Command-line flags

```text
trns                            start the interactive REPL
trns hello world                one-shot: translate 'hello world'
trns --swap cześć               one-shot, reversed direction
trns --from pl --to en cześć    explicit source + target
trns --settings                 open the settings menu directly
trns --path-add                 add this folder to PATH and exit
trns --path-remove              remove this folder from PATH and exit
trns --where                    print install + config paths
trns --color always             force ANSI colours even in pipes
```

## Configuration

Stored at `~/.trns/config.json` (macOS/Linux) or
`%USERPROFILE%\.trns\config.json` (Windows):

```json
{
  "version": 1,
  "first_run_done": true,
  "path_opt_in": true,
  "path_dir": "/.../labs/tools/trns",
  "source": "en",
  "target": "pl"
}
```

Edit it directly, or change anything from `/settings`. The file is JSON
with two-space indentation and a UTF-8 BOM-free encoding.

## Project layout

```
trns/
├── trns.py             # CLI entry point, first-run wizard, arg parsing
├── core/
│   ├── __init__.py
│   ├── translator.py   # urllib client for translate.googleapis.com
│   ├── config.py       # JSON config + cross-platform PATH manipulation
│   ├── utils.py        # ANSI colour helpers + language registry
│   └── ui.py           # REPL, settings menu, line editor
├── install.sh          # Linux/macOS installer (PATH opt-in)
├── install.bat         # Windows installer
├── uninstall.bat       # Windows uninstaller
├── trns.bat            # Windows launcher (used when on PATH)
├── requirements.txt    # (empty — stdlib only)
└── README.md
```

## Notes

- **Privacy:** the script never logs your translations. They go straight
  to the Google endpoint and back, with a desktop browser User-Agent.
- **Limits:** input is capped at 4500 characters per call to stay under
  Google's URL-length ceiling.
- **Offline:** a quick connectivity probe runs at startup; if it fails
  you get a warning but can still poke around in `/settings`.

## License

MIT — same as the rest of the Inpriv suite.
