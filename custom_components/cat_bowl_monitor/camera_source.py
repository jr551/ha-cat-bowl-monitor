"""Safe camera-source helpers."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.request import Request, urlopen


def private_esphome_snapshot_url(host: str) -> str | None:
    """Return the known ESPHome snapshot endpoint for a private IP address."""
    try:
        address = ip_address(host.strip())
    except ValueError:
        return None
    if not (address.is_private or address.is_link_local):
        return None
    rendered = f"[{address}]" if address.version == 6 else str(address)
    return f"http://{rendered}:8081/"


def fetch_bounded_snapshot(url: str, max_bytes: int, timeout: int) -> bytes:
    """Fetch one trusted local snapshot with strict size and time bounds."""
    request = Request(url, headers={"Connection": "close"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise OSError(f"Snapshot returned HTTP {response.status}")
        content = response.read(max_bytes + 1)
    if not 0 < len(content) <= max_bytes:
        raise OSError("Snapshot size was invalid")
    return content
