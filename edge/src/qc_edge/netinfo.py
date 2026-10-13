"""LAN address detection for the pairing QR code (SPEC-007 section 4.3).

No packet is sent: ``connect`` on a UDP socket only asks the kernel which local address would
route to the probe address.
"""

from __future__ import annotations

import ipaddress
import logging
import socket

logger = logging.getLogger("qc_edge")

# Private address that is never routed in practice; only used to pick the outgoing interface.
PROBE_ADDRESS = ("10.254.254.254", 1)
LOOPBACK_FALLBACK = "127.0.0.1"

_LOOPBACK = ipaddress.ip_network("127.0.0.0/8")
_LINK_LOCAL = ipaddress.ip_network("169.254.0.0/16")


def _udp_probe_address() -> str | None:
    """Local IPv4 the kernel would use to reach ``PROBE_ADDRESS``; ``None`` on failure."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return None
    try:
        sock.connect(PROBE_ADDRESS)
        return str(sock.getsockname()[0])
    except OSError:
        return None
    finally:
        sock.close()


def _hostname_addresses() -> list[str]:
    """IPv4 addresses the host name resolves to; empty on failure."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return [str(info[4][0]) for info in infos]


def _usable(candidate: str) -> bool:
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    return (
        address.version == 4
        and not address.is_unspecified
        and address not in _LOOPBACK
        and address not in _LINK_LOCAL
    )


def is_fallback(ips: list[str]) -> bool:
    """``True`` when ``ips`` is the loopback fallback (no LAN address was detected)."""
    return ips == [LOOPBACK_FALLBACK]


def detect_lan_ips() -> list[str]:
    """LAN IPv4 addresses of this host, the most likely one first.

    The UDP probe comes first; the host name addresses are added after it (they are the only
    source when the probe fails). Duplicates, ``127.0.0.0/8``, ``169.254.0.0/16`` and
    ``0.0.0.0`` are removed. With no candidate left, returns ``["127.0.0.1"]`` and logs a
    warning.
    """
    candidates: list[str] = []
    probed = _udp_probe_address()
    if probed is not None:
        candidates.append(probed)
    candidates.extend(_hostname_addresses())

    ips: list[str] = []
    for candidate in candidates:
        if _usable(candidate) and candidate not in ips:
            ips.append(candidate)
    if not ips:
        logger.warning(
            "no LAN IPv4 address detected; the pairing QR code uses %s and phones cannot reach "
            "it (connect the notebook to the Wi-Fi or to the phone hotspot)",
            LOOPBACK_FALLBACK,
        )
        return [LOOPBACK_FALLBACK]
    return ips
