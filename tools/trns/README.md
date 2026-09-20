# trns — terminal translator

```
 _____  ____        _      ____
|_   _||  _ \      | |    / ____|
  | |  | |_) |_   _| |__ | (___  _ __   ___  _ __
  | |  |  _ <| | | | '_ \ \___ \| '_ \ / _ \| '_ \
 _| |_ | |_) | |_| | |_) |____) | | | | (_) | | | |
|_____|____/ \__,_|_.__/|_____/|_| |_|\___/|_| |_|
          translate · inpriv        v0.1.0
```

A tiny interactive translator for your terminal. Backed by Google's free
`/translate_a/single` endpoint, so there is **no API key** and **no
dependency** beyond Python itself.

> Part of the [Inpriv Labs](https://github.com/Inpriv/labs) family —
> privacy-first, zero-knowledge tooling.

## Features

- **Interactive REPL** — type a phrase, get a translation, hit <kbd>Tab</kbd> to swap
  direction.
- **Tab-to-swap** — while typing, press <kbd>Tab</kbd> to instantly reverse the
  source and target language.
- **One-shot mode** — `trns hello world` prints a translation and exits, so
  it stays scriptable.
- **Zero deps** — pure Python 3.9+ standard library.
- **Cross-shell PATH persistence** — first-run opt-in writes a sentinel
  block to `~/.bashrc` / `~/.zshrc` / `~/.profile` (or `$PREFIX/etc/profile.d/trns.sh`
  on Termux). `/path` toggles it idempotently.
- **Settings menu** — `/settings` lets you change languages, swap direction,
  or toggle the PATH entry at any time.
- **Works on Linux, macOS, Termux, and Windows** — same source tree.

## Quick start

### Linux, macOS, WSL, Termux (one command)

```bash
curl -fsSL https://raw.githubusercontent.com/Inpriv/labs/main/tools/trns/install.sh | bash
```

The installer:

1. Detects your distro and installs `python3` if missing.
2. Downloads the latest `trns` sources into `~/.local/share/trns/`.
3. Drops a launcher at `~/.local/bin/trns` (or `$PREFIX/bin/trns` on Termux).
4. Asks whether to add the launcher directory to your PATH — re-runnable
   with `--path-add` / `--path-skip`.

After the install finishes, **open a new terminal** (or `source ~/.bashrc`)
and try:

```bash
trns hello world               # English -> Polish (default)
trns --swap cześć              # reverse direction
trns --from pl --to en cześć   # explicit source/target
trns                           # interactive REPL
```

### Windows

Windows users can run the script directly from a checkout — the install
wizard is not yet wired for cmd / PowerShell. See **Manual install** below.

```powershell
git clone https://github.com/Inpriv/labs.git
cd labs\tools\trns
python trns.py
```

## Keyboard cheatsheet

| Key            | Action                                       |
|----------------|----------------------------------------------|
| <kbd>Enter</kbd>     | translate the buffered line                  |
| <kbd>Tab</kbd>       | swap source <-> target (prompt updates live) |
| <kbd>Ctrl</kbd>+<kbd>L</kbd> | clear the screen                      |
| <kbd>Ctrl</kbd>+<kbd>C</kbd> | exit cleanly                         |

Slash commands also work at the prompt:

| Command     | What it does                          |
|-------------|---------------------------------------|
| `/swap`     | swap source <-> target                |
| `/settings` | open the settings menu                |
| `/path`     | toggle the PATH entry                 |
| `/clear`    | clear the screen                      |
| `/help`     | show command help                     |
| `/quit`     | exit trns                             |

## Command-line flags

```text
trns                            start the interactive REPL
trns hello world                one-shot translation
trns --swap cześć               one-shot, reversed direction
trns --from pl --to en cześć    explicit source + target
trns --settings                 open the settings menu
trns --path-add                 add this folder to PATH and exit
trns --path-remove              remove this folder from PATH and exit
trns --where                    print install + config paths
trns --version                  print version
trns --color always             force ANSI colours even in pipes
```

## Manual install

If you prefer to install without the shell bootstrap (or you want a
specific version):

```bash
git clone https://github.com/Inpriv/labs.git
cd labs/tools/trns
# Linux desktop / WSL
install_to="$HOME/.local/share/trns"      # or any path you like
mkdir -p "$install_to" "$HOME/.local/bin"
cp -R . "$install_to/"
ln -sf "$install_to/trns.py" "$HOME/.local/bin/trns"
"$HOME/.local/bin/trns" --path-add        # optional, writes to ~/.bashrc

# Termux
install_to="$PREFIX/share/trns"
mkdir -p "$install_to" "$PREFIX/bin"
cp -R . "$install_to/"
ln -sf "$install_to/trns.py" "$PREFIX/bin/trns"
```

The launcher is intentionally a 3-line wrapper around `trns.py` so future
updates can replace the sources without touching your shell `PATH`.

## Configuration

Stored at `~/.trns/config.json` (overridable via `$TRNS_HOME`):

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

Edit it directly, or change anything from `/settings`. The file is JSON with
two-space indentation and UTF-8 (no BOM).

## Project layout

```
trns/
├── trns.py            # CLI entry point, first-run wizard, arg parsing
├── install.sh         # apt/pacman/dnf/apk/pkg + XDG bootstrapper
├── core/
│   ├── __init__.py
│   ├── translator.py  # urllib client for translate.googleapis.com
│   ├── config.py      # JSON config + cross-platform PATH manipulation
│   ├── utils.py       # ANSI colour helpers + language registry
│   └── ui.py          # REPL, settings menu, line editor
├── requirements.txt   # (empty — stdlib only)
├── LICENSE
└── README.md
```

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/Inpriv/labs/main/tools/trns/install.sh \
  | bash -s -- --uninstall
```

This removes the data directory, the launcher, the `~/.trns` config, and
strips the sentinel block from your shell rc files.

## Notes

- **Privacy:** the script never logs your translations. They go straight to
  the Google endpoint and back, with a desktop browser User-Agent.
- **Limits:** input is capped at 4500 characters per call to stay under
  Google's URL-length ceiling.
- **Offline:** a quick connectivity probe runs at startup; if it fails you
  get a warning but can still poke around in `/settings`.

## License

MIT — same as the rest of the Inpriv Labs suite.