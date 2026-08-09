"""
service_discovery — UDP-broadcast service discovery (zeroconf mDNS optional).

### PART-META-JSON
{
  "name": "service_discovery",
  "layer": "network",
  "purpose": "Real service discovery over UDP: announcers broadcast JSON service records, a listener thread collects/dedupes them into ServiceInfo objects. NOT full mDNS/DNS-SD - a simple JSON-datagram protocol; if the optional 'zeroconf' package is installed, discover_mdns_services() provides real mDNS browsing.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Service records (name, type, address, port, properties); discovery port/interface; optional zeroconf for true mDNS.",
  "outputs": "List[ServiceInfo] of discovered services; UDP announcement datagrams.",
  "files_created": [],
  "security_notes": "Announcements are UNAUTHENTICATED broadcast JSON - any LAN host can announce or observe; never trust discovered addresses without an app-level handshake. Datagrams are capped at 8 KiB and parsed with json.loads (malformed input ignored, never eval). Selftest binds loopback only (127.0.0.1, ephemeral port) - no external network traffic.",
  "ai_usage": "sd = ServiceDiscovery(port=48653); sd.start(); ... sd.get_discovered_services(); sd.stop(). Announce with ServiceAnnouncer(ServiceInfo(...), target=('255.255.255.255', 48653)).announce_once(). discover_services(type_, timeout=) for one-shot browse.",
  "example": "from scrapyard.network.service_discovery import ServiceDiscovery, ServiceAnnouncer, ServiceInfo",
  "import_path": "scrapyard.network.service_discovery"
}
### END-PART-META
"""
from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass, field
from ipaddress import IPv4Address
from threading import Event, Thread
from time import sleep, time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STATUS = "core"

MAGIC = "scrapyard-sd-v1"
DEFAULT_PORT = 48653
MAX_DATAGRAM = 8192


@dataclass
class ServiceInfo:
    name: str
    type_: str
    address: IPv4Address
    port: int
    properties: Dict[str, Any] = field(default_factory=dict)

    def key(self) -> Tuple[str, str, str, int]:
        return (self.name, self.type_, str(self.address), self.port)

    def to_payload(self) -> bytes:
        return json.dumps({
            "magic": MAGIC, "name": self.name, "type": self.type_,
            "address": str(self.address), "port": self.port,
            "properties": self.properties,
        }).encode()

    @classmethod
    def from_payload(cls, data: bytes) -> Optional["ServiceInfo"]:
        """Parse an announcement datagram; returns None for anything malformed."""
        try:
            obj = json.loads(data.decode("utf-8"))
            if not isinstance(obj, dict) or obj.get("magic") != MAGIC:
                return None
            return cls(name=str(obj["name"]), type_=str(obj["type"]),
                       address=IPv4Address(obj["address"]), port=int(obj["port"]),
                       properties=dict(obj.get("properties", {})))
        except Exception:
            return None


class ServiceAnnouncer:
    """Broadcasts a service record as a UDP JSON datagram."""

    def __init__(self, service: ServiceInfo,
                 target: Tuple[str, int] = ("255.255.255.255", DEFAULT_PORT)):
        self.service = service
        self.target = target

    def announce_once(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if self.target[0].endswith(".255") or self.target[0] == "255.255.255.255":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(self.service.to_payload(), self.target)
        finally:
            sock.close()

    def announce_periodically(self, interval: float, stop: Event) -> None:
        while not stop.is_set():
            self.announce_once()
            stop.wait(interval)


class ServiceDiscovery:
    """Listens for UDP announcements and collects deduplicated ServiceInfo records."""

    def __init__(self, interface: str = "0.0.0.0", port: int = DEFAULT_PORT):
        self.interface = interface
        self.port = port
        self._services: Dict[Tuple, ServiceInfo] = {}
        self.stopped = Event()
        self.thread: Optional[Thread] = None
        self._sock: Optional[socket.socket] = None

    @property
    def bound_port(self) -> int:
        """Actual port after start() (useful when constructed with port=0)."""
        return self._sock.getsockname()[1] if self._sock else self.port

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            logger.warning("Service discovery is already running.")
            return
        self.stopped.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.interface, self.port))
        self._sock.settimeout(0.25)
        self.thread = Thread(target=self._run_discovery, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self.thread or not self.thread.is_alive():
            logger.warning("Service discovery is not running.")
            return
        self.stopped.set()
        self.thread.join(timeout=5)
        if self._sock:
            self._sock.close()
            self._sock = None

    def clear(self) -> None:
        self._services.clear()

    def get_discovered_services(self, service_type: Optional[str] = None) -> List[ServiceInfo]:
        services = list(self._services.values())
        if service_type:
            services = [s for s in services if s.type_ == service_type]
        return services

    def _run_discovery(self) -> None:
        """REAL receive loop: reads datagrams, parses, dedupes by service key."""
        while not self.stopped.is_set():
            try:
                data, addr = self._sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            except OSError:
                break  # socket closed during stop()
            info = ServiceInfo.from_payload(data)
            if info is None:
                logger.debug("ignoring malformed announcement from %s", addr)
                continue
            self._services[info.key()] = info


def discover_services(service_type: str, timeout: float = 5.0,
                      interface: str = "0.0.0.0",
                      port: int = DEFAULT_PORT) -> List[ServiceInfo]:
    """One-shot browse: listen for `timeout` seconds, return matching services."""
    sd = ServiceDiscovery(interface=interface, port=port)
    sd.start()
    deadline = time() + timeout
    try:
        while time() < deadline:
            sleep(min(0.1, max(0.0, deadline - time())))
    finally:
        sd.stop()
    return sd.get_discovered_services(service_type)


def discover_mdns_services(service_type: str = "_http._tcp.local.",
                           timeout: float = 3.0) -> List[ServiceInfo]:
    """True mDNS browsing IF the optional zeroconf package is installed."""
    try:
        from zeroconf import Zeroconf, ServiceBrowser  # lazy optional import
    except ImportError as e:
        raise RuntimeError(
            "mDNS browsing requires the optional 'zeroconf' package "
            "(pip install zeroconf); use ServiceDiscovery for the built-in "
            "UDP-broadcast protocol instead") from e

    found: List[ServiceInfo] = []

    class _Listener:
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=int(timeout * 1000))
            if info and info.addresses:
                found.append(ServiceInfo(
                    name=name, type_=type_,
                    address=IPv4Address(socket.inet_ntoa(info.addresses[0])),
                    port=info.port,
                    properties={k.decode() if isinstance(k, bytes) else k:
                                v.decode() if isinstance(v, bytes) else v
                                for k, v in (info.properties or {}).items()}))

        def update_service(self, zc, type_, name):
            self.remove_service(zc, type_, name)
            self.add_service(zc, type_, name)

        def remove_service(self, zc, type_, name):
            found[:] = [item for item in found
                        if not (item.name == name and item.type_ == type_)]

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, service_type, _Listener())
        sleep(timeout)
    finally:
        zc.close()
    return found


def _selftest():
    # Loopback-only: bind an ephemeral port on 127.0.0.1, announce to it, discover.
    sd = ServiceDiscovery(interface="127.0.0.1", port=0)
    sd.start()
    try:
        port = sd.bound_port
        assert port > 0

        svc = ServiceInfo(name="api-1", type_="_http._tcp",
                          address=IPv4Address("127.0.0.1"), port=8080,
                          properties={"version": "2"})
        ann = ServiceAnnouncer(svc, target=("127.0.0.1", port))
        ann.announce_once()
        ann.announce_once()  # duplicate announcement must dedupe

        # malformed datagrams are ignored, never crash the loop
        junk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        junk.sendto(b"not json at all", ("127.0.0.1", port))
        junk.sendto(b'{"magic": "wrong"}', ("127.0.0.1", port))
        junk.close()

        # second distinct service
        svc2 = ServiceInfo(name="worker-1", type_="_job._tcp",
                           address=IPv4Address("127.0.0.1"), port=9000)
        ServiceAnnouncer(svc2, target=("127.0.0.1", port)).announce_once()

        deadline = time() + 5.0
        while time() < deadline and len(sd.get_discovered_services()) < 2:
            sleep(0.05)

        all_svcs = sd.get_discovered_services()
        assert len(all_svcs) == 2, [s.key() for s in all_svcs]  # deduped + junk ignored
        http = sd.get_discovered_services("_http._tcp")
        assert len(http) == 1 and http[0].name == "api-1"
        assert http[0].properties == {"version": "2"}
        assert http[0].address == IPv4Address("127.0.0.1") and http[0].port == 8080
    finally:
        sd.stop()

    # payload roundtrip + malformed rejection
    p = svc.to_payload()
    back = ServiceInfo.from_payload(p)
    assert back == svc
    assert ServiceInfo.from_payload(b"\xff\xfe") is None
    assert ServiceInfo.from_payload(b'{"no": "magic"}') is None

    # start/stop lifecycle is safe to repeat
    sd2 = ServiceDiscovery(interface="127.0.0.1", port=0)
    sd2.start()
    sd2.start()  # warns, no crash
    sd2.stop()
    sd2.stop()   # warns, no crash

    print("service_discovery selftest OK")


if __name__ == "__main__":
    _selftest()
    raise SystemExit(0)
