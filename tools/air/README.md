# air — Wi-Fi 802.11 frame injector & PMF/WPA3 resilience auditor

```
     .--.  .-..----.
    / {} \ | || {}  }
   /  /\  \| || .-. \
   `-'  `-'`-'`-' `-'
   air.inpriv.xyz
   Wi-Fi PMF / WPA3 resilience auditor   v0.1.0
```

Interactive Python CLI that automates the full deauthentication test workflow:
interface management, AP & client discovery, and continuous frame injection,
with graceful restoration on exit.

> **Authorized use only.** Sending deauth/disassoc frames against networks you
> do not own or have explicit written permission to test is illegal in most
> jurisdictions. `air` enforces an interactive acceptance gate before any
> frame leaves the adapter.

## Features

- **Automatic monitor-mode switching** via `airmon-ng` (preferred — kills
  NetworkManager / `wpa_supplicant`, creates a virtual `wlan0mon`) with a
  graceful fallback to raw `iw`.
- **Passive AP discovery** — Beacons + Probe Responses across hopping
  channels. Extracts SSID, BSSID, channel, encryption (OPEN / WPA / WPA2/WPA3).
- **Client correlation** — locks to the AP's channel and correlates
  `client MAC -> AP BSSID -> IP address -> vendor (IEEE OUI)` via data,
  ARP, and IP-over-802.11 frames.
- **Targeted or broadcast deauth** — sends `Dot11Deauth` and optionally
  `Dot11Disas` frames in a continuous loop with configurable reason codes.
- **Graceful restore** — Ctrl+C (or any exit path) restores managed mode
  and re-attaches the adapter to NetworkManager.
- **Non-interactive mode** for scripting: `--bssid` + `--client` skips menus.
- **Local OUI overrides** in `data/oui-overrides.txt` for known lab gear.

## Project layout

```
air/
├── air.py                # CLI entry point
├── core/
│   ├── __init__.py
│   ├── interface.py      # monitor mode + channel hopping
│   ├── scanner.py        # AP & client discovery (Scapy)
│   ├── injector.py       # deauth/disassoc frame builder + loop
│   ├── oui.py            # MAC vendor lookup
│   └── utils.py          # colors, logging, subprocess, spinner
├── data/
│   └── oui-overrides.txt # local vendor overrides
├── requirements.txt
├── install.sh            # apt/pacman/dnf + venv bootstrapper
└── README.md
```

## Requirements

| Component | Notes |
|-----------|-------|
| Python    | 3.9+ |
| Scapy     | `pip install scapy` |
| `iw`      | `apt install iw` (Linux only) |
| `airmon-ng` | `apt install aircrack-ng` (preferred for monitor mode) |
| `ip`      | `apt install iproute2` |
| Wireless adapter | Must support monitor mode (e.g. Atheros AR9271, Ralink RT3070, Realtek RTL8812AU with monitor-capable driver) |

Monitor mode is **Linux-only**. On macOS/Windows the CLI will surface a clear
error message.

## Installation

```bash
git clone https://github.com/Inpriv/air.git
cd air
sudo ./install.sh                # installs iw + airmon-ng + scapy
source .venv/bin/activate
sudo python air.py --list        # confirm your adapter is detected
```

`install.sh` covers `apt` (Debian/Ubuntu/Kali/Parrot/Mint/Pop), `pacman`
(Arch/Manjaro), and `dnf` (Fedora/RHEL).

## Usage

### Interactive

```bash
sudo python air.py -i wlan0
```

1. `air` prints the banner and an authorization disclaimer — type `yes`.
2. Select the wireless interface (or pre-select with `-i wlan0`).
3. `air` flips the adapter into monitor mode.
4. **Scan APs** — channel-hopping for `--scan-time` seconds (default 20s).
5. Pick an AP from the table.
6. **Scan clients** — locks to the AP's channel for `--client-time` seconds.
7. Pick a client, `b` for broadcast, or `q` to back out.
8. **Inject** — `air` loops deauth (and optionally disassoc) frames. Press
   Ctrl+C to stop; the interface is restored automatically.

### Non-interactive

```bash
sudo python air.py -i wlan0 \
    --bssid AA:BB:CC:DD:EE:FF \
    --client 11:22:33:44:55:66 \
    --reason 7 --interval 0.05 --disassoc
```

- `--client ff:ff:ff:ff:ff:ff` (default) targets every connected client.
- `--reason 7` = "Class 3 frame from nonassociated STA" — most effective
  against most APs.
- `--no-monitor` skips the mode switch if you already have an adapter in
  monitor mode (e.g. from `airmon-ng`).

### Reason codes

| Code | Meaning |
|------|---------|
| 1 | Unspecified |
| 4 | Disassociated due to inactivity |
| 5 | AP unable to honor all associated STAs |
| 7 | Class 3 frame received from nonassociated STA |
| 8 | Disassociated because STA is leaving BSS |

## OUI overrides

`air` uses Scapy's `scapy.data.manuf` (~30k IEEE OUIs). Add hand-curated
entries to `data/oui-overrides.txt`:

```
00:11:22   TestingHomeLab-AP
B8:27:EB   Raspberry Pi Foundation
```

Overrides win over Scapy's database.

## Safety notes

- **802.11w / PMF** — modern WPA3 APs negotiate *Protected Management Frames*
  and reject forged deauths. `air` is the right tool to *test* PMF
  enforcement: a successful deauth means your AP isn't actually protecting
  management frames.
- **Channel pinning** — the injector always sets the interface to the target
  AP's channel before looping.
- **Disassoc vs deauth** — pass `--disassoc` to emit both each tick; some
  APs/clients respond faster to `Dot11Disas`.

## License & legal

This software is provided for educational and authorized security testing
purposes only. The authors disclaim all responsibility for misuse. By running
`air` you confirm that you have authorization to test the target network.
