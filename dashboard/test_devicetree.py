"""The device tree: several kinds of knowing, merged without flattening them.

THE PROPERTY UNDER TEST is not "the merge works" but "a guess and a statement
never end up looking the same". A TCP connect answering on 44818 with a Rockwell
OUI is an inference; a device that answered ListIdentity with its own serial
told you. A panel that renders both as a confident "vendor" is the same class of
lie as an un-aged value on the tag table.

So the tests that matter here are the negative ones: disagreement is kept rather
than resolved, a port sweep does not acquire an identity it never had, and a
bare address is not promoted into an inventory as though it were a device.

No network anywhere - every function is pure, driven from recorded shapes.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import devicetree
except ImportError as exc:
    devicetree = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


# Recorded shapes, as each module actually produces them.
SCANNED = [
    {"address": "10.0.0.5", "hostname": "plc-line1", "mac": "00:00:bc:11:22:33",
     "vendor": "Rockwell Automation", "ports": [{"port": 44818, "service": "ethernet-ip"},
                                                {"port": 80, "service": "http"}]},
    {"address": "10.0.0.9", "hostname": None, "mac": "00:80:41:aa:bb:cc",
     "vendor": "Vemotec GmbH", "ports": [{"port": 502, "service": "modbus"}]},
    {"address": "10.0.0.40", "hostname": None, "mac": None, "vendor": None,
     "ports": [{"port": 22, "service": "ssh"}]},
]

IDENTIFIED = [
    {"ip_address": "10.0.0.5", "product_name": "1756-L83E/B", "product_code": 168,
     "vendor": "Rockwell Automation/Allen-Bradley", "device_type": "Programmable Logic Controller",
     "revision": "32.11", "serial": "a1b2c3d4", "state": 3, "status": 96,
     "origin": "cip-listidentity"},
]


class _NeedsTree(unittest.TestCase):
    def setUp(self):
        if devicetree is None:
            self.fail(f'dashboard/devicetree.py is missing: {IMPORT_ERROR}')


class OriginTests(_NeedsTree):
    def test_every_row_says_which_sources_reported_it(self):
        rows = {r["address"]: r for r in devicetree.merge(SCANNED, IDENTIFIED)}
        self.assertEqual(rows["10.0.0.5"]["sources"], ["segment-scan", "cip-listidentity"])
        self.assertEqual(rows["10.0.0.9"]["sources"], ["segment-scan"])

    def test_a_port_sweep_alone_gets_no_identity(self):
        # The most important negative here. Something answered on 502 and the
        # OUI suggests a vendor - that is all anyone knows, and the row must not
        # imply otherwise.
        row = {r["address"]: r for r in devicetree.merge(SCANNED, IDENTIFIED)}["10.0.0.9"]
        self.assertIsNone(row["identity"])
        self.assertEqual(row["sources"], ["segment-scan"])
        self.assertEqual(row["vendor_source"], "segment-scan (OUI)")
        self.assertNotIn("said so", row["vendor_source"])

    def test_a_vendor_the_device_reported_is_marked_as_such(self):
        row = {r["address"]: r for r in devicetree.merge(SCANNED, IDENTIFIED)}["10.0.0.5"]
        self.assertIn("the device said so", row["vendor_source"])
        self.assertEqual(row["identity"]["serial"], "a1b2c3d4")

    def test_a_field_nobody_reported_stays_none_rather_than_blank(self):
        # A blank string reads as "nothing there"; None with no source beside it
        # reads as "nobody said". The panel renders them differently.
        row = {r["address"]: r for r in devicetree.merge(SCANNED)}["10.0.0.40"]
        self.assertIsNone(row["vendor"])
        self.assertIsNone(row["vendor_source"])
        self.assertIsNone(row["mac"])


class ConflictTests(_NeedsTree):
    def test_two_sources_disagreeing_are_both_kept_and_flagged(self):
        # The OUI table says "Rockwell Automation"; the device says "Rockwell
        # Automation/Allen-Bradley". Which is right is a question for a person -
        # picking a winner silently is how the wrong one ends up on screen with
        # nothing to say it was ever in doubt.
        row = {r["address"]: r for r in devicetree.merge(SCANNED, IDENTIFIED)}["10.0.0.5"]
        self.assertEqual(len(row["conflicts"]), 1)
        conflict = row["conflicts"][0]
        self.assertEqual(conflict["field"], "vendor")
        values = {v["value"] for v in conflict["values"]}
        self.assertEqual(values, {"Rockwell Automation",
                                  "Rockwell Automation/Allen-Bradley"})
        # Both sources are named, so the disagreement is actionable.
        self.assertTrue(all(v["source"] for v in conflict["values"]))

    def test_agreement_raises_no_conflict(self):
        # The negative that makes the flag mean something.
        agreeing = [dict(IDENTIFIED[0], vendor="Rockwell Automation")]
        row = {r["address"]: r for r in devicetree.merge(SCANNED, agreeing)}["10.0.0.5"]
        self.assertEqual(row["conflicts"], [])

    def test_the_tree_counts_conflicts_so_they_cannot_be_missed(self):
        summary = devicetree.tree(devicetree.merge(SCANNED, IDENTIFIED))
        self.assertEqual(summary["conflicts"], 1)


class GroupingTests(_NeedsTree):
    def test_devices_group_by_subnet_and_sort_numerically(self):
        rows = devicetree.merge(SCANNED, IDENTIFIED)
        # .40 after .9, which string sorting gets wrong.
        self.assertEqual([r["address"] for r in rows],
                         ["10.0.0.5", "10.0.0.9", "10.0.0.40"])
        summary = devicetree.tree(rows)
        self.assertEqual(len(summary["groups"]), 1)
        self.assertEqual(summary["groups"][0]["network"], "10.0.0.0/24")
        self.assertEqual(summary["total"], 3)

    def test_the_group_counts_how_many_actually_identified_themselves(self):
        # The difference between "three things answered a port" and "one of them
        # told us what it is" is the whole point of the panel.
        summary = devicetree.tree(devicetree.merge(SCANNED, IDENTIFIED))
        self.assertEqual(summary["groups"][0]["count"], 3)
        self.assertEqual(summary["groups"][0]["self_reported"], 1)

    def test_an_unparseable_address_is_grouped_rather_than_dropped(self):
        rows = devicetree.merge([{"address": "not-an-ip", "ports": []}])
        summary = devicetree.tree(rows)
        self.assertEqual(summary["groups"][0]["network"], "unknown")
        self.assertEqual(summary["total"], 1)

    def test_an_empty_address_is_ignored_rather_than_making_a_blank_row(self):
        rows = devicetree.merge([{"address": "", "ports": []},
                                 {"address": None, "ports": []}])
        self.assertEqual(rows, [])


class OpcuaTests(_NeedsTree):
    def test_opcua_is_optional_and_its_absence_is_not_an_error(self):
        # ADR-0019: the embedded server is firmware- and SKU-dependent, so zero
        # endpoints is the normal case and must not degrade the rest.
        rows = devicetree.merge(SCANNED, IDENTIFIED, endpoints=[])
        row = {r["address"]: r for r in rows}["10.0.0.5"]
        self.assertEqual(row["endpoints"], [])
        self.assertNotIn("opcua-endpoints", row["sources"])

    def test_endpoints_are_recorded_against_their_address(self):
        rows = devicetree.merge(SCANNED, IDENTIFIED, endpoints=[
            {"address": "10.0.0.5", "endpoints": [{"url": "opc.tcp://10.0.0.5:4840",
                                                   "security": "Basic256Sha256"}]}])
        row = {r["address"]: r for r in rows}["10.0.0.5"]
        self.assertIn("opcua-endpoints", row["sources"])
        self.assertEqual(row["endpoints"][0]["security"], "Basic256Sha256")
        self.assertIn("opc-ua", row["suggested"])


class PromotionTests(_NeedsTree):
    def test_a_promoted_device_is_matched_to_what_the_scan_found(self):
        rows = devicetree.merge(SCANNED, IDENTIFIED, promoted=[
            {"id": 7, "name": "Line 1 PLC", "kind": "plc", "address": "10.0.0.5",
             "port": 44818, "protocol": "ethernet-ip"}])
        row = {r["address"]: r for r in rows}["10.0.0.5"]
        self.assertIn("promoted", row["sources"])
        self.assertEqual(row["promoted"]["name"], "Line 1 PLC")

    def test_promotion_uses_the_existing_devices_schema(self):
        # ccstore.py:67. A device tree that needed its own table would be a
        # second inventory to keep in step with the first.
        rows = devicetree.merge(SCANNED, IDENTIFIED)
        row = {r["address"]: r for r in rows}["10.0.0.5"]
        saved = devicetree.promotion_for(row)
        self.assertEqual(set(saved), {"name", "kind", "address", "port", "protocol"})
        self.assertEqual(saved["address"], "10.0.0.5")
        self.assertEqual(saved["protocol"], "ethernet-ip")
        self.assertEqual(saved["port"], 44818)
        # The name comes from what the device called itself, not the bare address.
        self.assertEqual(saved["name"], "1756-L83E/B")

    def test_promotion_records_how_the_device_was_found(self):
        rows = {r["address"]: r for r in devicetree.merge(SCANNED, IDENTIFIED)}
        self.assertEqual(devicetree.promotion_for(rows["10.0.0.5"])["kind"],
                         "cip-listidentity")
        # A port sweep is saved as a port sweep. The inventory keeps the
        # difference between a device that identified itself and one that
        # merely had a port open.
        self.assertEqual(devicetree.promotion_for(rows["10.0.0.9"])["kind"],
                         "segment-scan")

    def test_a_bare_address_with_no_protocol_is_not_promotable(self):
        # 10.0.0.40 has only ssh open. That is a ping reply, not an inventory
        # entry, and offering to save it would fill the device list with hosts.
        rows = {r["address"]: r for r in devicetree.merge(SCANNED)}
        self.assertIsNone(devicetree.promotion_for(rows["10.0.0.40"]))

    def test_an_explicit_name_wins_over_the_derived_one(self):
        rows = {r["address"]: r for r in devicetree.merge(SCANNED, IDENTIFIED)}
        saved = devicetree.promotion_for(rows["10.0.0.5"], name="Packer 3")
        self.assertEqual(saved["name"], "Packer 3")


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
