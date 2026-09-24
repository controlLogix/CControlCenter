"""Count usable addresses in IPv4 networks."""

import ipaddress


def hosts_in(cidr):
    """Return usable IPv4 hosts, including both /31 hosts and the /32 host.

    Reject invalid networks, including IPv6 and addresses with host bits set.
    """
    try:
        network = ipaddress.IPv4Network(cidr)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid IPv4 CIDR {cidr!r}: {exc}") from exc

    if network.prefixlen == 31:
        return 2
    if network.prefixlen == 32:
        return 1
    return network.num_addresses - 2
