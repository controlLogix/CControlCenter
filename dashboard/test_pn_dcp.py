#!/usr/bin/env python3
"""TM-076 isolated wire fixtures, safety gates, journal and IIOT import tests.
No raw socket is opened and no real device is contacted.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pn_dcp', ROOT / 'taskmgmt/pn_dcp.py')
dcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dcp)
LOCAL = '02:00:00:00:00:01'
TARGET = '00:11:22:33:44:55'
# Independent byte fixture: text blocks include BlockInfo; odd names are padded.
IDENTITY = bytes.fromhex(
    '020200050000706c6300'       # name plc
    '0102000e0001c0a8010affffff00c0a80101'
    '02010006000041434d45'       # vendor ACME
    '020300060000002a1234')


def reply(service, xid, payload, src=TARGET, dst=LOCAL, response=1, fid=None):
    if fid is None:
        fid = 0xfeff if service == 5 else 0xfefd
    return (bytes.fromhex(dst.replace(':', '') + src.replace(':', '') + '8892')
            + struct.pack('!HBBIHH', fid, service, response, xid, 0, len(payload)) + payload).ljust(60, b'\0')


class Wire:
    def __init__(self):
        self.sent, self.queue = [], []
        self.mode = 'ok'
        self.before_write = lambda: None
        self.closed = False

    def send(self, data):
        self.sent.append(data)
        service, xid = data[16], struct.unpack_from('!I', data, 18)[0]
        if service == 5:
            self.queue.extend([reply(5, xid + 1, IDENTITY), reply(5, xid, IDENTITY, dst=TARGET),
                               reply(5, xid, IDENTITY), reply(5, xid, IDENTITY)])
        elif service == 3:
            if self.mode == 'read_timeout':
                return len(data)
            key = data[26:28]
            payload = IDENTITY[:10] if key == b'\x02\x02' else IDENTITY[10:28]
            self.queue.append(reply(3, xid, payload))
        elif service == 4:
            self.before_write()
            if self.mode == 'timeout':
                return len(data)
            error = 6 if self.mode == 'reject' else 0
            payload = b'\x05\x04\x00\x03' + data[26:28] + bytes([error, 0])
            if self.mode == 'bad_ack':
                payload = b'\x05\x04\x00\x03\x01\x02\x00\x00'
            if self.mode == 'wrong_source':
                self.queue.append(reply(4, xid, payload, src='00:11:22:33:44:66'))
            else:
                self.queue.append(reply(4, xid, payload))
        return len(data)

    def recv(self, size):
        if not self.queue:
            raise socket.timeout()
        return self.queue.pop(0)

    def settimeout(self, value):
        pass

    def close(self):
        self.closed = True


def client(wire):
    c = dcp.Client.__new__(dcp.Client)
    c.sock, c.mac, c.iface, c.timeout = wire, LOCAL, 'test0', .01
    return c


class ProtocolTests(unittest.TestCase):
    def test_identify_and_identity_fields(self):
        w = Wire()
        records = list(client(w).identify())
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual([r[k] for k in ('mac', 'name', 'ip', 'subnet', 'gateway', 'vendor', 'vendor_id', 'device_id')],
                         [TARGET, 'plc', '192.168.1.10', '255.255.255.0', '192.168.1.1', 'ACME', 42, 0x1234])
        packet = w.sent[0]
        self.assertEqual(packet[:6], bytes.fromhex('010ecf000000'))
        self.assertEqual(packet[12:18], bytes.fromhex('8892fefe0500'))
        self.assertEqual(packet[24:30], bytes.fromhex('0004ffff0000'))
        self.assertEqual(len(packet), 60)

    def test_truncated_wrong_ethertype_and_duplicate_blocks(self):
        packet = reply(5, 1, IDENTITY)
        for length in range(26 + len(IDENTITY)):
            self.assertIsNone(dcp.parse_frame(packet[:length]), length)
        self.assertIsNone(dcp.parse_frame(packet[:12] + b'\x08\x00' + packet[14:]))
        self.assertIsNone(dcp.parse_frame(reply(5, 1, IDENTITY + IDENTITY[:10])))
        self.assertIsNone(dcp.parse_frame(reply(5, 1, b'\x02\x02\x00\x05\0\0plc')))

    def test_vlan_and_unknown_block(self):
        packet = reply(5, 1, IDENTITY + bytes.fromhex('7f010002abcd'))
        tagged = packet[:12] + bytes.fromhex('810000648892') + packet[14:]
        self.assertEqual(dcp.station(dcp.parse_frame(tagged))['name'], 'plc')

    def test_get_is_unicast_selector(self):
        w = Wire()
        self.assertEqual(client(w).read(TARGET, dcp.NAME), {'name': 'plc'})
        self.assertEqual(w.sent[0][:6], dcp.mac_bytes(TARGET))
        self.assertEqual(w.sent[0][24:28], bytes.fromhex('00020202'))

    def test_invalid_targets_and_settings(self):
        for mac in ('', 'all', 'ff:ff:ff:ff:ff:ff', '01:0e:cf:00:00:00', '00:00:00:00:00:00', TARGET + ',aa'):
            with self.subTest(mac=mac), self.assertRaises(ValueError):
                dcp.target_mac(mac)
        for name in ('', 'A', '-plc', 'plc-', 'a..b', '1.2.3.4', 'port-001', 'a' * 64, 'é', 'a.' * 121):
            with self.subTest(name=name), self.assertRaises(ValueError):
                dcp.setting(name=name)
        for args in ({}, {'name': 'plc', 'ip': '1.2.3.4'}, {'ip': '1.2.3.4'},
                     {'ip': '192.168.1.0', 'subnet': '255.255.255.0', 'gateway': '0.0.0.0'},
                     {'ip': '192.168.1.2', 'subnet': '255.0.255.0', 'gateway': '0.0.0.0'},
                     {'ip': '192.168.1.2', 'subnet': '255.255.255.0', 'gateway': '192.168.2.1'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                dcp.setting(**args)

    def test_name_and_ip_wire(self):
        w = Wire()
        c = client(w)
        key, _, raw = dcp.setting(name='new')
        c.write(TARGET, key, raw)
        self.assertEqual(w.sent[0][24:36], bytes.fromhex('000a0202000500016e657700'))
        key, _, raw = dcp.setting(ip='192.168.1.20', subnet='255.255.255.0', gateway='0.0.0.0')
        c.write(TARGET, key, raw)
        self.assertEqual(w.sent[1][24:44], bytes.fromhex('00120102000e0001c0a80114ffffff0000000000'))
        self.assertTrue(all(p[:6] == dcp.mac_bytes(TARGET) for p in w.sent))

    def test_transport_refuses_multicast_and_control_writes(self):
        w = Wire()
        for mac, key in ((dcp.MULTICAST, dcp.NAME), ('ff:ff:ff:ff:ff:ff', dcp.IP), (TARGET, (5, 6))):
            with self.assertRaises(ValueError):
                client(w).write(mac, key, b'')
        self.assertFalse(w.sent)

    def test_privilege_failure_and_validation_before_socket(self):
        with patch.object(dcp.socket, 'socket', side_effect=PermissionError('denied')) as create, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(dcp.main(['--iface', 'eth0', 'identify']), 1)
            self.assertIn('sudo/CAP_NET_RAW', err.getvalue())
            create.reset_mock()
            self.assertEqual(dcp.main(['--iface', 'eth0', 'set', '--mac', 'all', '--name', 'plc']), 1)
            create.assert_not_called()

    def test_missing_mac_reset_and_batch_refused_by_cli(self):
        for tail in (['set', '--name', 'plc'], ['reset'], ['set', '--mac', TARGET, '--name', 'plc', '--yes']):
            with patch.object(dcp.socket, 'socket') as create, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                dcp.main(['--iface', 'eth0'] + tail)
            create.assert_not_called()

    def test_timeout_and_non_ethernet_interface_validation(self):
        for value in (0, -1, float('nan'), float('inf'), 61):
            with patch.object(dcp.socket, 'socket') as create, self.assertRaises(ValueError):
                dcp.Client('eth0', value)
            create.assert_not_called()
        with patch.object(dcp.socket, 'socket') as create:
            create.return_value.getsockname.return_value = ('lo', 0, 0, 772, bytes(6))
            with self.assertRaises(dcp.DCPError):
                dcp.Client('lo')
            create.return_value.close.assert_called_once()


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'writes.jsonl'
        self.wire = Wire()
        self.c = client(self.wire)
        self.change = dcp.setting(name='new')
        self.stderr = contextlib.redirect_stderr(io.StringIO())
        self.stderr.__enter__()
        self.addCleanup(self.stderr.__exit__, None, None, None)

    def run_set(self, confirm=lambda mac: True):
        return dcp.perform_set(self.c, TARGET, self.change, self.path, confirm)

    def rows(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def writes(self):
        return [p for p in self.wire.sent if p[16] == 4]

    def test_journal_precedes_write_and_records_old_new(self):
        self.wire.before_write = lambda: self.assertEqual(self.rows()[-1]['outcome'], 'intent')
        result = self.run_set()
        self.assertEqual(result['outcome'], 'acknowledged')
        rows = self.rows()
        self.assertEqual([r['outcome'] for r in rows], ['intent', 'acknowledged'])
        self.assertEqual(rows[0]['old'], {'name': 'plc'})
        self.assertEqual(rows[0]['new'], {'name': 'new'})
        self.assertEqual(rows[0]['mac'], TARGET)
        self.assertEqual(rows[0]['operation_id'], rows[1]['operation_id'])
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_cancel_and_no_current_value_prevent_write(self):
        with self.assertRaises(dcp.DCPError):
            self.run_set(lambda mac: False)
        self.assertFalse(self.writes())
        self.assertFalse(self.path.exists())
        self.wire.mode = 'read_timeout'
        with self.assertRaises(dcp.DCPError):
            self.run_set()
        self.assertFalse(self.writes())

    def test_changed_current_value_prevents_write(self):
        with patch.object(self.c, 'read', side_effect=[{'name': 'plc'}, {'name': 'changed'}]), self.assertRaises(dcp.DCPError):
            self.run_set()
        self.assertFalse(self.writes())

    def test_journal_error_and_fsync_failure_prevent_write(self):
        with patch.object(dcp, 'journal', side_effect=OSError('disk full')), self.assertRaises(OSError):
            self.run_set()
        self.assertFalse(self.writes())
        with patch.object(dcp.os, 'fsync', side_effect=OSError('disk error')), self.assertRaises(OSError):
            self.run_set()
        self.assertFalse(self.writes())

    def test_symlink_and_fifo_journal_refused(self):
        other = Path(self.temp.name) / 'other'
        other.write_text('unchanged')
        self.path.symlink_to(other)
        with self.assertRaises(OSError):
            self.run_set()
        self.assertEqual(other.read_text(), 'unchanged')
        self.path.unlink()
        os.mkfifo(self.path)
        with self.assertRaises(OSError):
            self.run_set()
        self.assertFalse(self.writes())

    def test_rejection_timeout_wrong_source_bad_ack_journalled_no_retry(self):
        for mode, outcome in [('reject', 'rejected'), ('timeout', 'unknown'), ('wrong_source', 'unknown'), ('bad_ack', 'unknown')]:
            with self.subTest(mode=mode):
                self.path.unlink(missing_ok=True)
                self.wire.mode = mode
                self.wire.sent.clear()
                with self.assertRaises(dcp.DCPError):
                    self.run_set()
                self.assertEqual(self.rows()[-1]['outcome'], outcome)
                self.assertEqual(len(self.writes()), 1)

    def test_keyboard_interrupt_records_unknown(self):
        with patch.object(self.c, 'write', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.run_set()
        self.assertEqual(self.rows()[-1]['outcome'], 'unknown')

    def test_ip_old_and_new_are_journalled(self):
        self.change = dcp.setting(ip='192.168.1.20', subnet='255.255.255.0', gateway='0.0.0.0')
        self.run_set()
        self.assertEqual(self.rows()[0]['old']['ip'], '192.168.1.10')
        self.assertEqual(self.rows()[0]['new']['ip'], '192.168.1.20')

    def test_exact_mac_confirmation_on_tty(self):
        for answer, expected in ((TARGET, True), ('yes', False), ('', False)):
            class TTY(io.StringIO):
                def readline(self):
                    return answer + '\n'
            with patch('builtins.open', return_value=TTY()) as opened:
                self.assertEqual(dcp.confirm(TARGET), expected)
            opened.assert_called_once_with('/dev/tty', 'r+')

    def test_no_arbitrary_control_blocks(self):
        self.change = ((5, 6), {'name': 'new'}, b'\0\0')
        with self.assertRaises(ValueError):
            self.run_set()
        self.assertFalse(self.wire.sent)


class DashboardTests(unittest.TestCase):
    def test_runner_registration_and_existing_script_hook(self):
        self.assertIn('run test_pn_dcp.py python3 dashboard/test_pn_dcp.py', (ROOT / 'dashboard/run_tests.sh').read_text())
        self.assertIn('src="iiot.js"', (ROOT / 'dashboard/index.html').read_text())

    def test_panel_import_in_dom(self):
        candidates = sorted(Path('/c/Users/Nick/.nvm/versions/node').glob('*/bin/node'))
        if not candidates:
            print('SKIP DCP browser import: node absent under /c/Users/Nick/.nvm/versions/node/*/bin')
            self.skipTest('required node location unavailable')
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const all = []; let loader, posts=[];
class Element {
  constructor(tag, cls='', text='') {this.tag=tag;this.children=[];this.dataset={};this.style={};this.handlers={};this.textContent=text;this.value='';all.push(this);}
  appendChild(e) {this.children.push(e);return e;}
  append(...nodes) {this.children.push(...nodes);}
  setAttribute() {}
  replaceChildren(...nodes) {this.children=nodes;}
  addEventListener(k,fn) {this.handlers[k]=fn;}
}
const root=new Element('div');
let state={schema:{stations:[]},snapshot:[],reconciliation:{counts:{match:0,mismatch:0,missing:0,unexpected:0},rows:[]}};
const document={getElementById:id=>id==='profinetPanel'?root:null,activeElement:null};
const window={addEventListener:(name,fn)=>{assert.equal(name,'agentmux:ready');fn();},AGENTMUX:{
 el:(...args)=>new Element(...args),registerCard:(view,fn,poll)=>{assert.equal(view,'iiot');assert.equal(poll,0);loader=fn;},
 getJSON:async path=>{assert.equal(path,'api/profinet');return state;},
 post:async(path,body)=>{assert.equal(path,'api/profinet/snapshot');posts.push(body);const record=body.records[0];
   if(record.kind!=='dcp-identify')throw Error('Identify records required');
   state={...state,snapshot:[record],reconciliation:{counts:{match:0,mismatch:0,missing:0,unexpected:1},rows:[{status:'unexpected',mac:record.mac,actual:{...record,vendor:String(record.vendor_id)},differences:[]}]}};return state;}
}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{document,window});
(async()=>{
 await loader();
 assert(all.some(e=>e.textContent.includes('sudo python3 taskmgmt/pn_dcp.py')));
 const input=all.find(e=>e.placeholder==='Paste the JSON lines from dcp.jsonl'),button=all.find(e=>e.textContent==='Import snapshot'),body=all.find(e=>e.tag==='tbody');
 input.value=JSON.stringify({kind:'dcp-identify',mac:'00:11:22:33:44:55',name:'<img src=x onerror=alert(1)>',vendor_id:0});
 await button.handlers.click();
 assert.equal(posts.length,1);assert.equal(posts[0].records[0].vendor_id,0);
 assert.equal(body.children.length,1);assert.equal(body.children[0].children[2].textContent,'<img src=x onerror=alert(1)>');
 assert.equal(body.children[0].children[6].textContent,'0');assert.equal(body.children[0].children[2].children.length,0);
 input.value='{invalid';await button.handlers.click();assert.equal(posts.length,1);
 assert(all.some(e=>e.textContent.startsWith('Import failed:')));assert.equal(body.children.length,1);
 input.value=JSON.stringify({kind:'dcp-set',mac:'00:11:22:33:44:55'});await button.handlers.click();
 assert.equal(posts.length,2);assert.equal(body.children.length,1);
 assert.equal(body.children[0].children[2].textContent,'<img src=x onerror=alert(1)>');
 console.log('DCP DOM import checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run([str(candidates[-1]), '-e', script, str(ROOT / 'dashboard/iiot.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    sys.exit(0 if result.wasSuccessful() else 1)
