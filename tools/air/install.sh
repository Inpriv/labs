#!/usr/bin/env bash
#
# install.sh — set up air on a Debian/Ubuntu-style host
# -----------------------------------------------------
# Installs system tools (iw, wireless-tools, tcpdump-style raw socket support)
# and Python dependencies (Scapy). Run as root or with sudo.

set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Please run with sudo: sudo ./install.sh" >&2
  exit 1
fi

echo "==> Detecting distro"
. /etc/os-release || true
DISTRO="${ID:-unknown}"

case "${DISTRO}" in
  ubuntu|debian|kali|parrot|linuxmint|pop)
    PKG="apt-get"
    SYSTEM_DEPS=(
      iw wireless-tools rfkill
      aircrack-ng                # optional: provides airmon-ng
      ca-certificates python3-pip python3-venv
      python3-scapy             # system-wide Scapy so `sudo python air.py` works
    )
    ;;
  arch|manjaro|endeavouros)
    PKG="pacman"
    SYSTEM_DEPS=(iw wireless_tools rfkill aircrack-ng python-pip)
    ;;
  fedora|centos|rhel|rocky|almalinux)
    PKG="dnf"
    SYSTEM_DEPS=(iw wireless-tools rfkill aircrack-ng python3-pip)
    ;;
  *)
    echo "Unknown distro '${DISTRO}'. Skipping system packages; please install"
    echo "iw + wireless-tools + python3-pip manually." >&2
    PKG=""
    SYSTEM_DEPS=()
    ;;
esac

if [[ -n "${PKG}" ]]; then
  echo "==> Installing system dependencies via ${PKG}"
  case "${PKG}" in
    apt-get) apt-get update -y && apt-get install -y "${SYSTEM_DEPS[@]}";;
    pacman)  pacman -Sy --noconfirm "${SYSTEM_DEPS[@]}";;
    dnf)     dnf install -y "${SYSTEM_DEPS[@]}";;
  esac
fi

echo "==> Creating Python virtual environment (.venv)"
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo
echo "==> Done. Usage:"
echo "    sudo python air.py --list"
echo "    sudo python air.py -i wlan0"
echo
echo "  (a system-wide python3-scapy was installed so 'sudo python' resolves"
echo "   Scapy correctly. If you prefer the venv, use 'sudo ./.venv/bin/python"
echo "   air.py ...' instead — sudo resets PATH and breaks the venv.)"
