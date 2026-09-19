#!/usr/bin/env bash
#
# install.sh - set up trns on Linux/macOS
#
# Adds this folder to the user's PATH so typing `trns` in any new
# terminal window launches the script. Re-running is safe; it silently
# no-ops if the folder is already on PATH.
#
# Usage:
#   ./install.sh
#   PATH_REMOVE=1 ./install.sh    # uninstall
#
# Equivalent Windows scripts: install.bat / uninstall.bat.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_NAME="trns.py"
PATH_MARKER="$HERE"

remove_path_entry() {
    case ":$PATH:" in
        *":$PATH_MARKER:"*) ;;
        *) return 0 ;;
    esac
    local new_path=""
    local IFS=':'
    for p in $PATH; do
        if [ "$p" != "$PATH_MARKER" ]; then
            new_path="${new_path:+$new_path:}$p"
        fi
    done
    if [ -n "$new_path" ]; then
        export PATH="$new_path"
        # Persist to login shell rc file if we can find one.
        for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
            if [ -w "$rc" ] || [ -w "$(dirname "$rc")" ]; then
                # Strip our entry from the rc file.
                if [ -f "$rc" ]; then
                    tmp=$(mktemp)
                    awk -v marker=":$PATH_MARKER" '
                        BEGIN { skip=0 }
                        index($0, marker) { skip=1 }
                        skip && /export PATH/ { skip=0; next }
                        skip && /^[[:space:]]*$/ { next }
                        skip && /^export PATH=/ { skip=0; next }
                        skip { next }
                        { print }
                    ' "$rc" > "$tmp" && mv "$tmp" "$rc"
                fi
                break
            fi
        done
    fi
}

add_path_entry() {
    case ":$PATH:" in
        *":$PATH_MARKER:"*) return 0 ;;
    esac
    export PATH="$PATH_MARKER:$PATH"
    for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
        if [ -f "$rc" ] && [ -w "$rc" ]; then
            # Only append if not already present.
            if ! grep -qF "$PATH_MARKER" "$rc"; then
                {
                    echo ""
                    echo "# Added by trns installer on $(date +%Y-%m-%d)"
                    echo "export PATH=\"$PATH_MARKER:\$PATH\""
                } >> "$rc"
            fi
            break
        fi
    done
}

if [ "${PATH_REMOVE:-0}" = "1" ]; then
    remove_path_entry
    echo "trns removed from PATH."
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "trns: Python 3 is not installed. Install Python 3.9+ and try again." >&2
    exit 1
fi

if ! command -v python >/dev/null 2>&1 && [ ! -x /usr/bin/python3 ]; then
    echo "trns: no python interpreter found." >&2
    exit 1
fi

add_path_entry

# Headless one-shot sanity check (no interactive REPL).
PYTHON_BIN="$(command -v python3 || command -v python)"
if ! "$PYTHON_BIN" "$HERE/$SCRIPT_NAME" --version >/dev/null 2>&1; then
    echo "trns: sanity check failed (python $("$PYTHON_BIN" -V 2>&1) on $HERE/$SCRIPT_NAME)" >&2
    exit 1
fi

echo
echo "trns is installed."
echo
echo "  - Open a NEW terminal window, then type: trns"
echo "  - One-shot:   trns hello world"
echo "  - Help:       trns --help"
echo
echo "If an already-open terminal does not see the new command,"
echo "close it and open a fresh one (login shells cache PATH)."
