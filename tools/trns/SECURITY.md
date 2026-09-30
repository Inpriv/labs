# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report privately
through GitHub's *Security > Report a vulnerability* on the repository.
Expect an acknowledgement within a few days.

## What trns touches

- **Network:** only `https://translate.googleapis.com`. Text you translate is
  sent there; nothing else is transmitted and nothing is logged locally.
- **Disk:** `~/.trns/config.json` (languages, PATH opt-in) and, only when you
  opt in, a marked block in your shell rc files. `--debug-input=FILE` writes
  raw keystrokes to `FILE` - **it can capture typed text**; use it briefly and
  delete the log.
- **Processes:** the clipboard layer runs `termux-clipboard-set`, `pbcopy`,
  `wl-copy`, `xclip`, `xsel` or `clip` with your text on stdin (never as
  arguments, never through a shell).

## Supported versions

Only the latest release receives fixes.
