"""Tests for usable IPv4 host counts."""

import unittest

from orchtest.cidr import hosts_in


class HostsInTests(unittest.TestCase):
    def test_usable_host_counts(self):
        cases = (
            ("192.0.2.0/24", 254),
            ("192.0.2.0/31", 2),
            ("192.0.2.1/32", 1),
            ("192.0.2.0/30", 2),
        )
        for cidr, expected in cases:
            with self.subTest(cidr=cidr):
                self.assertEqual(hosts_in(cidr), expected)

    def test_malformed_cidr_is_refused_with_reason(self):
        with self.assertRaisesRegex(ValueError, "Invalid IPv4 CIDR.*not-a-cidr"):
            hosts_in("not-a-cidr")

    def test_ipv6_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Invalid IPv4 CIDR"):
            hosts_in("2001:db8::/64")

    def test_host_bits_are_refused(self):
        with self.assertRaisesRegex(ValueError, "host bits set"):
            hosts_in("192.0.2.1/24")


if __name__ == "__main__":
    unittest.main()
