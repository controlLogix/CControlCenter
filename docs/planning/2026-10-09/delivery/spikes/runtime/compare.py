"""Run from a disposable copy with pinned dependencies; never use a user's hub."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import nats


async def main():
    root = Path(__file__).resolve().parent
    # A failed repeat must not leave an earlier success as the apparent result.
    (root/'comparison-result.json').unlink(missing_ok=True)
    cache = Path.home() / '.cache/agentmux-governance'
    go = cache / 'runtime-comparison/go/bin/go'
    server = cache / 'tools/nats-server'
    payload = {'schemaVersion': 'spike.v1', 'operationId': 'op-001',
               'context': {'organizationId': 'org-demo', 'projectId': 'project-demo'},
               'data': {'label': 'café', 'enabled': True, 'revision': 7, 'items': ['a', 'b']}}
    result = {'scope': 'Core NATS JSON interoperability and Go cross-compilation only',
              'platform': platform.platform(), 'python': sys.version, 'node': subprocess.check_output(['node', '--version'], text=True).strip(),
              'go': subprocess.check_output([str(go), 'version'], text=True).strip(),
              'nats': subprocess.check_output([str(server), '--version'], text=True).strip(),
              'clients': [], 'crossBuilds': [], 'negativeChecks': [],
              'limits': ['Not a throughput/latency benchmark or full plugin SDK.', 'No JetStream, account isolation, restart, container, native macOS execution or user-host qualification.']}
    for target_os, arch in [('linux', 'amd64'), ('linux', 'arm64'), ('darwin', 'amd64'), ('darwin', 'arm64')]:
        binary = root / f'client-{target_os}-{arch}'
        env = dict(os.environ, GOOS=target_os, GOARCH=arch, CGO_ENABLED='0', GOTOOLCHAIN='local')
        subprocess.run([str(go), 'build', '-trimpath', '-o', str(binary), '.'], cwd=root, env=env, check=True)
        result['crossBuilds'].append({'os': target_os, 'arch': arch, 'bytes': binary.stat().st_size,
                                     'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                                     'executed': target_os == 'linux' and arch == 'amd64'})
    subprocess.run(['node', 'node_modules/typescript/bin/tsc', '-p', '.'], cwd=root, check=True)
    with tempfile.TemporaryDirectory(prefix='amx-runtime-comparison-') as temp:
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
        token = secrets.token_hex(24)
        conf = Path(temp) / 'server.conf'
        conf.write_text(f'host: "127.0.0.1"\nport: {port}\nauthorization {{ token: "{token}" }}\n')
        conf.chmod(0o600)
        with (Path(temp) / 'server.log').open('wb') as log:
            proc = subprocess.Popen([str(server), '-c', str(conf)], stdout=log, stderr=log)
            nc = None
            try:
                for _ in range(80):
                    if proc.poll() is not None: raise RuntimeError('Disposable broker stopped before readiness')
                    try:
                        reader, writer = await asyncio.open_connection('127.0.0.1', port)
                        line = await asyncio.wait_for(reader.readline(), 1)
                        writer.close(); await writer.wait_closed()
                        if line.startswith(b'INFO '): break
                    except (OSError, TimeoutError): pass
                    await asyncio.sleep(.05)
                else: raise RuntimeError('Disposable broker did not become ready')
                nc = await nats.connect(f'nats://127.0.0.1:{port}', token=token, allow_reconnect=False)
                received = []
                subject = 'amx.spike.' + secrets.token_hex(8)
                async def respond(msg):
                    obj = json.loads(msg.data)
                    if obj != payload: raise ValueError('Unexpected wire content')
                    received.append(obj)
                    await msg.respond(json.dumps({'request': obj, 'server': 'python'}, ensure_ascii=False).encode())
                await nc.subscribe(subject, cb=respond); await nc.flush()
                env = dict(os.environ, AMX_SPIKE_URL=f'nats://127.0.0.1:{port}', AMX_SPIKE_TOKEN=token,
                           AMX_SPIKE_SUBJECT=subject, AMX_SPIKE_PAYLOAD=json.dumps(payload, ensure_ascii=False))
                for command in [[str(root/'client-linux-amd64')], [sys.executable, 'client.py'], ['node', 'dist/client.js']]:
                    child = await asyncio.create_subprocess_exec(*command, cwd=root, env=env,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    try: out, err = await asyncio.wait_for(child.communicate(), 8)
                    except TimeoutError:
                        child.kill(); await child.wait(); raise
                    if child.returncode != 0: raise RuntimeError(f'Client failed ({command[0]}): {err.decode()}')
                    report = json.loads(out); assert report['ok'] is True
                    result['clients'].append(report)
                assert len(received) == 3
                # Every client must fail when the responding service is absent.
                env['AMX_SPIKE_SUBJECT'] = subject + '.absent'
                for command in [[str(root/'client-linux-amd64')], [sys.executable, 'client.py'], ['node', 'dist/client.js']]:
                    child = await asyncio.create_subprocess_exec(*command, cwd=root, env=env,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    try: out, _ = await asyncio.wait_for(child.communicate(), 8)
                    except TimeoutError:
                        child.kill(); await child.wait(); raise
                    assert child.returncode != 0 and b'"ok":true' not in out and b'"ok": true' not in out
                    result['negativeChecks'].append({'clientCommand': command[0], 'absentServiceExitCode': child.returncode})
            finally:
                if nc: await nc.close()
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
    result['sourceSha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()
                              if p.suffix in ('.py', '.go', '.ts') or p.name in ('go.mod', 'go.sum', 'package.json', 'package-lock.json', 'tsconfig.json')}
    result['passed'] = True
    (root/'comparison-result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': True, 'clients': result['clients'], 'crossBuilds': len(result['crossBuilds']),
                      'negativeChecks': len(result['negativeChecks'])}))


if __name__ == '__main__':
    asyncio.run(main())
