#!/usr/bin/env bash
#
# install.sh — set up trns on Linux, macOS, and Termux (Android)
# ----------------------------------------------------------------
# Downloads the latest trns sources from GitHub into
#   $XDG_DATA_HOME/trns/    (defaults to ~/.local/share/trns)
# and creates a tiny launcher at
#   $XDG_BIN_HOME/trns      (defaults to ~/.local/bin/trns)
#
# Optionally asks to add the launcher directory to the user's PATH.
# Pure stdlib Python (3.9+), so no pip install required.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Inpriv/labs/main/tools/trns/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/Inpriv/labs/main/tools/trns/install.sh | bash -s -- --path-add
#   ./install.sh --help
#
# Recognised flags:
#   --path-add      add the launcher directory to PATH (no prompt)
#   --path-skip     don't add to PATH (no prompt)
#   --no-modify-path  alias of --path-skip
#   --uninstall     remove trns from disk and PATH, then exit
#   --update        replace the existing install with the latest sources
#   --help          show this help and exit

set -euo pipefail

# ---------------------------------------------------------------------
# Plumbing: figure out where we are, where we want to install.
# ---------------------------------------------------------------------

GITHUB_RAW_BASE="https://raw.githubusercontent.com/Inpriv/labs/main/tools/trns"
GITHUB_API_BASE="https://api.github.com/repos/Inpriv/labs/contents/tools/trns"
GITHUB_TARBALL="https://github.com/Inpriv/labs/archive/refs/heads/main.tar.gz"

# XDG defaults honour XDG_DATA_HOME / XDG_BIN_HOME if set, then fall back
# to ~/.local. On Termux $PREFIX/bin is always in PATH so we use it.
trns_data_dir() {
    if [[ -n "${XDG_DATA_HOME:-}" ]]; then
        printf '%s/trns\n' "${XDG_DATA_HOME}"
    else
        printf '%s/.local/share/trns\n' "${HOME}"
    fi
}

trns_bin_dir() {
    if [[ -n "${XDG_BIN_HOME:-}" ]]; then
        printf '%s\n' "${XDG_BIN_HOME}"
    else
        printf '%s/.local/bin\n' "${HOME}"
    fi
}

is_termux() {
    [[ "${PREFIX:-}" == /data/data/com.termux/* ]]
}

# Default to Termux conventions when on Android.
if is_termux; then
    XDG_BIN_HOME="${XDG_BIN_HOME:-$PREFIX/bin}"
    XDG_DATA_HOME="${XDG_DATA_HOME:-$PREFIX/share}"
fi

DATA_DIR="$(trns_data_dir)"
BIN_DIR="$(trns_bin_dir)"

# ---------------------------------------------------------------------
# Tiny logger.
# ---------------------------------------------------------------------

if [[ -t 1 ]]; then
    C_BOLD=$'\033[1m'
    C_DIM=$'\033[2m'
    C_PRIMARY=$'\033[38;2;203;190;255m'
    C_SUCCESS=$'\033[38;2;171;211;122m'
    C_WARN=$'\033[38;2;255;184;104m'
    C_ERROR=$'\033[38;2;255;134;112m'
    C_RESET=$'\033[0m'
else
    C_BOLD=""; C_DIM=""; C_PRIMARY=""; C_SUCCESS=""; C_WARN=""; C_ERROR=""; C_RESET=""
fi

log()   { printf '%b==>%b %s\n' "${C_PRIMARY}" "${C_RESET}" "$*"; }
ok()    { printf '%b==>%b %b%s%b\n' "${C_PRIMARY}" "${C_RESET}" "${C_SUCCESS}" "$*" "${C_RESET}"; }
warn()  { printf '%b==>%b %b%s%b\n' "${C_PRIMARY}" "${C_RESET}" "${C_WARN}"     "$*" "${C_RESET}" >&2; }
err()   { printf '%b==>%b %b%s%b\n' "${C_PRIMARY}" "${C_RESET}" "${C_ERROR}"    "$*" "${C_RESET}" >&2; }
dim()   { printf '%b    %b%s%b\n' "${C_DIM}" "${C_RESET}" "$*" "${C_RESET}"; }

usage() {
    cat <<EOF | sed 's/^    //'
    trns installer — by Inpriv Labs
    Usage:
        ./install.sh [--path-add|--path-skip|--no-modify-path] [--update] [--help]
        curl ... | bash -s -- --path-add
    Flags:
        --path-add        Add the launcher directory to PATH (no prompt)
        --path-skip       Do not touch PATH (no prompt)
        --no-modify-path  Alias of --path-skip
        --update          Replace existing install with the latest sources
        --uninstall       Remove trns from disk and PATH, then exit
        --help            Show this help and exit
EOF
}

# ---------------------------------------------------------------------
# Parse args (allow both `bash install.sh` and `curl | bash -s --`).
# ---------------------------------------------------------------------

PATH_OPT=""
DO_UPDATE=0
DO_UNINSTALL=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --path-add)         PATH_OPT=add;    shift ;;
        --path-skip|--no-modify-path) PATH_OPT=skip; shift ;;
        --update)           DO_UPDATE=1;     shift ;;
        --uninstall)        DO_UNINSTALL=1;  shift ;;
        -h|--help)          usage; exit 0 ;;
        *) err "Unknown flag: $1"; usage; exit 2 ;;
    esac
done

# ---------------------------------------------------------------------
# Detect distro / package manager (best effort).
# ---------------------------------------------------------------------

PKG=""
SYSTEM_DEPS=()
DISTRO="${ID:-unknown}"

if is_termux; then
    PKG="pkg"
    DISTRO="termux"
    SYSTEM_DEPS=(python ca-certificates)
elif [[ -r /etc/os-release ]]; then
    . /etc/os-release || true
    DISTRO="${ID:-unknown}"
    case "${DISTRO}" in
        ubuntu|debian|kali|parrot|linuxmint|pop|raspbian)
            PKG="apt-get"
            SYSTEM_DEPS=(python3 python3-pip ca-certificates curl)
            ;;
        arch|manjaro|endeavouros)
            PKG="pacman"
            SYSTEM_DEPS=(python python-pip ca-certificates curl)
            ;;
        fedora|centos|rhel|rocky|almalinux)
            PKG="dnf"
            SYSTEM_DEPS=(python3 python3-pip ca-certificates curl)
            ;;
        alpine)
            PKG="apk"
            SYSTEM_DEPS=(python3 ca-certificates curl)
            ;;
        *)
            PKG=""
            ;;
    esac
fi

# ---------------------------------------------------------------------
# Uninstall path.
# ---------------------------------------------------------------------

uninstall_trns() {
    log "Uninstalling trns from ${DATA_DIR}"
    if [[ -f "${DATA_DIR}/trns.py" ]]; then
        if [[ -x "${DATA_DIR}/trns.py" ]]; then
            "${DATA_DIR}/trns.py" --path-remove >/dev/null 2>&1 || true
        else
            python3 "${DATA_DIR}/trns.py" --path-remove >/dev/null 2>&1 || \
              python   "${DATA_DIR}/trns.py" --path-remove >/dev/null 2>&1 || true
        fi
    fi
    rm -rf "${DATA_DIR}"
    rm -f "${BIN_DIR}/trns"
    rm -rf "${HOME}/.trns"
    ok "trns removed."
}

if [[ "${DO_UNINSTALL}" == "1" ]]; then
    uninstall_trns
    exit 0
fi

# ---------------------------------------------------------------------
# Sanity checks.
# ---------------------------------------------------------------------

log "Detecting environment"
dim "  distro : ${DISTRO}"
dim "  pkg mgr: ${PKG:-<none>}"
dim "  data   : ${DATA_DIR}"
dim "  bin    : ${BIN_DIR}"

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    err "No 'python3' or 'python' on PATH. Install Python 3.9+ and re-run."
    exit 1
fi

# Pick whichever python we found. Prefer python3.
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
else
    PYTHON_BIN=python
fi

# Verify version >= 3.9.
PY_VERSION="$("${PYTHON_BIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [[ "${PY_MAJOR}" -lt 3 || ( "${PY_MAJOR}" -eq 3 && "${PY_MINOR}" -lt 9 ) ]]; then
    err "Python ${PY_VERSION} is too old. Need 3.9+."
    exit 1
fi

# ---------------------------------------------------------------------
# Optional: install system deps (Python is the only thing trns needs).
# ---------------------------------------------------------------------

install_system_deps() {
    [[ -z "${PKG}" ]] && {
        warn "Unknown distro; skipping system package install. Make sure '${PYTHON_BIN}' is on PATH."
        return 0
    }

    # On Termux we never want to require root — pkg is fine unprivileged
    # but the system itself is normally single-user.
    case "${PKG}" in
        apt-get)
            if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then SUDO=sudo; else SUDO=""; fi
            ${SUDO} apt-get update -y
            ${SUDO} apt-get install -y "${SYSTEM_DEPS[@]}"
            ;;
        pacman)
            if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then SUDO=sudo; else SUDO=""; fi
            ${SUDO} pacman -Sy --noconfirm --needed "${SYSTEM_DEPS[@]}"
            ;;
        dnf)
            if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then SUDO=sudo; else SUDO=""; fi
            ${SUDO} dnf install -y "${SYSTEM_DEPS[@]}"
            ;;
        apk)
            if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then SUDO=sudo; else SUDO=""; fi
            ${SUDO} apk add --no-cache "${SYSTEM_DEPS[@]}"
            ;;
        pkg)
            pkg update -y
            pkg install -y "${SYSTEM_DEPS[@]}"
            ;;
    esac
}

if [[ "${DO_UPDATE}" == "0" && -d "${DATA_DIR}" && -f "${DATA_DIR}/trns.py" ]]; then
    log "Existing install found at ${DATA_DIR}"
    ok "Use --update to refresh, or --uninstall to remove. Exiting."
    exit 0
fi

if [[ "${PKG}" != "" ]]; then
    log "Installing system dependencies (${PKG})"
    install_system_deps || warn "Some system packages failed to install; trns will still try."
fi

# ---------------------------------------------------------------------
# Fetch sources from GitHub. We download a tarball (one HTTP call) and
# extract just the tools/trns/ subtree. Robust against curl|bash where
# individual raw URLs would be N round-trips.
# ---------------------------------------------------------------------

log "Fetching trns from ${GITHUB_TARBALL}"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 --connect-timeout 15 "${GITHUB_TARBALL}" -o "${TMP}/repo.tar.gz" \
        || { err "Could not download ${GITHUB_TARBALL}"; exit 1; }
elif command -v wget >/dev/null 2>&1; then
    wget -q --tries=3 --timeout=20 -O "${TMP}/repo.tar.gz" "${GITHUB_TARBALL}" \
        || { err "Could not download ${GITHUB_TARBALL}"; exit 1; }
else
    err "Neither curl nor wget is installed; cannot download sources."
    exit 1
fi

log "Extracting tools/trns/"
tar -xzf "${TMP}/repo.tar.gz" -C "${TMP}" labs-main/tools/trns/ 2>/dev/null \
    || tar -xzf "${TMP}/repo.tar.gz" -C "${TMP}" 'labs-*/tools/trns/' 2>/dev/null \
    || { err "Tarball did not contain tools/trns/"; exit 1; }

# Locate the extracted directory regardless of strip prefix.
SRC_DIR=""
for candidate in "${TMP}/labs-main/tools/trns" "${TMP}"/labs-*/tools/trns; do
    if [[ -d "${candidate}" && -f "${candidate}/trns.py" ]]; then
        SRC_DIR="${candidate}"
        break
    fi
done
[[ -z "${SRC_DIR}" ]] && { err "Could not find tools/trns/ in archive"; exit 1; }

# ---------------------------------------------------------------------
# Install: move sources into $DATA_DIR, write launcher into $BIN_DIR.
# ---------------------------------------------------------------------

log "Installing to ${DATA_DIR}"
mkdir -p "${DATA_DIR}" "${BIN_DIR}"

# Remove old contents (clean reinstall / update) but keep our launcher.
for f in "${DATA_DIR}"/*; do
    [[ -e "${f}" ]] && rm -rf "${f}"
done
cp -R "${SRC_DIR}/." "${DATA_DIR}/"
chmod +x "${DATA_DIR}/trns.py"

# Launcher — a tiny shell script that exec's the right python against
# the canonical install path. No shebang-with-python-version traps.
LAUNCHER="${BIN_DIR}/trns"
cat > "${LAUNCHER}" <<EOF
#!/usr/bin/env bash
# trns launcher — generated by Inpriv Labs install.sh.
# Resolves the right python (python3 preferred, falls back to python).
exec "\${PYTHON:-python3}" "${DATA_DIR}/trns.py" "\$@"
EOF
chmod +x "${LAUNCHER}"

# Quick smoke test: --version should print without network.
log "Smoke-testing the install"
if ! "${LAUNCHER}" --version >/dev/null 2>&1; then
    err "Install verification failed: '${LAUNCHER} --version' exited non-zero."
    err "Try running it manually to see the error."
    exit 1
fi
ok "trns ${PY_VERSION} ready."

# ---------------------------------------------------------------------
# PATH wizard.
# ---------------------------------------------------------------------

path_dir_is_on_path() {
    case ":\${PATH}:" in
        *":${BIN_DIR}:"*) return 0 ;;
        *) return 1 ;;
    esac
}

ask_path() {
    if [[ ! -t 0 ]]; then
        # Non-interactive (curl|bash). Default to skip — user can re-run.
        return 1
    fi
    local ans
    printf "%b%s%b Add '%s' to your PATH? [y/N] " \
        "${C_BOLD}" "?" "${C_RESET}" "${BIN_DIR}"
    read -r ans
    [[ "${ans}" =~ ^[Yy]([Ee][Ss])?$ ]]
}

should_add_to_path() {
    case "${PATH_OPT}" in
        add)  return 0 ;;
        skip) return 1 ;;
        *)    if path_dir_is_on_path; then return 1; fi; ask_path ;;
    esac
}

if should_add_to_path; then
    log "Adding ${BIN_DIR} to PATH"
    if is_termux; then
        PREFIX_DIR="${PREFIX}/etc/profile.d"
        mkdir -p "${PREFIX_DIR}" 2>/dev/null || true
        LAUNCH="${BIN_DIR}/trns"
        PROFILE_FILE="${PREFIX_DIR}/trns.sh"
        {
            echo '# >>> trns install >>>'
            printf 'export PATH="%s:$PATH"\n' "${BIN_DIR}"
            echo '# <<< trns install <<<'
        } > "${PROFILE_FILE}"
        ok "Added via ${PROFILE_FILE}."
        dim "Open a new Termux session for the change to take effect."
    else
        PYTHON_BIN_PATH="$(${PYTHON_BIN} -c 'import os,sys; sys.stdout.write(os.path.realpath("${PYTHON_BIN}"))')"
        # Delegate PATH persistence to trns itself so the same logic covers
        # every supported shell. --path-add strips any prior sentinel block.
        "${LAUNCHER}" --path-add
        ok "Added to your shell rc."
        dim "Open a new terminal (or run 'source ~/.bashrc' / 'source ~/.zshrc') for the change to take effect."
    fi
else
    dim "Skipping PATH setup. You can add ${BIN_DIR} to PATH later by running:"
    dim "    ${LAUNCHER} --path-add"
    dim "or manually:"
    dim "    export PATH=\"${BIN_DIR}:\$PATH\""
fi

# ---------------------------------------------------------------------
# One-shot first-run: ask trns to mark the wizard complete so the user
# doesn't get the interactive prompt on their very first 'trns' call.
# ---------------------------------------------------------------------

log "Initialising trns config"
TRNS_HOME_OVERRIDE="$(dirname "${DATA_DIR}")" \
    "${LAUNCHER}" --where >/dev/null || true

cat <<EOF

${C_SUCCESS}trns is installed.${C_RESET}

  Try it:
    ${LAUNCHER} hello world
    ${LAUNCHER} --swap cześć
    ${LAUNCHER}                 # interactive REPL

  Uninstall:
    curl -fsSL ${GITHUB_RAW_BASE}/install.sh | bash -s -- --uninstall

EOF