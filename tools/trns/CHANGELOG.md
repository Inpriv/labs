# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [0.2.0]

### Changed
- **Complete UI redesign, mobile-first.** New compact layout (1-row top bar,
  card-style history, action bar) that works from ~24 columns / 6 rows up to
  wide desktops, with three responsive breakpoints.
- Restyled first-run wizard, settings menu, help and language picker; the
  picker now searches by number, code or name and flows into columns.
- One-shot output is a card on a terminal and *only the translation* when
  piped.
- `Direction` moved to `core.direction`; input parsing moved to `core.keys`.
- Version is defined once (`core.__version__`).

### Added
- **One-line installers**: `install.sh` (Linux/macOS/Termux) and new `install.ps1`
  (Windows PowerShell, no admin). Both verify the install, support update and
  uninstall, and accept a ref (`TRNS_REF` / `-Ref`) or a local checkout
  (`TRNS_SRC` / `-Source`).
- Installable project site (PWA) in `site/`.
- Tap targets: language chip (swap), history cards (copy), action pills.
- `/copy` and a clipboard layer (Termux:API, pbcopy, wl-copy, xclip, xsel,
  clip, OSC 52).
- Live re-layout on terminal resize / device rotation (SIGWINCH).
- Horizontal scrolling of the input line; it can no longer wrap and corrupt
  the screen on narrow terminals.
- `NO_COLOR` support, `TRNS_ASCII` glyph fallback.
- `tests/` (stdlib `unittest`), `CONTRIBUTING.md`, `SECURITY.md`.

### Fixed
- REPL now switches the tty to cbreak mode on POSIX; previously keys such as
  Tab were only delivered after Enter.
- Mouse-wheel / touch scrolling never fired (wheel events were parsed as
  generic clicks).
- Mouse reporting is switched off while menus are open, so taps no longer
  leak escape sequences into prompts.
- Help output and unknown-command errors were wiped by the next redraw.
- Symlinked launchers resolved the wrong install directory (`realpath`).
- Picking `auto` as a *target* language is no longer offered.
- Removed a duplicate `mn` entry in the language table.

## [0.1.0]
- Initial release: REPL, one-shot mode, settings menu, PATH opt-in, installer.
