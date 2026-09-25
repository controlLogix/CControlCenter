"""netscan internals that test_field_panels.py does not reach.

test_field_panels.py:392-455 already covers the range/port/actor guards, a real
loopback sweep, OUI resolution and the under_wsl flag. This file covers the parts
it does not: the ARP parsers, the WSL fallback branch, and the resilience
contract that neighbour_table's docstring claims.

WHY THIS FILE EXISTS. The scan died with a bare "OSError" on roughly 60% of e2e
runs. The cause was `Path(candidate).exists()` in the Windows-ARP fallback:
Path.exists() swallows only ENOENT/ENOTDIR/EBADF/ELOOP and re-raises everything
else, and a stat of /mnt/c under gate load raises EIO - the transient 9p failure
run_tests.sh already warns about. So a function documented "Never fatal" was
fatal, and a scan that had already found its host threw the result away.
"""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import netscan


class NeighbourTableIsNeverFatal(unittest.TestCase):
    """The docstring's promise, enforced."""

    def setUp(self):
        self._run_table = netscan._run_table
        self._under_wsl = netscan.running_under_wsl
        self._exists = Path.exists

    def tearDown(self):
        netscan._run_table = self._run_table
        netscan.running_under_wsl = self._under_wsl
        Path.exists = self._exists

    def _force_wsl_fallback(self, native=None):
        """One native entry only, which is what sends it to the Windows table."""
        native = native if native is not None else {'172.30.112.1': 'aa:bb:cc:dd:ee:ff'}
        netscan.running_under_wsl = lambda: True
        netscan._run_table = lambda argv, timeout=8: native if argv[0] == 'ip' else {}

    def test_eio_probing_the_windows_arp_binary_is_not_fatal(self):
        """The exact regression: a 9p stat raising EIO killed the whole scan."""
        self._force_wsl_fallback()

        def raise_eio(self):
            raise OSError(5, 'Input/output error')

        Path.exists = raise_eio
        table, source = netscan.neighbour_table()
        self.assertEqual(len(table), 1)
        self.assertIn('172.30.112.1', table)
        self.assertIsInstance(source, str)

    def test_any_oserror_from_the_probe_is_survived(self):
        """EIO is one errno; the contract is not a list of errnos."""
        for errno_value in (5, 13, 22, 122):
            with self.subTest(errno=errno_value):
                self._force_wsl_fallback()

                def raise_it(self, _e=errno_value):
                    raise OSError(_e, 'simulated')

                Path.exists = raise_it
                table, source = netscan.neighbour_table()
                self.assertIsInstance(table, dict)
                self.assertIsInstance(source, str)

    def test_a_missing_binary_is_skipped_quietly(self):
        """ENOENT was always handled; prove the guard did not break it."""
        self._force_wsl_fallback()
        Path.exists = lambda self: False
        table, source = netscan.neighbour_table()
        self.assertEqual(table, {'172.30.112.1': 'aa:bb:cc:dd:ee:ff'})
        self.assertEqual(source, 'this host')

    def test_the_windows_table_is_merged_under_the_native_one(self):
        """Native entries win: they were observed here, not one NAT hop away."""
        netscan.running_under_wsl = lambda: True

        def table(argv, timeout=8):
            if argv[0] == 'ip':
                return {'10.0.0.1': 'aa:aa:aa:aa:aa:aa'}
            if argv[0].lower().endswith('arp.exe'):
                return {'10.0.0.1': 'bb:bb:bb:bb:bb:bb', '10.0.0.2': 'cc:cc:cc:cc:cc:cc'}
            return {}

        netscan._run_table = table
        Path.exists = lambda self: True
        merged, source = netscan.neighbour_table()
        self.assertEqual(merged['10.0.0.1'], 'aa:aa:aa:aa:aa:aa')
        self.assertEqual(merged['10.0.0.2'], 'cc:cc:cc:cc:cc:cc')
        self.assertIn('Windows', source)


class ArpParsing(unittest.TestCase):
    def test_linux_ip_neigh(self):
        text = '10.0.0.5 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE\n'
        self.assertEqual(netscan._parse_arp(text), {'10.0.0.5': '00:11:22:33:44:55'})

    def test_linux_arp_dash_a(self):
        text = 'gw (10.0.0.1) at 00:aa:bb:cc:dd:ee [ether] on eth0\n'
        self.assertEqual(netscan._parse_arp(text), {'10.0.0.1': '00:aa:bb:cc:dd:ee'})

    def test_windows_arp_uses_dashes(self):
        """The Windows table separates MAC octets with dashes, not colons."""
        text = '  10.0.0.7           00-11-22-33-44-66     dynamic\n'
        self.assertEqual(netscan._parse_arp(text), {'10.0.0.7': '00:11:22:33:44:66'})

    def test_broadcast_and_multicast_rows_are_not_devices(self):
        text = ('  10.0.0.255  ff-ff-ff-ff-ff-ff  static\n'
                '  224.0.0.22  01-00-5e-00-00-16  static\n'
                '  10.0.0.9    00-11-22-33-44-77  dynamic\n')
        self.assertEqual(netscan._parse_arp(text), {'10.0.0.9': '00:11:22:33:44:77'})

    def test_first_entry_wins_on_a_duplicate_address(self):
        text = ('10.0.0.5 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE\n'
                '10.0.0.5 dev eth1 lladdr 99:99:99:99:99:99 STALE\n')
        self.assertEqual(netscan._parse_arp(text), {'10.0.0.5': '00:11:22:33:44:55'})

    def test_a_line_with_no_mac_is_ignored(self):
        self.assertEqual(netscan._parse_arp('10.0.0.5 dev eth0 INCOMPLETE\n'), {})


class RunTableNeverRaises(unittest.TestCase):
    def test_a_missing_binary_returns_empty(self):
        self.assertEqual(netscan._run_table(['definitely-not-a-real-binary-xyz', '-a']), {})


class CheckPortsGuards(unittest.TestCase):
    def test_the_default_list_is_not_handed_out_by_reference(self):
        """A caller mutating the result must not edit DEFAULT_PORTS for everyone."""
        before = list(netscan.DEFAULT_PORTS)
        got = netscan.check_ports(None)
        got.append(9999)
        self.assertEqual(netscan.DEFAULT_PORTS, before)

    def test_a_bool_is_not_a_port(self):
        """bool is a subclass of int; `type(v) is not int` excludes it. Keep it that way."""
        with self.assertRaises(netscan.Invalid):
            netscan.check_ports([True])


if __name__ == '__main__':
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    failures = len(result.failures) + len(result.errors)
    # A skipped test is not a passed one. result.testsRun counts skips, so the old
    # `testsRun - failures` reported them as passes and a suite that silently ran
    # nothing looked identical to one that ran everything. run_tests.sh:175 already
    # greps for '^SKIP ', so naming them here is what makes them visible in the gate.
    for case, reason in result.skipped:
        print(f'SKIP {case} - {reason}')
    print(f'passed {result.testsRun - failures - len(result.skipped)}, '
          f'failed {failures}')
    sys.exit(bool(failures))
