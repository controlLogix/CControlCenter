"""Bounded server-side conversation snapshot and CLI-guarded pane sends.

Courier log receipts lack message IDs: never infer delivery from a cursor (the
courier also adopts old outboxes at EOF). Unconfirmed history stays explicit.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading

import ccboard
import ccstore

HOME_DIR = ccstore.HOME_DIR
REPO = Path(__file__).resolve().parent.parent
STATES = ('queued', 'delivered', 'retried', 'dropped', 'dead-recipient', 'unknown', 'recorded')
SEND_SLOT = threading.BoundedSemaphore(2)


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def read_file(folder, name, budget):
    """Pin directories, reject links/devices, bound total bytes, preserve offsets."""
    directory = fd = None
    try:
        directory = os.open(HOME_DIR / folder if folder else HOME_DIR,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            return b'', 0, None
        size = min(info.st_size, 262144, budget[0])
        start = info.st_size - size
        os.lseek(fd, start, os.SEEK_SET)
        raw = os.read(fd, size)
        budget[0] -= len(raw)
        if start:
            cut = raw.find(b'\n') + 1
            raw, start = raw[cut:], start + cut
        return raw, start, info
    except OSError:
        return b'', 0, None
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def records(folder, name, budget):
    raw, offset, info = read_file(folder, name, budget)
    for line in raw.splitlines(keepends=True):
        offset += len(line)
        if not line.endswith(b'\n'):
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                yield value, offset, info
        except (ValueError, UnicodeError, RecursionError):
            continue


def files(folder):
    path = HOME_DIR / folder
    if path.is_symlink():
        return []
    try:
        return sorted(p.name for p in path.iterdir()
                      if re.fullmatch(r'[A-Za-z0-9_.-]{1,64}\.jsonl', p.name))[:128]
    except OSError:
        return []


def message(value, source, state, reason='', **extra):
    if not isinstance(value, dict):
        return None
    sender, recipient = value.get('sender'), value.get('recipient') or ''
    if not isinstance(sender, str) or not ccstore.NAME_PATTERN.fullmatch(sender):
        return None
    if not isinstance(recipient, str) or (recipient and not ccstore.NAME_PATTERN.fullmatch(recipient)):
        return None
    if not isinstance(value.get('body'), str):
        return None
    fields = {k: value.get(k) or '' for k in ('at', 'sender', 'recipient', 'kind', 'body', 'ref')}
    if any(not isinstance(v, str) for v in fields.values()):
        return None
    fields['body'] = fields['body'][:65536]
    fields['ref'] = fields['ref'][:256]
    pair = sorted({sender, recipient or 'broadcast'})
    return dict(fields, id=identity(fields), pair=pair,
                thread=identity([pair, fields['ref']]), source=source,
                state=state, reason=str(reason)[:2000], **extra)


def live_agents():
    try:
        result = subprocess.run(['tmux', '-L', 'agentmux', 'list-sessions', '-F', '#{session_name}'],
                                capture_output=True, text=True, timeout=3)
        if result.returncode and not ('no server running' in result.stderr or 'No such file' in result.stderr):
            return None
        return set(result.stdout.splitlines())
    except (OSError, subprocess.SubprocessError):
        return None


def chatter(db, params):
    if set(params) - {'limit', 'agent', 'card', 'state'}:
        raise ccboard.Invalid('unknown chatter filter')
    def one(key, default=''):
        values = params.get(key, [default])
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
            raise ccboard.Invalid('invalid chatter filter')
        return values[0]
    raw_limit = one('limit', '500')
    if not re.fullmatch(r'[0-9]{1,4}', raw_limit) or not 1 <= int(raw_limit) <= 2000:
        raise ccboard.Invalid('limit must be 1..2000')
    agent, card, state = one('agent'), one('card'), one('state')
    if state and state not in STATES:
        raise ccboard.Invalid('unknown chatter state')
    budget, merged = [2097152], {}
    def add(row):
        if row:
            previous = merged.get(row['id'])
            row['sources'] = sorted(set((previous or {}).get('sources', []) + [row['source']]))
            merged[row['id']] = row
    for name in files('queue'):
        cursor_raw, _, _ = read_file('courier', name[:-6] + '.cursor', budget)
        try:
            cursor = json.loads(cursor_raw)
            if not isinstance(cursor, dict):
                cursor = {}
        except (ValueError, UnicodeError):
            cursor = {}
        for value, end, info in records('queue', name, budget):
            consumed = (cursor.get('dev'), cursor.get('ino')) == (info.st_dev, info.st_ino) and isinstance(cursor.get('offset'), int) and end <= cursor['offset']
            add(message(value, 'queue', 'unknown' if consumed else 'queued',
                        'Courier consumed or adopted this record; no identity-bearing receipt.' if consumed else 'Awaiting courier delivery.'))
    budget[0] = 2097152  # reserve capacity for delivery state even under queue volume
    for row in db.execute('SELECT * FROM messages ORDER BY at DESC, id DESC LIMIT 2000'):
        value = message(dict(row), 'messages', 'unknown', 'Stored message; delivery is not confirmed.')
        if value and value['id'] not in merged:
            add(value)
    for value, _, _ in records('courier', 'dead-letter.jsonl', budget):
        add(message(value.get('message'), 'dead-letter', 'dropped', value.get('reason', ''), attempts=value.get('attempts')))
    for value, _, _ in records('courier', 'pending.jsonl', budget):
        attempts = value.get('attempts', 0)
        attempts = attempts if isinstance(attempts, int) and attempts >= 0 else 0
        add(message(value.get('message'), 'pending', 'retried' if attempts else 'queued',
                    value.get('reason', ''), attempts=attempts, next_at=value.get('next_at')))
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chatter_receipts'").fetchone():
        for receipt in db.execute('SELECT payload FROM chatter_receipts ORDER BY id DESC LIMIT 2000'):
            add(message(json.loads(receipt[0]), 'operator-send', 'delivered', 'CLI guarded send completed.'))
    for name in files('inbox'):
        for value, _, _ in records('inbox', name, budget):
            add(message(value, 'inbox', 'delivered', 'Written to recipient inbox.'))
    # Log events cannot safely be joined to a message/card: the log omits both.
    raw, offset, _ = read_file('courier', 'courier.log', budget)
    for line in raw.splitlines(keepends=True):
        offset += len(line)
        if not line.endswith(b'\n'):
            continue
        match = re.fullmatch(r'(\S+)\s+sent\s+([\w.-]+) -> ([\w.-]+) \(([^,)]+)(?:, retry (\d+))?\)\s*', line.decode('utf-8', 'replace'))
        if match:
            at, sender, recipient, kind, attempt = match.groups()
            row = message(dict(at=at, sender=sender, recipient=recipient, kind=kind,
                               body='Courier delivery confirmed; historical log does not retain body or card.'),
                          'courier-log', 'delivered', 'Receipt cannot be matched to a message identity.')
            if row:
                row['id'] = identity(['courier-log', offset, line.decode('utf-8', 'replace')])
                add(row)
    journal = [dict(r) for r in db.execute('SELECT * FROM journal ORDER BY at DESC, id DESC LIMIT 2000')]
    journal.extend(v for v, _, _ in records('', 'journal.jsonl', budget))
    for value in journal:
        body = str(value.get('subject') or '') + '\n' + str(value.get('body') or '')
        ref = re.search(r'\b[A-Z][A-Z0-9]*-\d+\b', body)
        row = message(dict(at=value.get('at'), sender=value.get('agent') or 'orchestrator',
                           kind=value.get('kind'), body=body.strip(), ref=ref.group() if ref else ''),
                      'journal', 'recorded')
        add(row)
    running = live_agents()
    virtual = set(os.environ.get('AGENTMUX_VIRTUAL_AGENTS', 'orchestrator').split(','))
    for row in merged.values():
        if row['state'] in ('queued', 'retried') and row['recipient'] and running is not None and row['recipient'] not in running | virtual:
            row['delivery_state'] = row['state']
            row['state'] = 'dead-recipient'
            row['reason'] = (row['reason'] + ' Recipient has no live pane.').strip()
    rows = sorted(merged.values(), key=lambda r: (ccstore.timestamp_sort_key(r['at']) or '', r['id']), reverse=True)
    shown = [r for r in rows if (not agent or agent in (r['sender'], r['recipient']))
             and (not card or r['ref'] == card) and (not state or r['state'] == state)]
    return dict(entries=shown[:int(raw_limit)], total=len(shown), bounded=True,
                agents=sorted({a for r in rows for a in (r['sender'], r['recipient']) if a}),
                live_agents=sorted(running) if running is not None else None,
                cards=sorted({r['ref'] for r in rows if r['ref']}), states=list(STATES),
                note='Bounded recent history. Unknown means delivery cannot be proven; old courier receipts have no card or body.')


def chatsend(db, body):
    if not isinstance(body, dict) or set(body) - {'recipient', 'text', 'ref'}:
        raise ccboard.Invalid('allowed fields: recipient, text, ref')
    recipient, text, ref = body.get('recipient'), body.get('text'), body.get('ref', '')
    if not isinstance(recipient, str) or not ccstore.NAME_PATTERN.fullmatch(recipient):
        raise ccboard.Invalid('invalid recipient')
    if not isinstance(text, str) or not text.strip() or len(text) > 8192 or '\x00' in text:
        raise ccboard.Invalid('text must be 1..8192 characters without NUL')
    if not isinstance(ref, str) or len(ref) > 256 or '\x00' in ref:
        raise ccboard.Invalid('invalid card reference')
    # cmd_send treats its first text argument --force as an option. Prefix ALL
    # user text so even that exact string can never bypass the modal guard.
    payload = '[operator]' + (f' ref {ref}' if ref else '') + ': ' + text
    if not SEND_SLOT.acquire(blocking=False):
        raise ccboard.Invalid('send busy; try again shortly')
    try:
        script = 'exec bash <(tr -d "\\r" < "$0") "$@"'
        result = subprocess.run(['bash', '-c', script, str(REPO / 'agentmux.sh'), 'send', recipient, payload],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as err:
        return dict(ok=False, error=f'Send did not confirm completion: {type(err).__name__}. Inspect the pane before retrying.',
                    key_hint=f'agentmux key {recipient} Escape')
    finally:
        SEND_SLOT.release()
    if result.returncode:
        detail = '\n'.join(line for line in (result.stderr or result.stdout).splitlines() if '--force' not in line)
        return dict(ok=False, error=detail[:2000] or 'CLI refused send.', key_hint=f'agentmux key {recipient} Escape')
    at = ccstore.timestamp()
    db.execute('INSERT INTO messages(at,sender,recipient,kind,body,ref) VALUES(?,?,?,?,?,?)',
               (at, 'operator', recipient, 'request', text, ref))
    db.execute('CREATE TABLE IF NOT EXISTS chatter_receipts(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('INSERT INTO chatter_receipts(payload) VALUES(?)', (json.dumps(dict(
        at=at, sender='operator', recipient=recipient, kind='request', body=text, ref=ref)),))
    # Persist a receipt independently of queue/courier inference.
    db.execute('INSERT INTO journal(at,kind,agent,subject,body) VALUES(?,?,?,?,?)',
               (ccstore.timestamp(), 'note', 'operator', f'Sent to {recipient}', ref))
    return dict(ok=True, detail='CLI send completed.')
