#!/usr/bin/env python3
"""
air — Wi-Fi 802.11 frame injector and PMF/WPA3 resilience auditor.

Interactive workflow:

    1. Pick a wireless interface (or pass `-i wlan0`)
    2. Switch it into monitor mode (via airmon-ng or raw `iw`)
    3. Scan for access points (Beacons + Probe Responses)
    4. Pick an AP from the list
    5. Sniff data frames to discover connected clients + their IPs
    6. Pick a client (or broadcast) and inject deauth frames
    7. Restore the interface to managed mode on exit

Authorized use only. See README.md for the legal disclaimer.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import injector, interface, scanner, utils
from core.utils import C, confirm, log, require_root, spinner

VERSION = "0.1.0"

BANNER = r"""
     .--.  .-..----.
    / {} \ | || {}  }
   /  /\  \| || .-. \
   `-'  `-'`-'`-' `-'
   air.inpriv.xyz
   Wi-Fi PMF / WPA3 resilience auditor   v""" + VERSION


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="air",
        description="Wi-Fi frame injector & PMF/WPA3 resilience auditor.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  sudo python air.py -i wlan0\n"
            "  sudo python air.py -i wlan0 --bssid AA:BB:CC:DD:EE:FF\n"
            "  sudo python air.py -i wlan0 --bssid AA:BB:CC:DD:EE:FF "
            "--client 11:22:33:44:55:66 --reason 7\n"
            "  sudo python air.py --list   # show wireless interfaces and exit\n"
        ),
    )
    p.add_argument("-i", "--iface", help="wireless interface (e.g. wlan0)")
    p.add_argument("--bssid", help="target AP BSSID (skips AP selection)")
    p.add_argument("--client", default="ff:ff:ff:ff:ff:ff",
                   help="target client MAC, or ff:ff:ff:ff:ff:ff for broadcast")
    p.add_argument("--scan-time", type=float, default=20.0,
                   help="seconds to scan for APs (default: 20)")
    p.add_argument("--client-time", type=float, default=15.0,
                   help="seconds to sniff clients (default: 15)")
    p.add_argument("--interval", type=float, default=0.1,
                   help="seconds between deauth frames (default: 0.1)")
    p.add_argument("--reason", type=int, default=7,
                   help="802.11 reason code (default: 7)")
    p.add_argument("--disassoc", action="store_true",
                   help="also send disassociation frames")
    p.add_argument("--no-monitor", action="store_true",
                   help="skip monitor-mode switch (assume already enabled)")
    p.add_argument("--list", action="store_true",
                   help="list wireless interfaces and exit")
    p.add_argument("--quiet", action="store_true", help="suppress spinners")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


DISCLAIMER = """
!! AUTHORIZED USE ONLY !!

Sending deauthentication frames against networks you do not own or have
explicit written permission to test is illegal in most jurisdictions
(e.g. CFAA, Computer Misuse Act, GDPR-flavoured national laws, ...).

By continuing you confirm that:

  - You own the target network, OR
  - You have explicit written authorisation to audit it.

Type 'yes' to accept and continue, anything else to abort.
"""


def acceptance_gate() -> None:
    print(C.wrap(DISCLAIMER, C.RED, C.BOLD))
    if not confirm(C.wrap("I have authorisation to test this network", C.BOLD)):
        print(C.wrap("Aborted. (no authorisation given)", C.YELLOW))
        sys.exit(2)


def choose_ap(aps: dict[str, scanner.AccessPoint]) -> scanner.AccessPoint:
    """Prompt the user to pick an AP from the discovered set."""
    if not aps:
        raise RuntimeError("No access points discovered.")

    print()
    print(C.wrap("Discovered access points:", C.BOLD, C.CYAN))
    print(C.wrap("-" * 78, C.GRAY))
    print(scanner.render_ap_table(aps))
    print(C.wrap("-" * 78, C.GRAY))

    sorted_aps = sorted(aps.values(), key=lambda a: -a.beacons)
    while True:
        raw = input(
            C.wrap(f"Select AP [1-{len(sorted_aps)}] or 'q' to re-scan: ", C.BOLD)
        ).strip()
        if raw.lower() in ("q", "quit", "r", "rescan"):
            raise KeyboardInterrupt("rescan")
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(sorted_aps):
                return sorted_aps[idx]
        except ValueError:
            pass
        print(C.wrap("Invalid selection.", C.RED))


def choose_client(clients: dict[str, scanner.Client]) -> Optional[str]:
    """Prompt the user to pick a client MAC, broadcast, or none.

    Returns:
        MAC string for the chosen client, "ff:ff:ff:ff:ff:ff" for broadcast,
        or None to abort back to the AP menu.
    """
    if not clients:
        log.warning("No clients observed for this AP (yet). Try a longer sniff.")
        return None

    print()
    print(C.wrap("Connected clients:", C.BOLD, C.CYAN))
    print(C.wrap("-" * 78, C.GRAY))
    print(scanner.render_client_table(clients))
    print(C.wrap("-" * 78, C.GRAY))

    sorted_clients = sorted(clients.values(), key=lambda c: -c.signal)
    prompt = (
        f"Target client [1-{len(sorted_clients)}], "
        "'b' for broadcast (all), or 'q' to abort: "
    )
    while True:
        raw = input(C.wrap(prompt, C.BOLD)).strip()
        if raw.lower() in ("q", "quit", "back"):
            return None
        if raw.lower() in ("b", "broadcast", "all"):
            return "ff:ff:ff:ff:ff:ff"
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(sorted_clients):
                return sorted_clients[idx].mac
        except ValueError:
            pass
        print(C.wrap("Invalid selection.", C.RED))


def run_ap_scan(iface: str, duration: float, *, quiet: bool) -> dict:
    """Hop channels and collect APs for `duration` seconds."""
    s = scanner.PassiveScanner(iface)
    s.start()
    with spinner(f"Sniffing beacons on {iface} for {duration:.0f}s", enabled=not quiet):
        try:
            s.join(duration)
        except KeyboardInterrupt:
            log.info("Scan interrupted")
            s.stop()
    return s.aps


def run_client_scan(iface: str, ap: scanner.AccessPoint, duration: float,
                    *, quiet: bool) -> dict:
    """Lock to AP.channel and capture clients for `duration` seconds."""
    if ap.channel:
        try:
            interface.set_channel(iface, ap.channel)
        except RuntimeError as e:
            log.warning("Could not lock channel: %s", e)

    sniff_obj = scanner.ClientSniffer(iface, bssid=ap.bssid, duration=duration)
    with spinner(
        f"Watching {ap.bssid} on ch {ap.channel} for {duration:.0f}s",
        enabled=not quiet,
    ):
        sniff_obj.run()
    return sniff_obj.clients


def run_inject(iface: str, ap: scanner.AccessPoint, client: str, *,
               reason: int, interval: float, include_disassoc: bool) -> int:
    """Inject deauth frames; returns total frames sent."""
    print(C.wrap(
        f"\n>>> Injecting deauths: AP={ap.bssid}  client={client}  "
        f"reason={reason} ({injector.VALID_REASONS.get(reason, '?')})  "
        f"interval={interval}s",
        C.RED, C.BOLD,
    ))
    if not confirm("Proceed?", default=True):
        print(C.wrap("Aborted.", C.YELLOW))
        return 0

    return injector.inject(
        bssid=ap.bssid,
        client=client,
        iface=iface,
        reason=reason,
        interval=interval,
        channel=ap.channel or None,
        include_disassoc=include_disassoc,
    )


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    utils.configure_logging(getattr(logging, args.log_level))

    print(C.wrap(BANNER, C.CYAN, C.BOLD))

    if args.list:
        for iface in interface.list_interfaces():
            tag = "[monitor-capable]" if iface.monitor_capable else "[managed only]"
            print(f"  {iface.name:<10} {iface.mac or '??':<18} {tag}")
        return 0

    try:
        require_root()
    except PermissionError as e:
        log.error(str(e))
        return 1
    try:
        from scapy.all import conf  # noqa: F401  - force scapy import to surface errors early
    except ImportError as e:
        log.error("Scapy is required: pip install scapy (%s)", e)
        return 1

    picked = (interface.WirelessInterface(name=args.iface)
              if args.iface else interface.prompt_for_interface())
    iface_name = picked.name
    log.info("Using interface %s", iface_name)

    sniff_iface = iface_name
    if not args.no_monitor:
        try:
            sniff_iface = interface.enable_monitor(iface_name)
        except RuntimeError as e:
            log.error("%s", e)
            return 1

    def _restore(_sig=None, _frame=None):
        if not args.no_monitor:
            interface.disable_monitor(sniff_iface)
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _restore)
        except (ValueError, OSError):
            pass

    try:
        if args.bssid:
            ap = scanner.AccessPoint(bssid=args.bssid.upper(), channel=0)
            aps = run_ap_scan(sniff_iface, min(args.scan_time, 8), quiet=args.quiet)
            for found in aps.values():
                if found.bssid == ap.bssid:
                    ap = found
                    break

            client = args.client or "ff:ff:ff:ff:ff:ff"
            if not args.client or args.client == "ff:ff:ff:ff:ff:ff":
                clients = run_client_scan(
                    sniff_iface, ap, args.client_time, quiet=args.quiet,
                )
                picked_client = choose_client(clients)
                if picked_client is None:
                    return 0
                client = picked_client

            run_inject(
                sniff_iface, ap, client,
                reason=args.reason, interval=args.interval,
                include_disassoc=args.disassoc,
            )
            return 0

        while True:
            aps = run_ap_scan(sniff_iface, args.scan_time, quiet=args.quiet)
            try:
                ap = choose_ap(aps)
            except KeyboardInterrupt:
                log.info("Re-scanning...")
                continue

            clients = run_client_scan(
                sniff_iface, ap, args.client_time, quiet=args.quiet,
            )
            client = choose_client(clients)
            if client is None:
                continue

            sent = run_inject(
                sniff_iface, ap, client,
                reason=args.reason, interval=args.interval,
                include_disassoc=args.disassoc,
            )
            log.info("Session complete: %d frames sent", sent)

            if not confirm("Run another audit?", default=False):
                break
    finally:
        if not args.no_monitor:
            log.info("Cleaning up...")
            interface.disable_monitor(sniff_iface)
        log.info("Goodbye.")
    return 0


if __name__ == "__main__":
    # Read-only / help invocations should not trigger the disclaimer gate.
    skip_gate = {"--help", "-h", "--list"}
    if not any(flag in sys.argv for flag in skip_gate):
        acceptance_gate()
    sys.exit(main())
