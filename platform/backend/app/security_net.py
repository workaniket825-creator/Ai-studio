"""SSRF guard for outbound tool/webhook calls.

Tool execution (OpenAPI operations, function webhooks) makes HTTP requests to
URLs supplied via specs. Without a guard, an agent could be steered into calling
internal services (cloud metadata, admin endpoints). This blocks private/loopback/
link-local addresses by default; specific internal hosts can be allow-listed from
Governance -> Platform Settings (no backend edits needed).
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse


class BlockedURLError(Exception):
    pass


def check_url(url: str) -> None:
    """Raise BlockedURLError if the URL is not permitted by current settings."""
    from .governance import platform_settings
    ps = platform_settings()
    if not ps.get("ssrf_block_private", True):
        return  # guard disabled by admin

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedURLError(f"unsupported URL scheme: {parsed.scheme or '(none)'}")
    host = parsed.hostname
    if not host:
        raise BlockedURLError("URL has no host")

    allowed = {h.strip().lower() for h in ps.get("ssrf_allowed_hosts", []) if h.strip()}
    if host.lower() in allowed:
        return  # explicitly permitted internal host

    # resolve and reject private / loopback / link-local / reserved addresses
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as e:
        raise BlockedURLError(f"could not resolve host '{host}': {e}")
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast):
            raise BlockedURLError(
                f"blocked call to internal address {ip} (host '{host}'). "
                "Add it under Governance -> Platform Settings -> allowed hosts if intended.")
