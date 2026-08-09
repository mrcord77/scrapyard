"""
network_utility — Hostname/IP resolution and network interface discovery.

### PART-META-JSON
{
  "name": "network_utility",
  "layer": "network",
  "purpose": "Hostname-to-IP resolution (resolve_ip) and network interface enumeration (get_network_interfaces) with a netifaces fast path and a stdlib loopback fallback.",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Hostnames to resolve; optional 'netifaces' package for full interface detail (lazy import).",
  "outputs": "IP strings (or None on resolution failure); list of interface dicts {name, ipv4, ipv6, mac}.",
  "files_created": [],
  "security_notes": "resolve_ip performs DNS lookups - resolving attacker-supplied hostnames can leak queries to DNS; interface data (IPs/MACs) is host-identifying, avoid logging it verbatim. Selftest resolves 'localhost' only.",
  "ai_usage": "Import what you need from `scrapyard.network.network_utility`.",
  "example": "from scrapyard.network.network_utility import *",
  "import_path": "scrapyard.network.network_utility"
}
### END-PART-META
"""
import re
import logging
import socket
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def resolve_ip(host: str) -> Optional[str]:
    """Resolve hostname to IP address with fallback and error handling."""
    try:
        return socket.gethostbyname(host)
    except socket.gaierror as e:
        logger.error(f"Failed to resolve IP for {host}: {e}")
        return None


def get_network_interfaces() -> List[Dict[str, Any]]:
    """Retrieve detailed network interface information including names, IPs, and MACs."""
    interfaces: List[Dict[str, Any]] = []
    
    # Primary implementation using netifaces (loaded lazily)
    try:
        import netifaces as ni
        
        for interface_name in ni.interfaces():
            try:
                addr_info = ni.ifaddresses(interface_name)
            except (ValueError, KeyError):
                continue
            
            interface_data: Dict[str, Any] = {
                'name': interface_name,
                'ipv4': None,
                'ipv6': None,
                'mac': None
            }
            
            # Extract IPv4 address
            if ni.AF_INET in addr_info:
                info = addr_info[ni.AF_INET][0]
                interface_data['ipv4'] = info.get('addr')
            
            # Extract IPv6 address (remove scope ID if present)
            if ni.AF_INET6 in addr_info:
                info = addr_info[ni.AF_INET6][0]
                raw_addr = info.get('addr', '')
                # Remove scope ID (e.g., %eth0) if present
                addr = raw_addr.split('%')[0] if '%' in raw_addr else raw_addr
                interface_data['ipv6'] = addr if addr else None
            
            # Extract MAC address and normalize format
            if ni.AF_LINK in addr_info:
                info = addr_info[ni.AF_LINK][0]
                mac_addr = info.get('addr', '')
                if mac_addr:
                    # Remove existing separators and normalize
                    mac_clean = mac_addr.replace(':', '').replace('-', '')
                    if len(mac_clean) == 12:
                        interface_data['mac'] = ':'.join(re.findall('..', mac_clean))
                    else:
                        interface_data['mac'] = mac_addr
            
            interfaces.append(interface_data)
        
        if interfaces:
            return interfaces
            
    except ImportError:
        logger.debug("netifaces not available, using fallback")
    except Exception as e:
        logger.error(f"Error retrieving interfaces via netifaces: {e}")
    
    # Fallback implementation using standard library
    try:
        # Attempt to get localhost information as minimal valid interface data
        localhost_ip = socket.gethostbyname('localhost')
        interfaces.append({
            'name': 'lo',
            'ipv4': localhost_ip,
            'ipv6': '::1',
            'mac': '00:00:00:00:00:00'
        })
    except Exception as e:
        logger.error(f"Failed to retrieve fallback interface data: {e}")
    
    return interfaces


def _selftest():
    """Offline self-test with no external network calls."""
    # Test resolve_ip
    ip = resolve_ip('localhost')
    assert ip is not None, "resolve_ip failed for localhost"
    
    # Test get_network_interfaces
    interfaces = get_network_interfaces()
    assert len(interfaces) > 0, "No network interfaces found"
    for interface in interfaces:
        if 'name' in interface and 'ipv4' in interface or 'ipv6' in interface or 'mac' in interface:
            break
    else:
        raise AssertionError("Interface details not found")


if __name__ == "__main__":
    _selftest()
