"""
core.scanner
============

Passive Wi-Fi discovery built on Scapy:

  * `PassiveScanner`  - hops channels and collects APs from Beacons + ProbeResps
  * `ClientSniffer`   - locks one channel, correlates clients (MAC -> IP -> vendor)

Channel hopping runs in a background thread so the AsyncSniffer can run
in the foreground thread.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from scapy.all import (  # type: ignore
    ARP,
    Dot11,
    Dot11Beacon,
    Dot11Elt,
    Dot11ProbeResp,
    RadioTap,
)
from scapy.layers.l2 import Ether

from . import oui
from .interface import ChannelHopper
from .utils import C, log


@dataclass
class AccessPoint:
    bssid: str
    ssid: str = "<hidden>"
    channel: int = 0
    signal: int = -100            # best dBm seen
    encryption: str = "OPEN"
    clients: set[str] = field(default_factory=set)
    last_seen: float = 0.0
    beacons: int = 0

    @property
    def label(self) -> str:
        if self.ssid == "<hidden>":
            return f"<hidden> [{self.bssid}]"
        return self.ssid


@dataclass
class Client:
    mac: str
    bssid: str = ""
    ips: set[str] = field(default_factory=set)
    signal: int = -100
    last_seen: float = 0.0
    vendor: str = ""

    @property
    def label(self) -> str:
        parts = [self.mac]
        if self.ips:
            parts.append(next(iter(self.ips)))
        if self.vendor and self.vendor != "Unknown":
            parts.append(self.vendor)
        return " / ".join(parts)


# --- 802.11 IE parsing -----------------------------------------------------

def _parse_privacy(packet) -> str:
    """Return a short encryption label from a Beacon/ProbeResp."""
    try:
        elt = packet[Dot11Elt]
        while elt:
            if elt.ID == 48:           # RSN (WPA2/WPA3)
                return "WPA2/WPA3"
            elt = elt.payload.getlayer(Dot11Elt)
    except Exception:
        pass

    cap = packet.sprintf("%Dot11Beacon.cap%") or ""
    if "privacy" in cap.lower():
        return "WEP/WPA"

    # WPA (vendor-specific 221 with OUI 00:50:F2, type 1)
    try:
        elt = packet[Dot11Elt]
        while elt:
            if elt.ID == 221 and elt.info[:4] == b"\x00\x50\xf2\x01":
                return "WPA"
            elt = elt.payload.getlayer(Dot11Elt)
    except Exception:
        pass

    return "OPEN"


def _parse_ssid(packet) -> str:
    try:
        elt = packet[Dot11Elt]
        while elt and elt.ID != 0:
            elt = elt.payload.getlayer(Dot11Elt)
        if elt and elt.info:
            return elt.info.decode("utf-8", errors="replace")
    except Exception:
        pass
    return "<hidden>"


def _parse_channel(packet) -> int:
    try:
        elt = packet[Dot11Elt]
        while elt:
            if elt.ID == 3:           # DS Parameter Set
                return int(elt.info[0])
            elt = elt.payload.getlayer(Dot11Elt)
    except Exception:
        pass
    return 0


# --- Passive AP discovery ---------------------------------------------------

class PassiveScanner:
    """Sniff Beacons + Probe Responses across hopping channels."""

    def __init__(self, iface: str, *, hop: bool = True, dwell: float = 0.5) -> None:
        self.iface = iface
        self.hop = hop
        self.dwell = dwell
        self.aps: dict[str, AccessPoint] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._hopper: Optional[ChannelHopper] = None
        self._sniffer = None

    def start(self) -> None:
        if self.hop:
            self._hopper = ChannelHopper(self.iface, interval=self.dwell)
            self._hopper.start()

        log.info("Listening for beacons on %s...", self.iface)
        from scapy.all import AsyncSniffer

        self._sniffer = AsyncSniffer(
            iface=self.iface,
            prn=self._on_frame,
            store=False,
            stop_filter=lambda _: self._stop.is_set(),
            monitor=True,
        )
        self._sniffer.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sniffer:
            try:
                self._sniffer.stop(join=True)
            except Exception:
                pass
        if self._hopper:
            self._hopper.stop()
            self._hopper = None

    def join(self, timeout: float) -> None:
        """Block for `timeout` seconds of sniffing, then stop."""
        end = time.monotonic() + timeout
        try:
            while not self._stop.is_set() and time.monotonic() < end:
                time.sleep(0.1)
        finally:
            self.stop()

    def _on_frame(self, pkt) -> None:
        if not pkt.haslayer(Dot11Beacon) and not pkt.haslayer(Dot11ProbeResp):
            return

        try:
            dot11 = pkt[Dot11]
            bssid = dot11.addr2
            if not bssid:
                return
            bssid = bssid.upper()

            ssid = _parse_ssid(pkt)
            channel = _parse_channel(pkt)
            encryption = _parse_privacy(pkt)
            signal = _signal_dbm(pkt)

            now = time.monotonic()
            with self._lock:
                ap = self.aps.get(bssid)
                if ap is None:
                    ap = AccessPoint(bssid=bssid)
                    self.aps[bssid] = ap
                ap.ssid = ssid or ap.ssid
                ap.channel = channel or ap.channel
                # Never downgrade a previously observed stronger cipher.
                if encryption != "OPEN" or ap.encryption == "OPEN":
                    ap.encryption = encryption
                if signal > ap.signal:
                    ap.signal = signal
                ap.last_seen = now
                ap.beacons += 1
        except Exception as e:
            log.debug("beacon handler: %s", e)


# --- Client correlation -----------------------------------------------------

class ClientSniffer:
    """Watch a single AP and correlate clients (MAC -> IP -> vendor)."""

    def __init__(self, iface: str, bssid: str, duration: float) -> None:
        self.iface = iface
        self.bssid = bssid.upper()
        self.duration = duration
        self.clients: dict[str, Client] = {}
        self._stop = threading.Event()
        self._sniffer = None
        self._lock = threading.Lock()

    def start(self) -> None:
        from scapy.all import AsyncSniffer
        self._sniffer = AsyncSniffer(
            iface=self.iface,
            prn=self._on_frame,
            store=False,
            stop_filter=lambda _: self._stop.is_set(),
            monitor=True,
        )
        self._sniffer.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sniffer:
            try:
                self._sniffer.stop(join=True)
            except Exception:
                pass

    def run(self) -> dict[str, Client]:
        """Sniff for `self.duration` seconds and return the client map."""
        self.start()
        try:
            time.sleep(self.duration)
        finally:
            self.stop()
        return self.clients

    def _on_frame(self, pkt) -> None:
        if not pkt.haslayer(Dot11):
            return
        dot11 = pkt[Dot11]
        if dot11.type != 2:                 # data frames only
            return

        bssid = (dot11.addr3 or "").upper()
        if bssid != self.bssid:
            return

        for addr in (dot11.addr1, dot11.addr2, dot11.addr4):
            if not addr:
                continue
            addr = addr.upper()
            if addr == self.bssid or not _is_unicast(addr):
                continue

            with self._lock:
                client = self.clients.get(addr)
                if client is None:
                    client = Client(mac=addr, bssid=self.bssid)
                    self.clients[addr] = client
                client.last_seen = time.monotonic()
                sig = _signal_dbm(pkt)
                if sig > client.signal:
                    client.signal = sig

        if pkt.haslayer(ARP):
            self._correlate_arp(pkt[ARP])
        if pkt.haslayer(Ether):
            self._correlate_ether(pkt[Ether])

    def _correlate_arp(self, arp: ARP) -> None:
        for mac, ip in ((arp.hwsrc, arp.psrc), (arp.hwdst, arp.pdst)):
            if not mac or not ip:
                continue
            mac = mac.upper()
            with self._lock:
                client = self.clients.get(mac)
                if client:
                    client.ips.add(ip)

    def _correlate_ether(self, ether: Ether) -> None:
        """Extract IP src from 802.11 data frames that carry an Ether/IP payload."""
        try:
            from scapy.layers.inet import IP
            if ether.payload and ether.payload.haslayer(IP):
                ip_pkt = ether.payload[IP]
                mac = ether.src.upper()
                if mac and ip_pkt.src:
                    with self._lock:
                        client = self.clients.get(mac)
                        if client:
                            client.ips.add(ip_pkt.src)
        except Exception:
            pass


# --- Helpers ----------------------------------------------------------------

def _signal_dbm(pkt) -> int:
    """Extract dBm signal from RadioTap if present; else -100."""
    try:
        if pkt.haslayer(RadioTap):
            return int(pkt[RadioTap].dBm_AntSignal or -100)
    except Exception:
        pass
    return -100


def _is_unicast(mac: str) -> bool:
    if not mac or len(mac) < 17:
        return False
    return (int(mac.split(":")[0], 16) & 1) == 0


# --- Pretty printing --------------------------------------------------------

def render_ap_table(aps: dict[str, AccessPoint]) -> str:
    """Return a formatted table of access points for the menu."""
    oui.warm_cache(aps.keys())

    rows = []
    for i, ap in enumerate(sorted(aps.values(), key=lambda a: -a.beacons), 1):
        signal = f"{ap.signal:>4} dBm"
        ch = f"{ap.channel:<3}" if ap.channel else " ? "
        rows.append(
            f"{C.wrap(str(i) + '.', C.BOLD)} "
            f"{C.wrap(ap.label, C.CYAN, C.BOLD):<32} "
            f"[{C.wrap(ap.bssid, C.GRAY)}] "
            f"ch {C.wrap(ch, C.YELLOW)} "
            f"{C.wrap(ap.encryption, C.MAGENTA):<10} "
            f"{signal}"
        )
    return "\n".join(rows)


def render_client_table(clients: dict[str, Client]) -> str:
    """Return a formatted table of clients."""
    oui.warm_cache(c.mac for c in clients.values())

    rows = []
    for i, c in enumerate(sorted(clients.values(), key=lambda x: -x.signal), 1):
        c.vendor = oui.lookup(c.mac)
        ip_str = ", ".join(sorted(c.ips)) if c.ips else C.wrap("?", C.GRAY)
        rows.append(
            f"{C.wrap(str(i) + '.', C.BOLD)} "
            f"{C.wrap(c.mac, C.CYAN):<18} "
            f"ap [{C.wrap(c.bssid, C.GRAY)}] "
            f"ip {ip_str:<15} "
            f"{c.vendor:<24} "
            f"{c.signal:>4} dBm"
        )
    return "\n".join(rows)
