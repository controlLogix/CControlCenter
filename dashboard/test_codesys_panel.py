#!/usr/bin/env python3
"""Only isolated fixtures: disposable SQLite, fake stdio MCP, stubbed SSH, local HTTP."""
import contextlib
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import ccboard
import ccstore
import codesys_panel as panel

FAKE_MCP = r'''
import json, sys
from pathlib import Path
statefile, logfile = map(Path, sys.argv[1:])
for line in sys.stdin:
    req = json.loads(line)
    if 'id' not in req:
        continue
    state = json.loads(statefile.read_text())
    result = {}
    if req['method'] == 'tools/call':
        params = req['params']
        with logfile.open('a') as log:
            log.write(json.dumps(params) + '\n')
        tool = params['name']
        if tool == state.get('fail'):
            result = {'isError': True, 'content': [{'type': 'text', 'text': 'private-password'}]}
        else:
            text = 'completed'
            if tool == 'execute_script':
                text = 'AGENTMUX_IDENTITY=' + json.dumps(dict(application=state.get('application', 'Application'), gateway_guid='gateway-fixture', device_address=state.get('device_address', '0001'), type=4102, id='0000 0005', simulation=False))
            if tool == 'get_runtime_status':
                text = 'Application State: ' + state.get('state', 'run') + '\nDevices Reachable: True\nDevice Count: 99'
            if tool == 'start_runtime_app': state['state'] = 'run'
            if tool in ('stop_runtime_app', 'reset_runtime_app'): state['state'] = 'stop'
            if tool == 'create_boot_application': state['boot'] = True
            statefile.write_text(json.dumps(state))
            result = {'content': [{'type': 'text', 'text': text}]}
    print(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/message', 'params': {}}), flush=True)
    print(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': result}), flush=True)
'''


class CodesysTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(ccstore, 'HOME_DIR', self.home).start()
        patch.object(ccstore, 'DB_PATH', self.home / 'cc.db').start()
        panel._PENDING.clear()
        panel._SEEN.clear()
        self.fixture = self.home / 'mcp.py'
        self.fixture.write_text(FAKE_MCP)
        self.state = self.home / 'state.json'
        self.state.write_text('{"state":"run"}')
        self.log = self.home / 'calls.jsonl'
        self.config = {'mcp_argv': [sys.executable, str(self.fixture), str(self.state), str(self.log)],
                       'targets': [{'id': 'lab', 'name': 'Lab <IPC>', 'ssh': 'admin@lab',
                                    'machine_id': 'a' * 32, 'project': 'C:/Lab.project',
                                    'application': 'Application', 'gateway_verified': True,
                                    'gateway_guid': 'gateway-fixture', 'device_address': '0001',
                                    'package': {'path': '/home/admin/runtime.deb', 'version': '4.21.0.0', 'sha256': 'b' * 64}}]}
        self.save_config()
        self.ssh_calls = []
        self.ssh_error = False
        self.backup_error = False
        self.install_error = False
        self.info = {'os': 'Linux', 'arch': 'x86_64', 'machine_id': 'a' * 32,
                     'version': '4.18.0.0', 'service': 'active'}
        patch.object(panel, 'ssh', side_effect=self.fake_ssh).start()
        with ccstore.connection():
            pass

    def save_config(self):
        (self.home / 'codesys.json').write_text(json.dumps(self.config))

    def fake_ssh(self, target, script, timeout=15):
        self.ssh_calls.append(script)
        if self.ssh_error:
            raise panel.Unavailable('SSH unreachable')
        if 'tar -czf' in script:
            # Inspect from a separate connection, proving intent was committed.
            with sqlite3.connect(ccstore.DB_PATH) as other:
                record = json.loads(other.execute('SELECT body FROM journal ORDER BY id DESC LIMIT 1').fetchone()[0])
                self.assertEqual(record['outcome'], 'intent')
                self.assertEqual(record['target'], 'lab')
            if self.backup_error:
                raise panel.Unavailable('backup failed')
        if 'apt-get install' in script:
            if self.install_error:
                raise panel.Unavailable('install verification failed')
            self.info['version'] = self.config['targets'][0]['package']['version']
        return '\n'.join(k + '=' + v for k, v in self.info.items()) + '\n'

    def rows(self):
        with ccstore.connection() as db:
            return panel.targets(db, {})['targets']

    def calls(self):
        return [json.loads(s) for s in self.log.read_text().splitlines()] if self.log.exists() else []

    def records(self):
        with ccstore.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM journal ORDER BY id')]

    def body(self, action='start', **kw):
        result = dict(target='lab', actor='operator', action=action, phase='prepare')
        if action == 'reset': result['reset_type'] = 'Cold'
        return {**result, **kw}

    def call(self, body, boot=False):
        with ccstore.connection() as db:
            return (panel.bootapp if boot else panel.plcstate)(db, body)

    def execute(self, action='start', **kw):
        body = self.body(action, **kw)
        pending = self.call(body, action == 'boot')
        body.update(phase='execute', token=pending['token'], confirm=True)
        return self.call(body, action == 'boot')

    def test_empty_inventory_and_invalid_config(self):
        (self.home / 'codesys.json').unlink()
        self.assertEqual(self.rows(), [])
        (self.home / 'codesys.json').write_text('{broken')
        with self.assertRaises(ccboard.Invalid): self.rows()

    def test_live_status_and_version_are_measured(self):
        row = self.rows()[0]
        self.assertTrue(row['reachable'])
        self.assertEqual(row['runtime_version'], '4.18.0.0')
        self.assertEqual(row['application'], 'Application')
        self.assertEqual(row['state'], 'run')
        self.assertIn('reset', row['actions'])
        self.assertEqual(len(self.ssh_calls), 1)
        self.assertFalse(self.records())
        self.state.write_text('{"state":"ApplicationState.exception"}')
        self.assertEqual(self.rows()[0]['state'], 'exception')

    def test_unreachable_discards_all_live_state_keeps_historical_last_seen(self):
        previous = self.rows()[0]
        self.ssh_error = True
        row = self.rows()[0]
        self.assertFalse(row['reachable'])
        self.assertIsNone(row['runtime_version'])
        self.assertIsNone(row['application'])
        self.assertEqual(row['state'], 'unknown')
        self.assertEqual(row['last_seen'], previous['last_seen'])
        self.assertEqual(row['actions'], [])

    def test_gateway_failure_and_aggregate_scan_never_infer_state(self):
        self.state.write_text('{"fail":"get_runtime_status"}')
        row = self.rows()[0]
        self.assertEqual(row['state'], 'unknown')
        self.assertNotIn('start', row['actions'])
        self.assertIn('Set active path', str(row))
        self.assertNotIn('private-password', str(row))
        self.state.write_text('{"state":"garbage"}')
        self.assertEqual(self.rows()[0]['state'], 'unknown')

    def test_identity_platform_and_application_mismatch_disable_controls(self):
        for key, value in [('machine_id', 'wrong'), ('os', 'Windows'), ('arch', 'aarch64')]:
            original = self.info[key]
            self.info[key] = value
            self.assertEqual(self.rows()[0]['actions'], [])
            self.info[key] = original
        self.state.write_text('{"application":"Other"}')
        self.assertNotIn('start', self.rows()[0]['actions'])
        self.assertFalse(self.records())

    def test_unverified_gateway_names_gui_steps(self):
        self.config['targets'][0]['gateway_verified'] = False
        self.save_config()
        row = self.rows()[0]
        self.assertNotIn('start', row['actions'])
        self.assertIn('Communication Settings', str(row))
        self.assertFalse(self.calls())

    def test_prepare_is_read_only_and_reset_confirmation_names_all_fields(self):
        pending = self.call(self.body('reset'))
        for text in ('Lab <IPC>', 'lab', 'admin@lab', 'Cold', 'retains', 'DESTRUCTIVE', 'operator'):
            self.assertIn(text, pending['confirmation'])
        self.assertFalse(self.records())
        self.assertTrue(all(c['name'] in ('get_runtime_status', 'execute_script') for c in self.calls()))
        self.assertFalse(any('tar -czf' in s or 'apt-get install' in s for s in self.ssh_calls))

    def test_each_control_uses_keep_login_and_committed_audit(self):
        for action in ('start', 'stop', 'reset', 'boot'):
            with self.subTest(action=action):
                self.assertTrue(self.execute(action)['ok'])
                records = self.records()[-2:]
                self.assertEqual([r['outcome'] for r in records], ['intent', 'success'])
                self.assertEqual(records[0]['actor'], 'operator')
                self.assertEqual(records[0]['action'], action)
                calls = self.calls()
                self.assertEqual(calls[-2]['name'], 'login_to_runtime')
                self.assertEqual(calls[-2]['arguments']['onlineChangeOption'], 'Keep')
                self.assertIs(calls[-2]['arguments']['startAfterLogin'], False)
                self.assertEqual(calls[-1]['name'], panel.TOOLS[action])
                if action == 'reset':
                    self.assertEqual(calls[-1]['arguments']['resetOption'], 'Cold')
                    self.assertEqual(records[0]['reset_type'], 'Cold')
        self.assertEqual(len(self.ssh_calls), 8)  # one per prepare and execute
        self.assertTrue(json.loads(self.state.read_text())['boot'])

    def test_confirmation_required_no_side_effects(self):
        for body in [self.body(phase='execute'), self.body(phase='execute', confirm='true'),
                     self.body(phase='execute', token='forged', confirm=True)]:
            with self.assertRaises(ccboard.Invalid): self.call(body)
        self.assertFalse(self.ssh_calls)
        self.assertFalse(self.records())

    def test_replay_expiry_and_altered_binding_refused(self):
        body = self.body()
        token = self.call(body)['token']
        execution = {**body, 'phase': 'execute', 'token': token, 'confirm': True}
        self.call(execution)
        with self.assertRaises(ccboard.Invalid): self.call(execution)
        for change in ({'actor': 'other'}, {'action': 'stop'}):
            token = self.call(body)['token']
            with self.assertRaises(ccboard.Invalid): self.call({**execution, 'token': token, **change})
        token = self.call(body)['token']
        panel._PENDING[token]['expires'] = 0
        with self.assertRaises(ccboard.Invalid): self.call({**execution, 'token': token})
        token = self.call(body)['token']
        self.config['targets'][0]['project'] = 'C:/Other.project'
        self.save_config()
        with self.assertRaises(ccboard.Invalid): self.call({**execution, 'token': token})

    def test_backup_failure_prevents_login_and_action_audit_survives_exception(self):
        self.backup_error = True
        with self.assertRaisesRegex(ccboard.Invalid, 'backup failed'): self.execute('reset')
        self.assertFalse(any(c['name'] == 'login_to_runtime' for c in self.calls()))
        self.assertEqual([r['outcome'] for r in self.records()], ['intent', 'failed'])

    def test_journal_failure_prevents_every_write(self):
        body = self.body()
        token = self.call(body)['token']
        with patch.object(panel, 'journal', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.call({**body, 'phase': 'execute', 'token': token, 'confirm': True})
        self.assertFalse(any('tar -czf' in s for s in self.ssh_calls))
        self.assertFalse(any(c['name'] == 'login_to_runtime' for c in self.calls()))

    def test_mcp_error_is_redacted_and_failed_action_is_journalled(self):
        self.state.write_text('{"state":"run", "fail":"start_runtime_app"}')
        with self.assertRaises(ccboard.Invalid) as error: self.execute()
        self.assertNotIn('private-password', str(error.exception))
        self.assertNotIn('private-password', str(self.records()))
        self.assertEqual(self.records()[-1]['outcome'], 'failed')

    def test_install_and_update_verify_package_and_do_not_require_mcp(self):
        for action, version in [('install', 'not installed'), ('update', '4.18.0.0')]:
            self.info['version'] = version
            self.config['mcp_argv'] = []
            self.save_config()
            self.assertTrue(self.execute(action)['ok'])
            script = self.ssh_calls[-1]
            for text in ('Package)', 'Architecture)', 'Version)', 'sha256sum', 'machine-id', 'systemctl is-active --quiet'):
                self.assertIn(text, script)
            self.assertLess(script.index('tar -czf'), script.index('apt-get install'))
            self.assertGreater(script.rindex('dpkg-query'), script.index('apt-get install'))
            self.assertNotIn('purge', script)
            self.assertEqual(self.info['version'], '4.21.0.0')
            self.assertEqual(self.records()[-1]['before_version'], version)

    def test_install_failure_is_not_success(self):
        self.install_error = True
        with self.assertRaises(ccboard.Invalid): self.execute('update')
        self.assertEqual(self.records()[-1]['outcome'], 'failed')

    def test_bad_inputs_never_run_transports(self):
        for body in [self.body(action=[]), self.body(actor=''), self.body('reset', reset_type=[]),
                     self.body('reset', reset_type='Erase'), self.body(host='evil'), self.body(target='other'),
                     self.body(phase='now'), self.body(reset_type='Cold')]:
            with self.assertRaises(ccboard.Invalid): self.call(body)
        self.assertFalse(self.ssh_calls)
        for bad in ['-oProxyCommand=bad', 'admin@host;touch /tmp/bad']:
            self.config['targets'][0]['ssh'] = bad
            self.save_config()
            with self.assertRaises(ccboard.Invalid): self.rows()
        self.assertFalse(self.ssh_calls)

    def test_lock_refuses_concurrent_operations(self):
        with panel._LOCK:
            with self.assertRaisesRegex(ccboard.Invalid, 'in progress'): self.rows()
            with self.assertRaisesRegex(ccboard.Invalid, 'in progress'): self.call(self.body())
        self.assertFalse(self.ssh_calls)

    def test_ssh_uses_one_bounded_noninteractive_connection_and_redacts_errors(self):
        # Stop only the SSH patch for this test; never launch a real SSH process.
        patch.stopall()
        with patch.object(panel.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'private-password')) as run:
            with self.assertRaises(panel.Unavailable) as error: panel.ssh(self.config['targets'][0], 'true')
            self.assertNotIn('private-password', str(error.exception))
            argv = run.call_args.args[0]
            self.assertIn('-oBatchMode=yes', argv)
            self.assertIn('-oStrictHostKeyChecking=yes', argv)
            self.assertEqual(run.call_count, 1)

    def test_stdio_disconnect_and_node_discovery_fail_explicitly(self):
        with self.assertRaisesRegex(panel.Unavailable, 'disconnected'):
            panel.MCP([sys.executable, '-c', 'pass'])
        with patch.object(panel.Path, 'glob', return_value=[]):
            with self.assertRaisesRegex(panel.Unavailable, '^SKIP node unavailable'):
                panel.MCP(['node', '/unused/server.js'])

    def test_http_routes_use_own_database_and_serve_js(self):
        import server
        from http.server import ThreadingHTTPServer
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        conn = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=15)
        self.addCleanup(conn.close)
        def request(method, path, body=None):
            conn.request(method, path, json.dumps(body) if body else None, {'Content-Type': 'application/json'})
            res = conn.getresponse()
            data = res.read()
            return res.status, data
        code, data = request('GET', '/api/board/targets')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)['targets'][0]['state'], 'run')
        body = self.body('boot')
        code, data = request('POST', '/api/board/bootapp', body)
        self.assertEqual(code, 200)
        token = json.loads(data)['token']
        code, _ = request('POST', '/api/board/bootapp', {**body, 'phase': 'execute', 'token': token, 'confirm': True})
        self.assertEqual(code, 200)
        code, _ = request('POST', '/api/board/plcstate', self.body(phase='execute'))
        self.assertEqual(code, 400)
        code, data = request('GET', '/codesys.js')
        self.assertEqual(code, 200)
        # CODESYS moved from a top-level view to a card on IIOT, where the rest of the
        # field equipment lives. This assertion still pinned the old registration and
        # so had been failing since that move. What it is actually here to protect is
        # that the panel registers itself at all and never builds DOM from a string.
        self.assertIn(b"registerCard('iiot', maybe, 0)", data)
        # And that it stays LAZY: every refresh is an SSH connection to a controller,
        # so a poll interval here would reach out to every PLC just because someone
        # opened IIOT to look at Modbus.
        self.assertIn(b"if (!card.open || loaded) return;", data)
        self.assertNotIn(b'innerHTML', data)

    def test_runtime_service_down_and_gateway_retarget_clear_state(self):
        self.info['service'] = 'inactive'
        row = self.rows()[0]
        self.assertEqual(row['state'], 'unknown')
        self.assertNotIn('start', row['actions'])
        self.info['service'] = 'active'
        self.state.write_text('{"device_address":"other-controller"}')
        self.assertNotIn('start', self.rows()[0]['actions'])

    def test_generated_install_script_aborts_before_mutation_on_changed_facts(self):
        captured = []
        with patch.object(panel, 'ssh', side_effect=lambda t, s, **kw: captured.append(s)):
            panel.perform(self.config, self.config['targets'][0], 'update', None, 'fixture', '4.18.0.0')
        script = captured[0]
        # Run the real generated shell control flow, replacing equipment tools
        # with shell functions. No sudo, SSH, package manager or /var write runs.
        harness = r'''
uname() { if test "$1" = -s; then echo Linux; else echo x86_64; fi; }
cat() { printf '%s\n' "$SIM_MACHINE"; }
dpkg-query() {
 case "$*" in
  *Status*) printf 'install ok installed';;
  *) printf '%s' "$SIM_VERSION";;
 esac
}
dpkg-deb() {
 case "$3" in
  Package) echo codesyscontrol;;
  Architecture) echo amd64;;
  Version) echo 4.21.0.0;;
 esac
}
sha256sum() { printf '%s  package\n' "$SIM_SHA"; }
systemctl() { echo active; }
sudo() {
 if test "$2" = sh; then
   echo backup >> "$SIM_LOG"
   test "$SIM_BACKUP_FAIL" != yes || return 1
 fi
 if test "$2" = env; then
   echo install >> "$SIM_LOG"
   SIM_VERSION="$SIM_AFTER_VERSION"
 fi
}
'''
        defaults = {'SIM_MACHINE': 'a' * 32, 'SIM_VERSION': '4.18.0.0', 'SIM_SHA': 'b' * 64,
                    'SIM_BACKUP_FAIL': 'no', 'SIM_AFTER_VERSION': '4.21.0.0', 'SIM_LOG': str(self.home / 'shell.log')}
        cases = [({}, ['backup', 'install'], True),
                 ({'SIM_MACHINE': 'wrong'}, [], False),
                 ({'SIM_VERSION': '4.19.0.0'}, [], False),
                 ({'SIM_SHA': 'wrong'}, [], False),
                 ({'SIM_BACKUP_FAIL': 'yes'}, ['backup'], False),
                 ({'SIM_AFTER_VERSION': 'wrong'}, ['backup', 'install'], False)]
        for changed, effects, success in cases:
            with self.subTest(changed=changed):
                log = self.home / 'shell.log'
                log.write_text('')
                proc = subprocess.run(['sh', '-s'], input=(harness + script).replace('dpkg-query', 'dpkg_query').replace('dpkg-deb', 'dpkg_deb'), text=True, capture_output=True,
                                      env={**os.environ, **defaults, **changed}, timeout=10)
                self.assertEqual(proc.returncode == 0, success, proc.stderr)
                self.assertEqual(log.read_text().splitlines(), effects)

    def test_backup_archive_is_private_and_contains_runtime_data(self):
        import tarfile
        data = self.home / 'runtime'
        data.mkdir()
        (data / 'retain.fixture').write_text('fixture')
        backup = self.home / 'backups'
        script = panel.backup_script('test')
        script = script.replace('/var/backups/agentmux-codesys', str(backup))
        script = script.replace('var/opt/codesys etc/codesyscontrol', str(data).lstrip('/'))
        # Strip the sudo wrapper but run the original install/tar command.
        harness = 'sudo() { shift; "$@"; }\n'
        subprocess.run(['sh', '-s'], input=harness + script, text=True, check=True, timeout=10)
        archive = backup / 'test.tgz'
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        with tarfile.open(archive) as tar:
            self.assertTrue(any(n.endswith('retain.fixture') for n in tar.getnames()))
        self.assertNotIn('ignore-failed-read', script)

    def test_frontend_confirm_cancel_unreachable_and_errors(self):
        try:
            node = panel.node_binary()
        except panel.Unavailable as exc:
            print(str(exc), flush=True)
            self.skipTest(str(exc))
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
class El {
 constructor(tag, cls, text) { this.tag=tag; this.text=text || ''; this.children=[]; this.events={}; }
 appendChild(n) {this.children.push(n); return n;}
 replaceChildren(...n) {this.children=n;}
 addEventListener(k, f) {this.events[k]=f;}
 setAttribute() {}
}
const root = new El('section'); let loader, approve=false, confirms=[], posts=[];
let row = {id:'lab', name:'<img src=x>', address:'admin@lab', reachable:true, state:'run', runtime_version:'4.18', application:'App', actions:['start','reset','boot'], errors:[]};
let offline=false;
const shellCard = new El('details'); shellCard.open=false;
global.document={getElementById:id=>{assert.equal(id,'viewCodesys');return root;}, querySelector:selector=>{assert.equal(selector,'details[data-collapse-key="iiot:codesys"]');return shellCard;}};
global.window={confirm:t=>{confirms.push(t); return approve;}, addEventListener:(k,f)=>f(), CCC:{
 el:(...a)=>new El(...a), registerCard:(k,f,poll)=>{assert.equal(k,'iiot');assert.equal(poll,0);loader=async()=>{if(!shellCard.open){shellCard.open=true;f();await new Promise(setImmediate);}else await root.children.find(n=>n.tag==='button'&&n.text==='Refresh targets').events.click();};},
 getJSON:async p=>{assert.equal(p,'/api/board/targets'); if(offline) throw Error('offline'); return {targets:[row]};},
 post:async(p,b)=>{posts.push({p,b}); return b.phase==='prepare'?{token:'abc',confirmation:'RESET lab Cold destructive'}:{ok:true,message:'done'};}
}};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const all=n=>[n,...n.children.flatMap(all)];
const button=t=>all(root).find(n=>n.tag==='button' && n.text===t);
(async()=>{
 await loader();
 let input=all(root).find(n=>n.tag==='input'); input.value='operator'; input.events.input();
 all(root).find(n=>n.tag==='select').value='Cold';
 await button('Reset').events.click();
 assert.equal(posts.length,1); assert.equal(posts[0].b.reset_type,'Cold');
 assert.equal(confirms.length,1); assert(!posts.some(p=>p.b.phase==='execute'));
 await loader(); approve=true;
 await button('Create boot application').events.click();
 assert.equal(posts.at(-1).p,'/api/board/bootapp'); assert.equal(posts.at(-1).b.confirm,true);
 assert.equal(posts.at(-1).b.token,'abc');
 row={...row,reachable:false}; await loader();
 assert(button('Start').disabled);
 const text=all(root).map(n=>n.text).join(' ');
 assert(text.includes('UNREACHABLE')); assert(!text.includes('State: run')); assert(!text.includes('Runtime: 4.18'));
 assert(text.includes('/var/opt/codesys')); assert(text.includes('survives'));
 offline=true; await loader(); assert(all(root).some(n=>n.text.includes('offline')));
 assert(!button('Start'));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        subprocess.run([node, '-e', script, str(Path(__file__).with_name('codesys.js'))], check=True, timeout=15)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CodesysTests))
    failures = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failures - len(result.skipped)}, failed {failures}', flush=True)
    raise SystemExit(bool(failures))
