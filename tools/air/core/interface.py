"""
core.interface
==============

Wireless interface lifecycle: discovery, monitor-mode switching
(airmon-ng first, raw `iw` fallback), channel pinning, channel hopping.

Linux-first. macOS / Windows are best-effort — true monitor mode requires
Linux with a supported adapter.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from .utils import C, log, require_tool, run, run_live


@dataclass
class WirelessInterface:
    name: str
    mac: str = ""
    driver: str = ""
    chipset: str = ""
    mode: str = "managed"
    monitor_capable: bool = False

    def __str__(self) -> str:
        return f"{self.name} [{self.driver or 'unknown driver'}]"


def list_interfaces() -> list[WirelessInterface]:
    """Enumerate wireless interfaces and report their current state."""
    if sys.platform.startswith("linux"):
        ifaces = _list_interfaces_linux()
    elif sys.platform == "darwin":
        ifaces = _list_interfaces_macos()
    else:
        ifaces = _list_interfaces_scapy()

    for iface in ifaces:
        iface.monitor_capable = _supports_monitor(iface.name)
    return ifaces


def _list_interfaces_linux() -> list[WirelessInterface]:
    """Use `iw dev` to enumerate wireless interfaces on Linux."""
    out: list[WirelessInterface] = []
    try:
        require_tool("iw")
    except RuntimeError:
        log.warning("`iw` not installed; cannot enumerate wireless interfaces")
        return out

    try:
        result = run(["iw", "dev"], check=False)
    except RuntimeError:
        return out

    current: Optional[WirelessInterface] = None
    for raw in result.stdout.splitlines():
        line = raw.rstrip()
        m = re.match(r"\s*Interface\s+(\S+)", line)
        if m:
            if current:
                out.append(current)
            current = WirelessInterface(name=m.group(1))
            continue
        if current is None:
            continue
        if "addr" in line:
            current.mac = line.split()[-1].upper()
        elif "type" in line:
            current.mode = line.split()[-1]

    if current:
        out.append(current)

    for iface in out:
        phy_path = f"/sys/class/net/{iface.name}/phy80211"
        if os.path.islink(phy_path):
            phy = os.readlink(phy_path).split("/")[-1]
            try:
                with open(f"/sys/class/ieee80211/{phy}/device/driver") as fh:
                    iface.driver = fh.read().strip().split("/")[-1]
            except OSError:
                pass
    return out


def _list_interfaces_macos() -> list[WirelessInterface]:
    """macOS: monitor mode needs an external adapter; report en0 as best effort."""
    try:
        from scapy.all import get_if_hwaddr  # type: ignore
        return [WirelessInterface(name="en0", mac=get_if_hwaddr("en0"))]
    except Exception:
        return [WirelessInterface(name="en0")]


def _list_interfaces_scapy() -> list[WirelessInterface]:
    """Fallback: enumerate NPF adapters on Windows / unknown platforms."""
    try:
        from scapy.all import get_if_list, get_if_hwaddr  # type: ignore
        return [
            WirelessInterface(name=name, mac=get_if_hwaddr(name))
            for name in get_if_list()
        ]
    except Exception as e:
        log.debug("Could not enumerate interfaces via Scapy: %s", e)
        return []


_IW_PHY_CACHE: dict[str, str] = {}


def _iface_phy(iface: str) -> str:
    """Resolve the wireless PHY name for an interface (cached)."""
    if iface in _IW_PHY_CACHE:
        return _IW_PHY_CACHE[iface]
    link = os.path.realpath(f"/sys/class/net/{iface}/phy80211")
    phy = os.path.basename(link)
    _IW_PHY_CACHE[iface] = phy
    return phy


def _supports_monitor(iface: str) -> bool:
    """Return True if the interface supports monitor mode."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        result = run(["iw", "phy", _iface_phy(iface), "info"], check=False)
    except RuntimeError:
        return False
    return "monitor" in result.stdout.split()


def prompt_for_interface() -> WirelessInterface:
    """Show discovered interfaces and let the user pick one."""
    ifaces = list_interfaces()
    if not ifaces:
        raise RuntimeError(
            "No wireless interfaces detected. Plug in an adapter and try again."
        )

    print(C.wrap("\nDetected wireless interfaces:", C.BOLD))
    for i, iface in enumerate(ifaces, 1):
        tag = C.wrap("[monitor-capable]", C.GREEN) if iface.monitor_capable \
              else C.wrap("[managed only]",   C.YELLOW)
        print(f"  {i}. {iface.name:<10} {iface.mac or '??':<18} {tag}")

    while True:
        try:
            choice = input(C.wrap("Select interface [1]: ", C.BOLD)).strip() or "1"
            idx = int(choice) - 1
            if 0 <= idx < len(ifaces):
                picked = ifaces[idx]
                if not picked.monitor_capable:
                    log.warning(
                        "%s may not support monitor mode; air will still try.",
                        picked.name,
                    )
                return picked
        except ValueError:
            pass
        print(C.wrap("Invalid selection, try again.", C.RED))


def enable_monitor(iface: str) -> str:
    """Switch `iface` into monitor mode. Returns the actual sniff interface.

    Prefers `airmon-ng` (handles NetworkManager / wpa_supplicant, creates a
    virtual `<iface>mon`). Falls back to raw `iw` if airmon-ng is missing
    or fails.
    """
    if not sys.platform.startswith("linux"):
        raise RuntimeError(
            "Monitor mode is only supported on Linux. Your platform: "
            f"{sys.platform}. Use an external adapter or a Linux host."
        )

    airmon = shutil.which("airmon-ng")
    if airmon:
        try:
            return _enable_monitor_airmon(iface, airmon)
        except RuntimeError as e:
            log.warning("airmon-ng path failed (%s); falling back to `iw`", e)

    require_tool("iw")
    log.info("Switching %s into monitor mode via `iw`", iface)
    run(["ip", "link", "set", iface, "down"], check=False)
    run(["iw", "dev", iface, "set", "type", "monitor"], check=False)
    run(["ip", "link", "set", iface, "up"], check=False)

    state = read_state(iface)
    if state.mode != "monitor":
        raise RuntimeError(
            f"Failed to set {iface} to monitor mode (still '{state.mode}'). "
            "Driver may not support monitor mode, or the adapter is busy "
            "(try `sudo airmon-ng check kill` first)."
        )
    log.info("%s is now in %s mode", iface, C.wrap("monitor", C.GREEN, C.BOLD))
    return iface


def _enable_monitor_airmon(iface: str, airmon: str) -> str:
    """Use airmon-ng: kill NM/wpa_supplicant, start monitor, verify, return iface name."""
    log.info("Switching %s into monitor mode via airmon-ng", iface)

    try:
        result = run([airmon, "check", "kill"], check=False, timeout=15.0)
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and "killed" in line.lower():
                log.info("airmon-ng: %s", line)
    except RuntimeError as e:
        log.debug("airmon-ng check kill returned non-zero: %s", e)

    result = run([airmon, "start", iface], check=False, timeout=15.0)
    if result.code != 0:
        raise RuntimeError(
            f"airmon-ng start failed:\n{result.stderr.strip() or result.stdout.strip()}"
        )

    monitor_iface = _parse_airmon_output(result.stdout, iface) or f"{iface}mon"

    state = read_state(monitor_iface)
    if state.mode != "monitor":
        raise RuntimeError(
            f"airmon-ng reported success but {monitor_iface} is in '{state.mode}' "
            "mode. The driver may not support monitor mode."
        )

    log.info(
        "%s is now in monitor mode (using %s)",
        iface, C.wrap(monitor_iface, C.GREEN, C.BOLD),
    )
    return monitor_iface


def _parse_airmon_output(stdout: str, original_iface: str) -> Optional[str]:
    """Extract the monitor interface name from airmon-ng's output.

    Example lines:
        (mac80211 monitor mode vif enabled on [phy0]wlan0mon)
        (mac80211 station mode vif disabled for [phy0]wlan0)
    """
    for raw in stdout.splitlines():
        line = raw.strip().strip("()")
        if "enabled on" in line:
            parts = line.split()
            for i, tok in enumerate(parts):
                if tok == "on" and i + 1 < len(parts):
                    bracket = parts[i + 1]
                    if bracket.startswith("["):
                        return bracket.rsplit("]", 1)[-1]
                    return bracket
    return None


def disable_monitor(iface: str) -> None:
    """Restore managed mode and bring the interface up.

    If `iface` is a virtual monitor interface (ends with `mon`), try
    `airmon-ng stop` first, then defensively restore via raw `iw` and
    restart NetworkManager.
    """
    if not sys.platform.startswith("linux"):
        return
    log.info("Restoring %s to managed mode", iface)

    target = iface[:-3] if iface.endswith("mon") else iface

    airmon = shutil.which("airmon-ng")
    if airmon and iface.endswith("mon"):
        try:
            run([airmon, "stop", iface], check=False, timeout=15.0)
            log.info("airmon-ng stopped %s; original %s restored", iface, target)
        except RuntimeError as e:
            log.warning("airmon-ng stop failed (%s); using raw `iw`", e)

    if os.path.isfile(f"/sys/class/net/{target}"):
        run(["ip", "link", "set", target, "down"], check=False)
        run(["iw", "dev", target, "set", "type", "managed"], check=False)
        run(["ip", "link", "set", target, "up"], check=False)

    if os.path.isfile("/usr/bin/nmcli"):
        run_live(["nmcli", "device", "set", target, "managed", "yes"])
    if os.path.isfile("/usr/sbin/NetworkManager"):
        run_live(["systemctl", "start", "NetworkManager"])


def read_state(iface: str) -> WirelessInterface:
    """Return the current state of `iface` from `iw dev`."""
    info = WirelessInterface(name=iface)
    if not sys.platform.startswith("linux"):
        return info
    try:
        result = run(["iw", "dev", iface, "info"], check=False)
    except RuntimeError:
        return info
    for line in result.stdout.splitlines():
        if "addr" in line:
            info.mac = line.split()[-1].upper()
        if "type" in line:
            info.mode = line.split()[-1]
    return info


WIFI_24_CHANNELS = list(range(1, 14))      # 1..13 (most countries); 14 = JP only
WIFI_5_CHANNELS  = [36, 40, 44, 48, 52, 56, 60, 64,
                    100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144,
                    149, 153, 157, 161, 165]

ALL_CHANNELS = WIFI_24_CHANNELS + WIFI_5_CHANNELS


def set_channel(iface: str, channel: int) -> None:
    """Pin `iface` to the given channel (must already be in monitor mode)."""
    require_tool("iw")
    try:
        run(["iw", "dev", iface, "set", "channel", str(channel)], timeout=5.0)
    except RuntimeError as e:
        raise RuntimeError(f"Could not set {iface} to channel {channel}: {e}") from e


class ChannelHopper:
    """Background thread that cycles `iface` through `channels` at `interval`s."""

    def __init__(self, iface: str, channels: Iterable[int] = ALL_CHANNELS,
                 interval: float = 0.5) -> None:
        self.iface = iface
        self.channels = list(channels) or ALL_CHANNELS
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def __enter__(self) -> "ChannelHopper":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name=f"ChannelHopper({self.iface})", daemon=True,
        )
        self._thread.start()
        log.debug(
            "Channel hopping %s across %d channels (every %.1fs)",
            self.iface, len(self.channels), self.interval,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        i = 0
        while not self._stop.is_set():
            ch = self.channels[i % len(self.channels)]
            with self._lock:
                try:
                    set_channel(self.iface, ch)
                except RuntimeError as e:
                    log.debug("hop channel %d failed: %s", ch, e)
            i += 1
            end = time.monotonic() + self.interval
            while not self._stop.is_set() and time.monotonic() < end:
                time.sleep(0.05)
