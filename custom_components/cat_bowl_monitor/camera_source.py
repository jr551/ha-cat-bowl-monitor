"""Safe camera-source helpers."""

from __future__ import annotations

from ipaddress import ip_address


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
