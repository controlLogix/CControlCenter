"""One device tree from several kinds of knowing, without pretending they are equal.

WHAT THIS MERGES, and why the origins have to survive the merge:

  segment-scan      netscan.py. A TCP connect answered on port 44818, and the MAC
                    resolved to a vendor through an OUI table. That is an
                    INFERENCE: something is listening, and the NIC was sold by
                    Rockwell. It is not the device telling you what it is.
  cip-listidentity  rockwell.discover(). A UDP broadcast the device ANSWERED,
                    with its own vendor, product code, revision, serial and
                    state. The device said so.
  opcua-endpoints   getEndpoints(). Also self-reported, and also optional - the
                    embedded server is firmware- and SKU-dependent (ADR-0019).
  promoted          a row the operator already saved in cc.db.

Collapsing those into one "vendor" field would be the same class of lie as an
un-aged value on the tag table: a screen that looks equally confident about a
guess and a statement. So every row carries `sources`, every field that came
from somewhere carries where, and a row that is only a port sweep says so.

DISAGREEMENT IS DATA, NOT AN ERROR TO RESOLVE. If the OUI table says one vendor
and the device says another, both are recorded and the row is flagged. Picking a
winner - newest, most specific, highest priority - is how the wrong one ends up
on screen with nothing to say it was ever in doubt. Same rule as the merged tag
table in the plan: two sources, two records, the disagreement shown.

NO NETWORK HERE. Every function is pure, so the merge can be tested against
recorded output from a real scan and a real discovery without either.
"""

import ipaddress

# Ordered by how much the device itself told us, which is the order a reader
# should trust them in. Used for display, never to pick a winner.
SOURCES = ("promoted", "cip-listidentity", "opcua-endpoints", "segment-scan")

# Ports that mean "this is worth asking a protocol question", so the tree can
# suggest the next step rather than leaving a bare open port on screen.
PROTOCOL_PORTS = {
    44818: "ethernet-ip",
    502: "modbus-tcp",
    4840: "opc-ua",
    102: "s7comm",
    1883: "mqtt",
    8883: "mqtt-tls",
    48898: "ads",
    11740: "codesys",
}


def _blank(address):
    return {
        "address": address,
        "sources": [],
        # Every one of these is None until something reports it, and each is
        # paired with the source that did. A field with no source beside it is
        # a field nobody can be asked about.
        "hostname": None,
        "mac": None,
        "vendor": None,
        "vendor_source": None,
        "ports": [],
        "identity": None,
        "endpoints": [],
        "promoted": None,
        "conflicts": [],
        "suggested": [],
    }


def _note_conflict(row, field, a_value, a_source, b_value, b_source):
    """Record that two sources disagree. Never pick one."""
    row["conflicts"].append({
        "field": field,
        "values": [{"value": a_value, "source": a_source},
                   {"value": b_value, "source": b_source}],
    })


def _add_source(row, source):
    if source not in row["sources"]:
        row["sources"].append(source)


def _sort_key(row):
    """Numeric where the address is an IP, so .10 sorts after .9."""
    try:
        return (0, int(ipaddress.ip_address(row["address"])))
    except ValueError:
        return (1, 0)


def merge(scanned=(), identified=(), endpoints=(), promoted=()):
    """Build one row per address from every source that reported it.

    Each argument is a sequence of plain dicts as its own module produces them,
    so this can be driven from recorded output with no network:

      scanned     netscan snapshot()["hosts"]
      identified  rockwell.discover()
      endpoints   [{"address":..., "endpoints":[...]}]
      promoted    cc.db devices rows
    """
    rows = {}

    def row_for(address):
        address = str(address or "").strip()
        if not address:
            return None
        if address not in rows:
            rows[address] = _blank(address)
        return rows[address]

    # ── the port sweep: something is listening, and the OUI suggests a vendor ──
    for host in scanned or ():
        row = row_for(host.get("address"))
        if row is None:
            continue
        _add_source(row, "segment-scan")
        row["hostname"] = host.get("hostname") or row["hostname"]
        row["mac"] = host.get("mac") or row["mac"]
        if host.get("vendor"):
            row["vendor"] = host["vendor"]
            row["vendor_source"] = "segment-scan (OUI)"
        row["ports"] = list(host.get("ports") or [])
        for port in row["ports"]:
            protocol = PROTOCOL_PORTS.get(port.get("port"))
            if protocol and protocol not in row["suggested"]:
                row["suggested"].append(protocol)

    # ── CIP ListIdentity: the device's own account of itself ─────────────────
    for device in identified or ():
        row = row_for(device.get("ip_address"))
        if row is None:
            continue
        _add_source(row, "cip-listidentity")
        row["identity"] = {k: device.get(k) for k in
                           ("product_name", "product_code", "vendor", "device_type",
                            "revision", "serial", "state", "status")}
        said = device.get("vendor")
        if said:
            # The device told us. If the OUI guessed something else, BOTH are
            # kept and the row is flagged - the guess is not corrected away,
            # because which one is wrong is a question for a person.
            if row["vendor"] and row["vendor"] != said:
                _note_conflict(row, "vendor", row["vendor"], row["vendor_source"],
                               said, "cip-listidentity")
            row["vendor"] = said
            row["vendor_source"] = "cip-listidentity (the device said so)"
        if "ethernet-ip" not in row["suggested"]:
            row["suggested"].append("ethernet-ip")

    # ── OPC UA endpoints: optional, and absent is normal ─────────────────────
    for entry in endpoints or ():
        row = row_for(entry.get("address"))
        if row is None:
            continue
        _add_source(row, "opcua-endpoints")
        row["endpoints"] = list(entry.get("endpoints") or [])
        if "opc-ua" not in row["suggested"]:
            row["suggested"].append("opc-ua")

    # ── what the operator already saved ──────────────────────────────────────
    for device in promoted or ():
        row = row_for(device.get("address"))
        if row is None:
            continue
        _add_source(row, "promoted")
        row["promoted"] = {k: device.get(k) for k in
                           ("id", "name", "kind", "port", "protocol")}

    return sorted(rows.values(), key=_sort_key)


def tree(rows, scan_request=None):
    """Group merged rows by subnet, for rendering.

    Grouped by the /24 the address falls in rather than by vendor or protocol,
    because that is how the person standing in front of the panel thinks about
    it: this cabinet, that cell.
    """
    groups = {}
    for row in rows:
        try:
            network = str(ipaddress.ip_network(row["address"] + "/24", strict=False))
        except ValueError:
            network = "unknown"
        groups.setdefault(network, []).append(row)

    return {
        "groups": [
            {
                "network": network,
                "devices": members,
                "count": len(members),
                # How many of these actually told us what they are, as opposed
                # to merely having a port open. The difference is the point of
                # the whole panel.
                "self_reported": sum(1 for m in members
                                     if "cip-listidentity" in m["sources"]
                                     or "opcua-endpoints" in m["sources"]),
            }
            for network, members in sorted(groups.items())
        ],
        "total": len(rows),
        "conflicts": sum(len(r["conflicts"]) for r in rows),
        # Echoed back so the panel can say what produced this, rather than
        # rendering a list with no provenance.
        "scan": scan_request,
        "sources": list(SOURCES),
    }


def promotion_for(row, name=None):
    """The cc.db `devices` row this device would be saved as.

    Deliberately uses the EXISTING schema (ccstore.py:67) - no new table and no
    new column. A device tree that needed its own store would be a second
    inventory to keep in step with the first.

    Returns None when there is nothing worth saving yet: a bare address with no
    protocol is not an inventory entry, it is a ping reply.
    """
    protocol = row["suggested"][0] if row["suggested"] else None
    if not protocol:
        return None
    port = next((p["port"] for p in row["ports"]
                 if PROTOCOL_PORTS.get(p["port"]) == protocol), None)
    identity = row.get("identity") or {}
    return {
        "name": name or identity.get("product_name") or row.get("hostname") or row["address"],
        # `kind` records HOW this was found, so an inventory entry does not lose
        # the difference between a device that identified itself and one that
        # merely had a port open.
        "kind": "cip-listidentity" if "cip-listidentity" in row["sources"] else "segment-scan",
        "address": row["address"],
        "port": port,
        "protocol": protocol,
    }
