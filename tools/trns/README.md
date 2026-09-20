<<<<<<< HEAD
# trns — terminal translator

```
 _
| |_ _ __ _ __  ___
| __| '__| '_ \/ __|
| |_| |  | | | \__ \
 \__|_|  |_| |_|___/
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

---

## Android (TWA) & PWA companion

In addition to the CLI, this subtree ships a phone-friendly PWA and
an installable Android APK with identical translation behaviour.

| Path | What it is |
|---|---|
| `app/` | The PWA itself: HTML, CSS, JS, service worker, manifest, icons |
| `apk/` | Gradle project (bubblewrap-generated) producing `app-debug.apk` |
| `cloudflare-worker/` | Cloudflare Worker serving the PWA at `trns.inpriv.xyz` |

### Live

- **Production**: https://trns.inpriv.xyz
- **Fallback**: https://trns-pwa.saloyek.workers.dev
- **Digital Asset Links**: https://trns-pwa.saloyek.workers.dev/.well-known/assetlinks.json

The Android `asset_statements` string in
`apk/app/src/main/res/values/strings.xml` points at the same two
URLs — that is what lets the TWA open URLs in-app rather than
routing them through Chrome.

### Translation backend

Google's free `translate.googleapis.com/translate_a/single` endpoint
— same source as `core/translator.py`. No API key, no account, no
telemetry. Up to 4500 chars per request, retries twice on transient
failures.

### Tech

- **PWA**: Vanilla JS, system fonts, M3-style dark theme.
- **TWA**: Standard `com.google.androidbrowserhelper.trusted.LauncherActivity`,
  Adaptive icons in 5 densities (mdpi → xxxhdpi), `LaunchTheme` matching
  `themeColor` in `twa-manifest.json`.
- **Worker**: CSP locks the app to self + the translation endpoint; TWA
  verification is handled via asset statements.

### Building

```bash
# 1. PWA — no build step, just serve:
cd app && python -m http.server 8000

# 2. APK:
cd apk
export JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"
export PATH="$JAVA_HOME/bin:$PATH"
export ANDROID_HOME="$LOCALAPPDATA/Android/Sdk"
./gradlew assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk  (~4.7 MB)

# 3. Worker:
cd cloudflare-worker && npx wrangler@4 deploy
```

### Installing the APK on a phone

1. Download `app-debug.apk` (see Releases).
2. On Android: Settings → Security → Install unknown apps (allow for
   your browser / file manager).
3. Tap the downloaded file → **Install**.
4. The app appears as **trns** in the launcher with the Inpriv primary
   gradient icon. First launch opens the PWA in fullscreen (no URL bar).

### Install status

- **packageId**: `xyz.inpriv.trns`
- **versionCode**: 2
- **versionName**: `0.1.0-beta`
- **minSdk**: 21 (Android 5.0)
- **targetSdk**: 36 (Android 16)

Beta channel. Asset Links + service worker registered; no analytics;
no third-party SDKs.
>>>>>>> c25dc29 (feat(trns): PWA + TWA Android app + Cloudflare Worker)
