"""
port_scanner — Async TCP port scanner (asyncio open_connection probes).

### PART-META-JSON
{
  "name": "port_scanner",
  "layer": "network",
  "purpose": "Async TCP port scanner: probes host:port ranges concurrently with asyncio.open_connection and reports open/closed per port.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Hostname/IP and port list or range; per-connection timeout.",
  "outputs": "Per-port result dicts (host, port, open/closed, error detail).",
  "files_created": [],
  "security_notes": "Port scanning hosts you do not own may violate policy/law - scan only your own services. Probes are plain TCP connects (no payload sent). Selftest scans loopback only.",
  "ai_usage": "Import what you need from `scrapyard.network.port_scanner`.",
  "example": "from scrapyard.network.port_scanner import *",
  "import_path": "scrapyard.network.port_scanner"
}
### END-PART-META
"""
import asyncio
from typing import List, Dict, Any
import socket
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def scan_port(host: str, port: int) -> Dict[str, Any]:
    """
    Asynchronously scan a single port on the given host.
    
    :param host: The hostname or IP address to scan.
    :param port: The port number to scan.
    :return: A dictionary containing the result of the scan.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        writer.close()
        await writer.wait_closed()
        return {"port": port, "status": "open", "service": socket.getservbyport(port), "protocol": "TCP"}
    except (ConnectionRefusedError, OSError):
        return {"port": port, "status": "closed", "service": None, "protocol": "TCP"}

async def scan_ports(host: str, start: int, end: int) -> List[Dict[str, Any]]:
    """
    Scan a range of ports on the given host.
    
    :param host: The hostname or IP address to scan.
    :param start: The starting port number in the range.
    :param end: The ending port number in the range.
    :return: A list of dictionaries containing the results of the scans.
    """
    tasks = [scan_port(host, port) for port in range(start, end + 1)]
    results = await asyncio.gather(*tasks)
    return results

def _selftest() -> None:
    """
    Self-test function to validate the functionality of the module.
    
    :return: None
    """
    host = "localhost"
    start_port = 20
    end_port = 100
    
    logger.info(f"Scanning ports {start_port} to {end_port} on {host}")
    results = asyncio.run(scan_ports(host, start_port, end_port))
    
    assert len(results) > 0, "Scan did not return any results"
    for result in results:
        assert isinstance(result, dict), "Result is not a dictionary"
        assert set(result.keys()) == {"port", "status", "service", "protocol"}, "Result dictionary keys are incorrect"
    
    logger.info("Self-test passed successfully")

if __name__ == "__main__":
    _selftest()
