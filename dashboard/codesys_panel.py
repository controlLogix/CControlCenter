"""CODESYS board ops. Operator-owned AGENTMUX_HOME/codesys.json inventory.

Example (no passwords in this file):
{"mcp_argv": ["node", "/path/to/CodesysRTMCP/build/bin.js"], "targets": [
 {"id": "lab", "name": "Lab IPC", "ssh": "admin@lab", "machine_id": "32 hex digits",
  "project": "C:/Projects/Lab.project", "application": "Application",
  "gateway_verified": true, "gateway_guid": "gateway GUID from IDE",
  "device_address": "CODESYS address from IDE",
  "package": {"path": "/home/admin/codesyscontrol_4.21.0.0_amd64.deb",
              "version": "4.21.0.0", "sha256": "64 hex digits"}}]}

The configured project must have its active application and GUI gateway path bound
by the operator to this exact SSH target. machine_id pins SSH identity in addition
to normal host-key checking. MCP credentials are inherited from the server process.
No request may supply a command, project path, host, or package. Package files must
be staged on the target; installation is sudo -n apt-get install of that exact file.
Local node launches resolve ONLY from /c/Users/Nick/.nvm/versions/node/*/bin.
"""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shlex
import signal
import subprocess
import threading
import time

import ccboard
import ccstore

WARNING = ('apt purge does NOT clear the runtime password. Device user management '
           'under /var/opt/codesys survives package removal and reinstall. '
           'Password recovery is a separate, backed-up operation in a real terminal.')
GATEWAY = ('In the CODESYS IDE: Device > Communication Settings > Add new gateway '
           '(target IP, port 1217) > Scan network > select the Linux SL device > '
           'Set active path. Verify the active application and target before setting '
           'gateway_verified in codesys.json. The MCP cannot configure the gateway.')
RESET = {'Warm': 'reinitializes non-retain variables',
         'Cold': 'reinitializes variables including retains',
         'Origin': 'removes the application and its retained data'}
TOOLS = {'start': 'start_runtime_app', 'stop': 'stop_runtime_app',
         'reset': 'reset_runtime_app', 'boot': 'create_boot_application'}
_LOCK = threading.Lock()
_PENDING = {}
_SEEN = {}


class Unavailable(Exception):
    """Safe operator-facing failure; never include transport stderr or credentials."""


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def inventory():
    path = ccstore.HOME_DIR / 'codesys.json'
    if not path.exists():
        return {'targets': [], 'mcp_argv': []}
    try:
        data = json.loads(path.read_text())
        rows = data['targets']
        if not isinstance(rows, list) or len(rows) > 8:
            raise ValueError
        ids = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError
            for key in ('id', 'name', 'ssh'):
                if not isinstance(row.get(key), str) or not 1 <= len(row[key]) <= 120:
                    raise ValueError
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', row['id']) or row['id'] in ids:
                raise ValueError
            ids.add(row['id'])
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*', row['ssh']):
                raise ValueError
            for key in ('project', 'application', 'machine_id', 'gateway_guid', 'device_address'):
                if key in row and (not isinstance(row[key], str) or len(row[key]) > 500):
                    raise ValueError
            if 'gateway_verified' in row and type(row['gateway_verified']) is not bool:
                raise ValueError
            pkg = row.get('package')
            if pkg is not None:
                if not isinstance(pkg, dict) or not re.fullmatch(r'/[A-Za-z0-9_./+-]+\.deb', pkg.get('path', '')):
                    raise ValueError
                if not re.fullmatch(r'[A-Za-z0-9.+:~_-]{1,80}', pkg.get('version', '')):
                    raise ValueError
                if not re.fullmatch(r'[a-f0-9]{64}', pkg.get('sha256', '')):
                    raise ValueError
        argv = data.get('mcp_argv', [])
        if not isinstance(argv, list) or len(argv) > 30 or any(not isinstance(s, str) or not s or '\0' in s for s in argv):
            raise ValueError
        return data
    except (OSError, ValueError, KeyError, TypeError):
        raise ccboard.Invalid('Invalid codesys.json; see the inventory example in dashboard/codesys_panel.py.') from None


def node_binary():
    candidates = [p for p in Path('/c/Users/Nick/.nvm/versions/node').glob('*/bin/node')
                  if p.is_file() and os.access(p, os.X_OK)]
    if not candidates:
        raise Unavailable('SKIP node unavailable under /c/Users/Nick/.nvm/versions/node/*/bin; CODESYS MCP disabled.')
    return str(max(candidates, key=lambda p: tuple(int(n) for n in re.findall(r'\d+', p.parts[-3]))))


class MCP:
    """Bounded newline JSON-RPC stdio client; one session for login + operation.

    stderr is discarded: upstream diagnostics can contain runtime credentials.
    No automatic retries of writes, and only the fixed tool set below is exposed.
    """
    def __init__(self, argv):
        if not argv:
            raise Unavailable('Configure mcp_argv in codesys.json and inherited CODESYS_RUNTIME_USER/PASS; reconnect after credential changes.')
        argv = list(argv)
        if argv[0].replace('\\', '/').rsplit('/', 1)[-1].lower() in ('node', 'node.exe'):
            argv[0] = node_binary()
        try:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            raise Unavailable('CODESYS MCP process could not start; check mcp_argv.') from None
        self.seq, self.buffer = 0, b''
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        try:
            self.rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                   'clientInfo': {'name': 'agentmux-codesys', 'version': '1'}})
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except Exception:
            self.close()
            raise

    def send(self, data):
        try:
            self.proc.stdin.write((json.dumps(data) + '\n').encode())
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise Unavailable('CODESYS MCP disconnected; action outcome may be unknown. Refresh before retrying.') from None

    def rpc(self, method, params):
        self.seq += 1
        self.send({'jsonrpc': '2.0', 'id': self.seq, 'method': method, 'params': params})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if b'\n' not in self.buffer:
                if not self.selector.select(max(0, deadline - time.monotonic())):
                    break
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    raise Unavailable('CODESYS MCP disconnected; refresh state before retrying.')
                self.buffer += chunk
                if len(self.buffer) > 1024 * 1024:
                    raise Unavailable('CODESYS MCP response exceeded limit.')
                continue
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                row = json.loads(line)
            except ValueError:
                raise Unavailable('Invalid CODESYS MCP response.') from None
            if not isinstance(row, dict):
                raise Unavailable('Invalid CODESYS MCP response.')
            if row.get('id') != self.seq:
                # Notifications are harmless; server requests are not implemented.
                if 'id' in row and 'method' in row:
                    self.send({'jsonrpc': '2.0', 'id': row['id'], 'error': {'code': -32601, 'message': 'Not supported'}})
                continue
            if 'error' in row:
                raise Unavailable('CODESYS MCP rejected the request; check gateway and runtime credentials.')
            result = row.get('result')
            if not isinstance(result, dict):
                raise Unavailable('Invalid CODESYS MCP result.')
            return result
        raise Unavailable('CODESYS MCP timed out; outcome unknown. Refresh before retrying; no automatic retry was made.')

    def call(self, tool, args):
        if tool not in set(TOOLS.values()) | {'get_runtime_status', 'login_to_runtime', 'execute_script'}:
            raise Unavailable('Unsupported CODESYS tool.')
        result = self.rpc('tools/call', {'name': tool, 'arguments': args})
        if result.get('isError'):
            raise Unavailable('CODESYS MCP refused ' + tool + '. Check runtime credentials and gateway. ' + GATEWAY)
        content = result.get('content', [])
        if not isinstance(content, list):
            raise Unavailable('Invalid CODESYS MCP content.')
        return '\n'.join(c['text'] for c in content if isinstance(c, dict) and isinstance(c.get('text'), str))

    def close(self):
        self.selector.close()
        # Only our own process group; never kill another IDE/MCP session.
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()
        except ProcessLookupError:
            self.proc.wait()
        for stream in (self.proc.stdin, self.proc.stdout):
            stream.close()


@contextmanager
def mcp_session(config):
    client = MCP(config.get('mcp_argv', []))
    try:
        yield client
    finally:
        client.close()


def ssh(target, script, timeout=15):
    try:
        proc = subprocess.run(['ssh', '-oBatchMode=yes', '-oConnectTimeout=5',
                               '-oStrictHostKeyChecking=yes', '-oConnectionAttempts=1',
                               '--', target['ssh'], 'sh -s'], input=script, text=True,
                              capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise Unavailable('SSH unavailable or timed out; no retry. Check the target/host key in a terminal.') from None
    if proc.returncode:
        raise Unavailable('SSH operation failed; no retry. Check the target, sudo -n permissions, and staged package in a terminal. Outcome may be unknown.')
    if len(proc.stdout) > 65536:
        raise Unavailable('SSH response exceeded limit.')
    return proc.stdout


PROBE = r'''set -eu
printf 'os=%s\narch=%s\nmachine_id=%s\n' "$(uname -s)" "$(uname -m)" "$(cat /etc/machine-id)"
if dpkg-query -W -f='${Status}' codesyscontrol 2>/dev/null | grep -qx 'install ok installed'; then
  runtime_version=$(dpkg-query -W -f='${Version}' codesyscontrol)
else
  runtime_version='not installed'
fi
printf 'version=%s\n' "$runtime_version"
printf 'service='
systemctl is-active codesyscontrol 2>/dev/null || true
'''


def probe(target, package_check=False):
    script = PROBE + (package_script(target) if package_check else "")
    fields = dict(line.split('=', 1) for line in ssh(target, script).splitlines() if '=' in line)
    if not all(fields.get(key) for key in ('os', 'arch', 'machine_id', 'version')):
        raise Unavailable('Target returned incomplete Linux/runtime identity.')
    return fields


def binding(target):
    return bool(target.get('project') and target.get('application') and target.get('gateway_guid')
                and target.get('device_address') and target.get('gateway_verified') is True)


# Read-only API reference:
# https://content.helpme-codesys.com/en/ScriptingEngine/ScriptDeviceObject.html
# Do not modify gateway settings from this panel. Missing getters fail closed.
IDENTITY_SCRIPT = """import json
app = project.active_application
device = app
while device is not None and not getattr(device, 'is_device', False):
    device = device.get_parent()
ident = device.get_device_identification()
print('AGENTMUX_IDENTITY=' + json.dumps({'application': app.get_name(),
    'gateway_guid': str(device.get_gateway()), 'device_address': device.get_address(),
    'type': ident.type, 'id': ident.id, 'simulation': device.get_simulation_mode()}))
"""


def runtime_state(client, target):
    args = {'projectFilePath': target['project']}
    text = client.call('execute_script', {**args, 'script': IDENTITY_SCRIPT,
                                       'description': 'Read active application and gateway target identity'})
    identities = re.findall(r'^AGENTMUX_IDENTITY=(.+)$', text, re.M)
    try:
        identity = json.loads(identities[0]) if len(identities) == 1 else None
        valid = (isinstance(identity, dict) and
                 all(identity.get(k) == target[k] for k in ('application', 'gateway_guid', 'device_address')) and
                 identity.get('type') == 4102 and identity.get('id') == '0000 0005' and
                 identity.get('simulation') is False)
    except (ValueError, KeyError):
        valid = False
    if not valid:
        raise Unavailable('Active application, Linux SL device, or gateway address does not match the configured target binding. ' + GATEWAY)
    text = client.call('get_runtime_status', args)
    match = re.search(r'^Application State:\s*(\S+)\s*$', text, re.M)
    state = match.group(1).lower().rsplit('.', 1)[-1] if match else 'unknown'
    # Never infer target reachability from the MCP's aggregate gateway device count.
    state = {'run': 'run', 'stop': 'stop', 'exception': 'exception'}.get(state, 'unknown')
    return state


def snapshot(config, target, package_check=False):
    identity = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()
    row = {'id': target['id'], 'name': target['name'], 'address': target['ssh'],
           'reachable': False, 'runtime_version': None, 'application': None,
           'state': 'unknown', 'last_seen': _SEEN.get(identity), 'checked_at': stamp(),
           'errors': [], 'actions': [], 'package_version': (target.get('package') or {}).get('version')}
    try:
        info = probe(target, package_check)
        row.update(reachable=True, last_seen=stamp(), runtime_version=info['version'], service=info.get('service', 'unknown'))
        _SEEN[identity] = row['last_seen']
        if info['os'] != 'Linux' or info['arch'] != 'x86_64':
            raise Unavailable('Only CODESYS Control for Linux SL on x86-64 is supported.')
        if info['machine_id'] != target.get('machine_id'):
            raise Unavailable('Machine identity is unverified. Set machine_id from this box in codesys.json before any action.')
        if target.get('package'):
            row['actions'].append('install' if info['version'] == 'not installed' else 'update')
        if not binding(target):
            raise Unavailable(GATEWAY)
        if info['version'] == 'not installed':
            return row
        if info.get('service') != 'active':
            raise Unavailable('Linux runtime service is not active; current application state is unknown. Inspect codesyscontrol in a terminal.')
        with mcp_session(config) as client:
            row['state'] = runtime_state(client, target)
        row['application'] = target['application']
        if row['state'] != 'unknown':
            row['actions'].extend(TOOLS)
    except Unavailable as exc:
        row['errors'].append(str(exc))
    return row


def targets(db, params):
    if params:
        raise ccboard.Invalid('targets takes no query parameters')
    config = inventory()
    if not _LOCK.acquire(blocking=False):
        raise ccboard.Invalid('CODESYS operation in progress; refresh after it finishes.')
    try:
        return {'targets': [snapshot(config, t) for t in config['targets']],
                'checked_at': stamp(), 'warning': WARNING, 'gateway_help': GATEWAY,
                'setup': 'Configure AGENTMUX_HOME/codesys.json; example in dashboard/codesys_panel.py. No target is assumed.'}
    finally:
        _LOCK.release()


def journal(db, target, action, actor, outcome, operation_id, **detail):
    # Commit intent before contacting equipment. Keep it even if the HTTP request
    # later fails/rolls back. Only this endpoint owns this fresh board connection.
    db.execute('INSERT INTO journal (at,kind,agent,subject,body) VALUES (?,?,?,?,?)',
               (stamp(), 'note' if outcome == 'success' else 'blocked' if outcome == 'failed' else 'plan',
                actor, 'codesys:' + target['id'], json.dumps(dict(target=target['id'],
                address=target['ssh'], action=action, actor=actor, outcome=outcome,
                operation_id=operation_id, **detail))))
    db.commit()


def backup_script(operation_id):
    # Missing paths on a fresh installation are fine; unreadable/changing files
    # are not. Never suppress tar errors and proceed with a partial backup.
    return ("set -eu\nsudo -n install -d -m 700 /var/backups/agentmux-codesys\n"
            "sudo -n sh -c 'umask 077; set --; "
            "for p in var/opt/codesys etc/codesyscontrol; do "
            "if test -e /$p; then set -- \"$@\" \"$p\"; fi; done; "
            "tar -czf /var/backups/agentmux-codesys/" + operation_id +
            ".tgz -C / --files-from /dev/null \"$@\"'\n")


def package_script(target, install=False, operation_id=''):
    pkg = target['package']
    path, version, sha = (shlex.quote(pkg[k]) for k in ('path', 'version', 'sha256'))
    script = (f"set -eu\ntest \"$(uname -s)\" = Linux\ntest \"$(uname -m)\" = x86_64\n"
              f"test \"$(cat /etc/machine-id)\" = {shlex.quote(target['machine_id'])}\n"
              f"test \"$(dpkg-deb -f {path} Package)\" = codesyscontrol\n"
              f"test \"$(dpkg-deb -f {path} Architecture)\" = amd64\n"
              f"test \"$(dpkg-deb -f {path} Version)\" = {version}\n"
              f"test \"$(sha256sum {path} | cut -d ' ' -f 1)\" = {sha}\n")
    if install:
        script += backup_script(operation_id)
        script += (f"sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-remove {path}\n"
                   f"test \"$(dpkg-query -W -f='${{Version}}' codesyscontrol)\" = {version}\n"
                   "systemctl is-active --quiet codesyscontrol\n")
    return script


def perform(config, target, action, reset_type, operation_id, before_version):
    # One SSH connection per action: identity/version check, backup, and package
    # install (if requested) are a single batch. No connection retries.
    preflight = ("set -eu\ntest \"$(uname -s)\" = Linux\n"
                 "test \"$(uname -m)\" = x86_64\n"
                 f"test \"$(cat /etc/machine-id)\" = {shlex.quote(target['machine_id'])}\n" +
                 PROBE + f"test \"$runtime_version\" = {shlex.quote(before_version)}\n")
    if action in ('install', 'update'):
        ssh(target, preflight + package_script(target, True, operation_id), timeout=180)
        return
    ssh(target, preflight + "systemctl is-active --quiet codesyscontrol\n" + backup_script(operation_id), timeout=45)
    with mcp_session(config) as client:
        runtime_state(client, target)  # check active application again in this session
        args = {'projectFilePath': target['project']}
        # Keep forbids a download/online change; never implicitly start on login.
        client.call('login_to_runtime', {**args, 'onlineChangeOption': 'Keep', 'startAfterLogin': False})
        if action == 'reset':
            args['resetOption'] = reset_type
        client.call(TOOLS[action], args)


def change(db, body, boot=False):
    if not isinstance(body, dict) or set(body) - {'target', 'actor', 'action', 'reset_type', 'phase', 'token', 'confirm'}:
        raise ccboard.Invalid('Invalid CODESYS action fields')
    actor = ccboard.text(body.get('actor'), 'actor', 64, required=True, pattern=ccboard.NAME_RE)
    action = 'boot' if boot else body.get('action')
    if (boot and body.get('action', 'boot') != 'boot') or not isinstance(action, str) or action not in set(TOOLS) | {'install', 'update'}:
        raise ccboard.Invalid('Unsupported CODESYS action')
    reset_type = body.get('reset_type')
    if (action == 'reset' and (not isinstance(reset_type, str) or reset_type not in RESET)) or (action != 'reset' and reset_type is not None):
        raise ccboard.Invalid('Reset requires Warm, Cold, or Origin; other actions take no reset_type')
    if body.get('phase') not in ('prepare', 'execute'):
        raise ccboard.Invalid('Prepare an action, then execute with its confirmation token')
    config = inventory()
    target = next((t for t in config['targets'] if t['id'] == body.get('target')), None)
    if target is None:
        raise ccboard.Invalid('Unknown configured target')
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    request = (str(ccstore.HOME_DIR), fingerprint, target['id'], actor, action, reset_type)
    if not _LOCK.acquire(blocking=False):
        raise ccboard.Invalid('CODESYS operation in progress; wait before retrying.')
    try:
        now = time.monotonic()
        for token in list(_PENDING):
            if _PENDING[token]['expires'] < now:
                del _PENDING[token]
        if body['phase'] == 'execute':
            token = body.get('token')
            if not isinstance(token, str) or body.get('confirm') is not True:
                raise ccboard.Invalid('Explicit confirmation and prepared token required')
            pending = _PENDING.pop(token, None)  # consume before any attempt; no replay
            if not pending or pending['request'] != request:
                raise ccboard.Invalid('Confirmation expired, consumed, or does not match target/action/actor/configuration')
        if body['phase'] == 'prepare':
            row = snapshot(config, target, package_check=action in ('install', 'update'))
            if action not in row['actions']:
                raise ccboard.Invalid('Action unavailable. ' + ' '.join(row['errors']))
            if len(_PENDING) >= 100:
                raise ccboard.Invalid('Too many pending confirmations; wait for expiry')
            text = f"{action.upper()} on {target['name']} ({target['id']}, {target['ssh']})"
            if action == 'reset':
                text += f" — {reset_type} reset: {RESET[reset_type]}. DESTRUCTIVE."
            if action in ('install', 'update'):
                text += f" — Linux SL {row['runtime_version']} to {target['package']['version']}. Runtime may restart and stop equipment. {WARNING}"
            else:
                text += ' Runtime data will be backed up first; login uses Keep (no download).'
            text += f" Actor: {actor}. Confirm this equipment is safe to change."
            token = secrets.token_urlsafe(32)
            _PENDING[token] = {'request': request, 'expires': now + 120, 'version': row['runtime_version']}
            return {'confirmation': text, 'token': token, 'expires_in': 120}
        operation_id = secrets.token_hex(16)
        detail = {'reset_type': reset_type, 'before_version': pending['version'],
                  'package_version': (target.get('package') or {}).get('version') if action in ('install', 'update') else None}
        journal(db, target, action, actor, 'intent', operation_id, **detail)
        try:
            perform(config, target, action, reset_type, operation_id, pending['version'])
        except (Unavailable, OSError) as exc:
            journal(db, target, action, actor, 'failed', operation_id, **detail)
            raise ccboard.Invalid('Operation failed or outcome unknown; inspect the target before retrying. ' +
                                  (str(exc) if isinstance(exc, Unavailable) else 'Local transport unavailable.')) from None
        journal(db, target, action, actor, 'success', operation_id, **detail)
        return {'ok': True, 'operation_id': operation_id,
                'message': 'Operation completed; refresh target state. Backup: /var/backups/agentmux-codesys/' + operation_id + '.tgz'}
    finally:
        _LOCK.release()


def plcstate(db, body):
    return change(db, body)


def bootapp(db, body):
    return change(db, body, boot=True)
