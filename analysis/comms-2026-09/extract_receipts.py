#!/usr/bin/env python3
"""extract_receipts.py - what each agent CLI's OWN logs say it received as a user turn.

Phase A extractor (see README.md). Stdlib only, read-only, deterministic.
Writes out/receipts.jsonl: one `type=received` record per user turn (or per courier
envelope, when a single turn carried several).

Sources (all opened read-only; sqlite via ?mode=ro URIs):
  codex   rollout JSONL (event_msg item_completed UserMessage)       ~/.codex, ~/.codex-wsl, /mnt/c/Users/Nick/.codex
          logs_2.sqlite  (codex_core::session::handlers Submission UserInput) - fills rollout gaps
          history.jsonl  (composer submissions)                      - only entries no rollout/log covers
  claude  projects/**/*.jsonl  (user turns, queued_command attachments, queue-operation enqueue)
          history.jsonl        - only entries no transcript covers
          under ~/.agentmux/claude-config/<agent>/ and ~/.claude-wsl/
  grok    sessions/*/*/updates.jsonl (ACP user_message_chunk) - chat_history.jsonl only when no updates
          logs/unified.jsonl  (pager prompt.enqueue / prompt.drain) - queue delay and never-drained input

Everything is cut at the snapshot instant (CUTOFF) so that live, still-growing logs give
identical output on every run.

agentmux deletes ~/.agentmux/claude-config/<agent>/ when it tears a team down. The nfl-lead and
nfl-rev transcripts vanished at ~2026-09-30T03:12Z, mid-analysis; the 78 records extracted from
them just before are frozen in out/receipts.rescued-claude-config.jsonl and merged back only
while their source files are missing.

Mapping a CLI session to an agentmux pane name (detail.map_method, detail.map_conf):
  high  config-dir (claude-config/<agent>), shell-snapshot-env (codex shell_snapshots/<sid>.*.sh
        exports AGENTMUX_AGENT), sidecar-start (snapshot run/<name>.{cli,cwd,started}, <=60 s),
        or two independent medium methods that agree
  med   brief-name ("You are X" / "named X" / AGENTMUX_AGENT=X with X a known pane name),
        dispatch-pointer (dispatch/TM-NNN.md -> pane tm-NNN), run-assign / run-ref (runs/*/events
        assign rows), brief-alias (team role -> pane learned from high sessions), self-report
        (grok compaction summary), pane-content (>=2 distinctive received snippets found in one
        pane log, sender's own log excluded)
  low   env-mention (AGENTMUX_AGENT=X dominant in the session's own tool traffic), pane-content
        with a single snippet
"""
import collections
import datetime
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys

HOME = '/home/nick'
SNAP = HOME + '/agentmux-comms-snapshot/20260929-215601'
# Snapshot directory name is local wall clock (CDT, UTC-5): 2026-09-29 21:56:01 CDT.
CUTOFF = datetime.datetime(2026, 9, 30, 2, 56, 1, tzinfo=datetime.timezone.utc)
CUTOFF_TS = CUTOFF.timestamp()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out', 'receipts.jsonl')
RESCUE = os.path.join(HERE, 'out', 'receipts.rescued-claude-config.jsonl')

CODEX_ROOTS = [
    (HOME + '/.codex', 'codex-home'),
    (HOME + '/.codex-wsl', 'codex-wsl'),
    ('/mnt/c/Users/Nick/.codex', 'codex-win-copy'),
]
CLAUDE_CFG = HOME + '/.agentmux/claude-config'
CLAUDE_WSL = HOME + '/.claude-wsl'
GROK = HOME + '/.grok'
PANE_LOGS = HOME + '/.agentmux/logs'

STATS = collections.Counter()

# --------------------------------------------------------------------------- utils

ANSI_RE = re.compile(r'\x1b\[[0-9;?<>=!]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|\x1b[@-Z\\-_=>]')
PASTE_RE = re.compile(r'\x1b?\[20[01]~')
ENV_RE = re.compile(r'\[agentmux\] from (?P<sender>[^\s()]+) \((?P<kind>[^)]*)\)(?: ref (?P<ref>[^\s:]+))?: ?')
DISPATCH_RE = re.compile(r'(?:/home/nick|~|\$HOME)/\.agentmux/dispatch/(TM-\d+)[^\s]*\.md')
WS_RE = re.compile(r'\s+')
USER_QUERY_RE = re.compile(r'^\s*<user_query>\s*(.*?)\s*</user_query>\s*$', re.S)
PASTED_TAG_RE = re.compile(r'<pasted_content id="[^"]*">\n?|\n?</pasted_content>')


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def iso_ms(ts):
    d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    return d.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (d.microsecond // 1000)


def parse_iso(s):
    if not s:
        return None
    s = s.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    m = re.match(r'^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$', s)
    if m and m.group(2) and len(m.group(2)) > 7:  # nanoseconds -> microseconds
        s = m.group(1) + m.group(2)[:7] + m.group(3)
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.timestamp()


def v7_ts(uuid):
    try:
        return int(uuid.replace('-', '')[:12], 16) / 1000.0
    except ValueError:
        return None


def clean(text):
    text = ANSI_RE.sub('', text)
    text = PASTE_RE.sub('', text)
    return text


def norm(text):
    return WS_RE.sub(' ', text).strip()


def sha1(s):
    return hashlib.sha1(s.encode('utf-8', 'surrogatepass')).hexdigest()


def unwrap(text, cli):
    """Strip framing the CLI itself adds around what was typed/pasted."""
    wrappers = []
    m = USER_QUERY_RE.match(text)
    if m:
        text = m.group(1)
        wrappers.append('user_query')
    if '<pasted_content id="' in text:
        text = PASTED_TAG_RE.sub('', text)
        wrappers.append('pasted_content')
    return text, wrappers


def segments(text):
    """Split a turn into courier-envelope segments. Returns list of (raw_segment, env_match or None)."""
    starts = [m for m in ENV_RE.finditer(text) if m.start() == 0 or text[m.start() - 1] == '\n'
              or not text[:m.start()].strip()]
    if len(starts) <= 1:
        m = starts[0] if starts else None
        if m is None:
            m2 = ENV_RE.search(text)
            if m2 and not text[:m2.start()].strip():
                m = m2
        return [(text, m)]
    segs = []
    head = text[:starts[0].start()]
    if head.strip():
        segs.append((head, None))
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        segs.append((text[m.start():end], m))
    return segs


def body_fields(raw, cli):
    """Return list of dicts: prefix, body_sha, body_len, envelope detail, for each segment of a turn."""
    text = clean(raw)
    text, wrappers = unwrap(text, cli)
    segs = segments(text)
    turn_norm = norm(text)
    out = []
    for i, (seg, m) in enumerate(segs):
        d = {}
        body = seg
        if m is not None:
            local = ENV_RE.match(seg.lstrip())
            if local:
                body = seg.lstrip()[local.end():]
                d['envelope'] = True
                d['envelope_kind'] = 'courier'
                d['env_sender'] = local.group('sender')
                d['env_kind'] = local.group('kind')
                if local.group('ref'):
                    d['env_ref'] = local.group('ref')
        dm = DISPATCH_RE.search(body)
        if dm and len(norm(body)) < 600:
            d['envelope'] = True
            d.setdefault('envelope_kind', 'dispatch-pointer')
            if d['envelope_kind'] != 'dispatch-pointer':
                d['envelope_kind'] = d['envelope_kind'] + '+dispatch-pointer'
            d['dispatch_card'] = dm.group(1)
        nb = norm(body)
        rec = {
            'prefix': nb[:80],
            'body_sha': sha1(nb) if nb else None,
            'body_len': len(nb),
            'detail': d,
        }
        if wrappers:
            d['wrapper'] = wrappers
        if len(segs) > 1:
            d['segment'] = [i + 1, len(segs)]
            d['turn_body_sha'] = sha1(turn_norm)
        d['raw_len'] = len(raw)
        out.append(rec)
    return out


def full_sha(raw):
    """sha of the whole normalized turn (framing stripped, envelope kept) - used for dedupe only."""
    t, _ = unwrap(clean(raw), None)
    return sha1(norm(t))


def jsonl(path):
    """Yield (lineno, obj) for each parseable line; never raises on a torn last line."""
    try:
        fh = open(path, 'r', encoding='utf-8', errors='replace')
    except OSError:
        return
    with fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield i, json.loads(line)
            except ValueError:
                STATS['bad_json_line'] += 1


def ro_connect(path):
    return sqlite3.connect('file:%s?mode=ro' % path, uri=True)


# --------------------------------------------------------------------------- session registry

class Session:
    def __init__(self, cli, sid):
        self.cli = cli
        self.sid = sid
        self.cwd = None
        self.start = None
        self.store = None
        self.evidence = []      # (name, method, conf, note)
        self.turns = []         # raw user texts in order (for mapping)
        self.files = []         # files to scan for env mentions
        self.meta = {}
        self.agent = None
        self.map_method = None
        self.map_conf = None
        self.agent_hint = None
        self.map_conflict = None


SESSIONS = {}


def sess(cli, sid):
    k = (cli, sid)
    if k not in SESSIONS:
        SESSIONS[k] = Session(cli, sid)
    return SESSIONS[k]


RECS = []   # pending records: dict with keys t(float), t_basis, raw, cli, sid, detail, ref, (optional) body override


def add(t, raw, cli, sid, ref, detail, t_basis='utc', nobody_len=None):
    RECS.append({'t': t, 't_basis': t_basis, 'raw': raw, 'cli': cli, 'sid': sid, 'ref': ref,
                 'detail': detail, 'nobody_len': nobody_len})


# --------------------------------------------------------------------------- codex

CODEX_SYNTH_PREFIX = ('<environment_context>', '<user_instructions>', '# AGENTS.md instructions',
                      '<turn_aborted>', '<subagent_notification>')
TITLE_GEN = 'Generate a concise, single-line task title'


def codex_text(content):
    parts = []
    kinds = []
    for c in content or []:
        if not isinstance(c, dict):
            continue
        kinds.append(c.get('type'))
        if c.get('type') in ('text', 'input_text') and isinstance(c.get('text'), str):
            parts.append(c['text'])
    return '\n'.join(parts), kinds


CODEX_PRIMARY = {}   # (sid, full_sha) -> record index list ; also time index per sid
CODEX_BY_SID = collections.defaultdict(list)


def extract_codex_rollouts():
    seen_items = set()
    for root, label in CODEX_ROOTS:
        files = sorted(glob.glob(root + '/sessions/**/*.jsonl', recursive=True)) + \
            sorted(glob.glob(root + '/archived_sessions/**/*.jsonl', recursive=True))
        for f in files:
            sid = None
            m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$', f)
            if m:
                sid = m.group(1)
            s = None
            for ln, o in jsonl(f):
                typ = o.get('type')
                p = o.get('payload') if isinstance(o.get('payload'), dict) else {}
                if typ == 'session_meta':
                    sid = p.get('id') or p.get('session_id') or sid
                    s = sess('codex', sid)
                    s.cwd = s.cwd or p.get('cwd')
                    s.start = s.start or parse_iso(p.get('timestamp')) or parse_iso(o.get('timestamp'))
                    s.store = s.store or label
                    s.meta['originator'] = p.get('originator')
                    s.meta['cli_version'] = p.get('cli_version')
                    src = p.get('source')
                    s.meta['source'] = src if isinstance(src, str) else ('subagent' if isinstance(src, dict) else None)
                    if f not in s.files:
                        s.files.append(f)
                    continue
                if typ != 'event_msg' or p.get('type') != 'item_completed':
                    continue
                item = p.get('item') or {}
                if item.get('type') != 'UserMessage':
                    continue
                if s is None:
                    s = sess('codex', sid)
                    s.store = s.store or label
                    if f not in s.files:
                        s.files.append(f)
                iid = item.get('id')
                if (sid, iid) in seen_items:
                    STATS['codex_rollout_dup_item'] += 1
                    continue
                seen_items.add((sid, iid))
                text, kinds = codex_text(item.get('content'))
                t = parse_iso(o.get('timestamp'))
                if p.get('started_at_ms'):
                    t = p['started_at_ms'] / 1000.0
                if text.lstrip().startswith(CODEX_SYNTH_PREFIX):
                    STATS['codex_synthetic_skipped'] += 1
                    continue
                s.turns.append(text)
                det = {'source': 'rollout', 'store': label, 'turn_id': p.get('turn_id')}
                if [k for k in kinds if k not in ('text', 'input_text')]:
                    det['content_kinds'] = sorted(set(k for k in kinds if k))
                add(t, text, 'codex', sid, '%s:%d' % (f, ln), det)
                CODEX_BY_SID[sid].append((t, full_sha(text), len(RECS) - 1))


def rust_str(s, i):
    out = []
    n = len(s)
    esc = {'n': '\n', 't': '\t', 'r': '\r', '\\': '\\', '"': '"', "'": "'", '0': '\0'}
    while i < n:
        c = s[i]
        if c == '\\' and i + 1 < n:
            nx = s[i + 1]
            if nx == 'u' and i + 2 < n and s[i + 2] == '{':
                j = s.find('}', i + 3)
                if j == -1:
                    return ''.join(out), n, False
                try:
                    out.append(chr(int(s[i + 3:j], 16)))
                except ValueError:
                    pass
                i = j + 1
                continue
            out.append(esc.get(nx, nx))
            i += 2
            continue
        if c == '"':
            return ''.join(out), i + 1, True
        out.append(c)
        i += 1
    return ''.join(out), n, False


TEXT_START = re.compile(r'Text \{ text: "')


def extract_codex_logs():
    for root, label in CODEX_ROOTS:
        db = root + '/logs_2.sqlite'
        if not os.path.exists(db):
            continue
        con = ro_connect(db)
        try:
            rows = con.execute(
                "select id, ts, ts_nanos, thread_id, feedback_log_body from logs "
                "where target = 'codex_core::session::handlers' and feedback_log_body like '%Submission sub=Submission%' "
                "and feedback_log_body like '%UserInput%' order by ts, ts_nanos, id").fetchall()
        finally:
            con.close()
        for rid, ts, tsn, thread, body in rows:
            t = ts + (tsn or 0) / 1e9
            if not thread:
                m = re.search(r'thread_id=([0-9a-f-]{36})', body)
                thread = m.group(1) if m else None
            opm = re.search(r'op: (\w+)', body)
            op = opm.group(1) if opm else None
            parts = []
            truncated = False
            pos = body.find('UserInput')
            while True:
                m = TEXT_START.search(body, pos)
                if not m:
                    break
                txt, pos, ok = rust_str(body, m.end())
                parts.append(txt)
                if not ok:
                    truncated = True
                    break
            text = '\n'.join(parts)
            if text.startswith(TITLE_GEN):
                STATS['codex_logs_titlegen_skipped'] += 1
                continue
            if text.lstrip().startswith(CODEX_SYNTH_PREFIX):
                STATS['codex_synthetic_skipped'] += 1
                continue
            ref = '%s#logs.id=%d' % (db, rid)
            fs = full_sha(text)
            match = None
            best = None
            for (pt, psha, idx) in CODEX_BY_SID.get(thread, []):
                if psha == fs or (truncated and norm(clean(RECS[idx]['raw'])).startswith(norm(clean(text))[:200])):
                    dt = abs(pt - t)
                    if dt < 120 and (best is None or dt < best):
                        best, match = dt, idx
            if match is not None:
                d = RECS[match]['detail']
                d.setdefault('also_in', [])
                if 'logs_2' not in d['also_in']:
                    d['also_in'].append('logs_2')
                d['t_submit'] = iso_ms(t)
                STATS['codex_logs_matched_rollout'] += 1
                continue
            s = sess('codex', thread)
            s.store = s.store or label
            s.turns.append(text)
            if s.start is None:
                s.start = v7_ts(thread)
            det = {'source': 'logs_2', 'store': label, 'op': op}
            if truncated:
                det['log_truncated'] = True
            add(t, text, 'codex', thread, ref, det)
            CODEX_BY_SID[thread].append((t, fs, len(RECS) - 1))
            STATS['codex_logs_only'] += 1


def extract_codex_history():
    for root, label in CODEX_ROOTS:
        hp = root + '/history.jsonl'
        if not os.path.exists(hp):
            continue
        for ln, o in jsonl(hp):
            sid = o.get('session_id')
            t = o.get('ts')
            text = o.get('text') or ''
            if t is None:
                continue
            fs = full_sha(text)
            matched = False
            for (pt, psha, idx) in CODEX_BY_SID.get(sid, []):
                if abs(pt - t) < 120 and (psha == fs or abs(pt - t) < 3):
                    d = RECS[idx]['detail']
                    d.setdefault('also_in', [])
                    if 'history' not in d['also_in']:
                        d['also_in'].append('history')
                    matched = True
                    break
            if matched:
                STATS['codex_history_matched'] += 1
                continue
            s = sess('codex', sid)
            s.store = s.store or label
            s.turns.append(text)
            if s.start is None:
                s.start = v7_ts(sid)
            add(float(t), text, 'codex', sid, '%s:%d' % (hp, ln), {'source': 'history', 'store': label,
                                                                  't_precision': 'seconds'})
            CODEX_BY_SID[sid].append((float(t), fs, len(RECS) - 1))
            STATS['codex_history_only'] += 1


def codex_shell_snapshots():
    for root, label in CODEX_ROOTS:
        for f in sorted(glob.glob(root + '/shell_snapshots/*.sh')):
            sid = os.path.basename(f).split('.')[0]
            try:
                txt = open(f, 'r', encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            m = re.search(r'^declare -x AGENTMUX_AGENT="([^"]+)"', txt, re.M)
            if m:
                sess('codex', sid).evidence.append((m.group(1), 'shell-snapshot-env', 'high', f))


# --------------------------------------------------------------------------- claude

CLAUDE_BY_SID = collections.defaultdict(list)


def claude_text(content):
    if isinstance(content, str):
        return content, 'str'
    parts = []
    kinds = set()
    for c in content or []:
        if isinstance(c, dict):
            kinds.add(c.get('type'))
            if c.get('type') == 'text':
                parts.append(c.get('text') or '')
    if 'tool_result' in kinds:
        return None, 'tool_result'
    return '\n'.join(parts), ','.join(sorted(k for k in kinds if k))


def claude_kind(text):
    s = text.lstrip()
    if s.startswith('<local-command-stdout>') or s.startswith('<local-command-stderr>') or \
            s.startswith('<local-command-caveat>'):
        return 'local-command-output'
    if s.startswith('<command-name>') or s.startswith('<command-message>'):
        return 'slash-command'
    if s.startswith('[Request interrupted by user'):
        return 'interrupt'
    if s.startswith('<teammate-message'):
        return 'teammate-message'
    if s.startswith('Another Claude session sent a message'):
        return 'cross-session'
    if s.startswith('<task-notification>'):
        return 'task-notification'
    return None


def claude_configs():
    cfgs = []
    for d in sorted(glob.glob(CLAUDE_CFG + '/*/')):
        name = os.path.basename(d.rstrip('/'))
        if os.path.islink(d.rstrip('/')):
            continue
        if os.path.isdir(d + 'projects') or os.path.exists(d + 'history.jsonl'):
            cfgs.append((d.rstrip('/'), 'claude-config/' + name, name))
    cfgs.append((CLAUDE_CFG, 'claude-config(shared)', None))
    cfgs.append((CLAUDE_WSL, 'claude-wsl', None))
    return cfgs


def extract_claude():
    for cdir, label, agent in claude_configs():
        files = sorted(glob.glob(cdir + '/projects/*/*.jsonl'))
        for f in files:
            sid = os.path.basename(f)[:-6]
            s = sess('claude', sid)
            s.store = label
            if f not in s.files:
                s.files.append(f)
            if agent:
                s.evidence.append((agent, 'config-dir', 'high', cdir))
            enq = []
            delivered = []
            for ln, o in jsonl(f):
                typ = o.get('type')
                if s.cwd is None and o.get('cwd'):
                    s.cwd = o.get('cwd')
                ts = parse_iso(o.get('timestamp'))
                if s.start is None and ts:
                    s.start = ts
                if typ == 'queue-operation':
                    if o.get('operation') == 'enqueue':
                        c = o.get('content')
                        if isinstance(c, list):
                            c, _ = claude_text(c)
                        if isinstance(c, str):
                            enq.append((ts, c, ln))
                    continue
                if typ == 'attachment':
                    a = o.get('attachment') or {}
                    if a.get('type') == 'queued_command':
                        pr = a.get('prompt')
                        if isinstance(pr, list):
                            pr, _ = claude_text(pr)
                        if not isinstance(pr, str):
                            continue
                        if o.get('isSidechain'):
                            STATS['claude_sidechain_skipped'] += 1
                            continue
                        det = {'source': 'claude-project', 'store': label, 'delivery': 'queued_command'}
                        k = claude_kind(pr)
                        if k:
                            det['kind'] = k
                        add(ts, pr, 'claude', sid, '%s:%d' % (f, ln), det)
                        delivered.append((ts, full_sha(pr), len(RECS) - 1))
                        s.turns.append(pr)
                    continue
                if typ != 'user':
                    continue
                if o.get('isSidechain'):
                    STATS['claude_sidechain_skipped'] += 1
                    continue
                if o.get('isMeta') or o.get('isCompactSummary') or o.get('isVisibleInTranscriptOnly'):
                    STATS['claude_meta_skipped'] += 1
                    continue
                msg = o.get('message') or {}
                text, kinds = claude_text(msg.get('content'))
                if text is None:
                    continue
                k = claude_kind(text)
                if k == 'local-command-output':
                    STATS['claude_local_output_skipped'] += 1
                    continue
                det = {'source': 'claude-project', 'store': label, 'delivery': 'turn'}
                if k:
                    det['kind'] = k
                for key in ('promptSource', 'entrypoint'):
                    if o.get(key):
                        det[key] = o.get(key)
                if isinstance(o.get('origin'), dict) and o['origin'].get('kind'):
                    det['origin'] = o['origin']['kind']
                if o.get('agentName'):
                    det['claude_team_agent'] = o.get('agentName')
                add(ts, text, 'claude', sid, '%s:%d' % (f, ln), det)
                delivered.append((ts, full_sha(text), len(RECS) - 1))
                s.turns.append(text)
            # match enqueues to deliveries
            used = set()
            for (ets, c, ln) in enq:
                fs = full_sha(c)
                hit = None
                for (dts, dsha, idx) in delivered:
                    if idx in used or dsha != fs or dts is None or ets is None:
                        continue
                    if dts >= ets - 2:
                        hit = idx
                        break
                if hit is not None:
                    used.add(hit)
                    RECS[hit]['detail']['t_enqueued'] = iso_ms(ets)
                    STATS['claude_enqueue_matched'] += 1
                else:
                    add(ets, c, 'claude', sid, '%s:%d' % (f, ln),
                        {'source': 'claude-project', 'store': label, 'delivery': 'enqueued-not-delivered'})
                    STATS['claude_enqueue_unmatched'] += 1
            CLAUDE_BY_SID[sid].extend(delivered)
    # history files
    for cdir, label, agent in claude_configs():
        hp = cdir + '/history.jsonl'
        if not os.path.exists(hp):
            continue
        paste_dirs = [cdir + '/paste-cache', CLAUDE_WSL + '/paste-cache']
        used = set()
        for ln, o in jsonl(hp):
            sid = o.get('sessionId')
            tms = o.get('timestamp')
            if not sid or tms is None:
                continue
            t = tms / 1000.0
            disp = o.get('display') or ''
            hit = None
            best = None
            for (dts, dsha, idx) in CLAUDE_BY_SID.get(sid, []):
                if idx in used or dts is None:
                    continue
                dt = abs(dts - t)
                if dt < 20 and (best is None or dt < best):
                    best, hit = dt, idx
            if hit is not None:
                used.add(hit)
                d = RECS[hit]['detail']
                d.setdefault('also_in', [])
                if 'history' not in d['also_in']:
                    d['also_in'].append('history')
                STATS['claude_history_matched'] += 1
                continue
            text = disp
            resolved = True
            pcs = o.get('pastedContents') or {}
            for key in sorted(pcs, key=lambda x: str(x)):
                pc = pcs[key] or {}
                content = pc.get('content')
                if content is None and pc.get('contentHash'):
                    for pd in paste_dirs:
                        pf = '%s/%s.txt' % (pd, pc['contentHash'])
                        if os.path.exists(pf):
                            content = open(pf, 'r', encoding='utf-8', errors='replace').read()
                            break
                ph = re.compile(r'\[Pasted text #%s(?: \+\d+ lines)?\]' % re.escape(str(pc.get('id', key))))
                if content is not None:
                    text = ph.sub(lambda _m: content, text, count=1)
                else:
                    resolved = False
            s = sess('claude', sid)
            s.store = s.store or label
            s.cwd = s.cwd or o.get('project')
            if s.start is None:
                s.start = t
            if agent:
                s.evidence.append((agent, 'config-dir', 'high', cdir))
            s.turns.append(text)
            det = {'source': 'claude-history', 'store': label}
            if pcs:
                det['paste_resolved'] = resolved
            k = claude_kind(text)
            if k:
                det['kind'] = k
            add(t, text, 'claude', sid, '%s:%d' % (hp, ln), det)
            STATS['claude_history_only'] += 1


# --------------------------------------------------------------------------- grok

GROK_GROUPS = collections.defaultdict(list)   # sid -> [(t, raw_len, rec_index)]


def grok_sessions():
    return sorted(glob.glob(GROK + '/sessions/*/*/'))


def extract_grok():
    for d in grok_sessions():
        sid = os.path.basename(d.rstrip('/'))
        s = sess('grok', sid)
        s.store = 'grok'
        try:
            sm = json.load(open(d + 'summary.json', encoding='utf-8', errors='replace'))
        except (OSError, ValueError):
            sm = {}
        s.cwd = (sm.get('info') or {}).get('cwd')
        s.start = v7_ts(sid) or parse_iso(sm.get('created_at'))
        for fn in ('updates.jsonl', 'chat_history.jsonl'):
            if os.path.exists(d + fn):
                s.files.append(d + fn)
        up = d + 'updates.jsonl'
        if os.path.exists(up):
            groups = []
            pending_pid = None
            last_chunk = False
            for ln, o in jsonl(up):
                params = o.get('params') or {}
                u = params.get('update') or {}
                su = u.get('sessionUpdate')
                meta = params.get('_meta') or {}
                t = meta.get('agentTimestampMs')
                t = t / 1000.0 if t else o.get('timestamp')
                if su == 'hook_execution' and u.get('event_name') == 'user_prompt_submit':
                    pending_pid = u.get('prompt_id') or ('hook@%d' % ln)
                    last_chunk = False
                    continue
                if su == 'user_message_chunk':
                    c = u.get('content') or {}
                    txt = c.get('text') if isinstance(c, dict) else None
                    ctype = c.get('type') if isinstance(c, dict) else None
                    if groups and last_chunk and groups[-1]['pid'] == pending_pid:
                        g = groups[-1]
                    else:
                        g = {'pid': pending_pid, 't': t, 'ln': ln, 'parts': [], 'kinds': []}
                        groups.append(g)
                    if isinstance(txt, str):
                        g['parts'].append(txt)
                    g['kinds'].append(ctype)
                    last_chunk = True
                    continue
                if su is not None:
                    last_chunk = False
            for g in groups:
                text = ''.join(g['parts'])
                det = {'source': 'grok-updates', 'store': 'grok'}
                if g['pid']:
                    det['prompt_id'] = g['pid']
                if len(g['parts']) > 1:
                    det['chunks'] = len(g['parts'])
                ks = sorted(set(k for k in g['kinds'] if k and k != 'text'))
                if ks:
                    det['content_kinds'] = ks
                add(g['t'], text, 'grok', sid, '%s:%d' % (up, g['ln']), det)
                GROK_GROUPS[sid].append((g['t'], len(text), len(RECS) - 1))
                s.turns.append(text)
            # synthetic chat entries still carry identity evidence (compaction summaries)
            ch = d + 'chat_history.jsonl'
            if os.path.exists(ch):
                for ln, o in jsonl(ch):
                    if o.get('type') == 'user' and o.get('synthetic_reason') == 'compaction_meta':
                        txt, _ = claude_text(o.get('content'))
                        if txt:
                            s.meta.setdefault('selfreport', []).append(txt[:4000])
            continue
        ch = d + 'chat_history.jsonl'
        if not os.path.exists(ch):
            continue
        t0 = parse_iso(sm.get('created_at')) or v7_ts(sid)
        for ln, o in jsonl(ch):
            if o.get('type') != 'user' or o.get('synthetic_reason'):
                continue
            txt, _ = claude_text(o.get('content'))
            if not txt:
                continue
            if txt.lstrip().startswith('<user_info>'):
                STATS['grok_synthetic_skipped'] += 1
                continue
            add(t0, txt, 'grok', sid, '%s:%d' % (ch, ln),
                {'source': 'grok-chat', 'store': 'grok',
                 'tz_note': 'no per-turn time in chat_history; t is session created_at'}, t_basis='utc')
            s.turns.append(txt)


def extract_grok_unified():
    up = GROK + '/logs/unified.jsonl'
    if not os.path.exists(up):
        return
    pid_sid = {}
    ev = collections.defaultdict(list)
    for ln, o in jsonl(up):
        t = parse_iso(o.get('ts'))
        if t is None or t > CUTOFF_TS:
            continue
        pid = o.get('pid')
        if o.get('sid') and pid is not None:
            pid_sid.setdefault(pid, o['sid'])
        msg = o.get('msg')
        if msg in ('prompt.enqueue', 'prompt.drain'):
            ev[pid].append((t, ln, msg, o.get('ctx') or {}))
    for pid in sorted(ev, key=lambda x: (str(type(x)), x)):
        sid = pid_sid.get(pid)
        queue = []   # unmatched enqueues (t, ln, len)
        drains = []
        for (t, ln, msg, ctx) in ev[pid]:
            if msg == 'prompt.enqueue':
                queue.append([t, ln, ctx.get('len'), False])
            elif ctx.get('kind', 'prompt') == 'prompt':
                L = ctx.get('prompt_len')
                hit = None
                for q in queue:
                    if not q[3] and q[2] == L and q[0] <= t + 0.01:
                        hit = q
                        break
                if hit:
                    hit[3] = True
                drains.append((t, L, hit))
        # attach enqueue/drain times to delivered update groups
        groups = GROK_GROUPS.get(sid, [])
        usedg = set()
        for (dt, L, hit) in drains:
            best = None
            for (gt, glen, idx) in groups:
                if idx in usedg or gt is None:
                    continue
                if glen == L and -2 <= gt - dt <= 30:
                    best = idx
                    break
            if best is not None:
                usedg.add(best)
                d = RECS[best]['detail']
                d['t_drain'] = iso_ms(dt)
                if hit:
                    d['t_enqueued'] = iso_ms(hit[0])
                    d['pager_queue_s'] = round(dt - hit[0], 3)
                STATS['grok_unified_matched'] += 1
        for q in queue:
            if not q[3]:
                det = {'source': 'grok-unified', 'store': 'grok', 'delivery': 'pager-enqueued-not-drained',
                       'pid': pid, 'enqueue_len': q[2]}
                add(q[0], None, 'grok', sid, '%s:%d' % (up, q[1]), det, nobody_len=q[2])
                STATS['grok_enqueue_not_drained'] += 1
                if sid:
                    sess('grok', sid)


# --------------------------------------------------------------------------- mapping

def known_names():
    names = set()
    for f in glob.glob(PANE_LOGS + '/*.log'):
        names.add(os.path.basename(f)[:-4])
    for f in glob.glob(SNAP + '/run/*.cli'):
        names.add(os.path.basename(f)[:-4])
    for ln, o in jsonl(SNAP + '/journal.jsonl'):
        if isinstance(o.get('agent'), str):
            names.add(o['agent'])
    for f in glob.glob(SNAP + '/runs/*/events.jsonl'):
        for ln, o in jsonl(f):
            for k in ('by', 'worker', 'reviewer'):
                if isinstance(o.get(k), str):
                    names.add(o[k])
    for s in SESSIONS.values():
        for (n, m, c, _) in s.evidence:
            names.add(n)
    for d in glob.glob(CLAUDE_CFG + '/*/'):
        if not os.path.islink(d.rstrip('/')) and os.path.isdir(d + 'projects'):
            names.add(os.path.basename(d.rstrip('/')))
    names = {n for n in names if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', n)}
    names.discard('operator')
    return names


def run_assignments():
    jobs = {}
    for f in sorted(glob.glob(SNAP + '/runs/*/events.jsonl')):
        for ln, o in jsonl(f):
            if o.get('event') == 'assign' and o.get('job'):
                jobs[o['job']] = (o.get('worker'), o.get('reviewer'))
    return jobs


def sidecars():
    out = []
    for f in sorted(glob.glob(SNAP + '/run/*.started')):
        name = os.path.basename(f)[:-8]
        try:
            st = parse_iso(open(f).read().strip())
            cli = open(SNAP + '/run/%s.cli' % name).read().strip()
            cwd = open(SNAP + '/run/%s.cwd' % name).read().strip()
        except OSError:
            continue
        out.append((name, cli, cwd, st))
    return out


NAME_TOKEN = r'([A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9])'
BRIEF_PATTERNS = [
    re.compile(r"\bYou are agentmux agent ['\"]?" + NAME_TOKEN),
    re.compile(r"\bYou are (?:the )?['\"]?" + NAME_TOKEN + r"['\"]?(?![A-Za-z0-9_-])"),
    re.compile(r"\byou are ['\"]?" + NAME_TOKEN + r"['\"]?(?![A-Za-z0-9_-])"),
    re.compile(r"\bnamed ['\"]?" + NAME_TOKEN + r"['\"]?(?![A-Za-z0-9_-])"),
    re.compile(r"\$?AGENTMUX_AGENT\s*=\s*['\"]?" + NAME_TOKEN),
]
ENV_MENTION = re.compile(r'AGENTMUX_AGENT=\\?[\'"]?([a-z0-9][a-z0-9_.-]*[a-z0-9])')
JOB_RE = re.compile(r'\bjob ([0-9a-f]{6}/\d+)\b')


NAMED_RE = re.compile(r"\bnamed ['\"]?" + NAME_TOKEN + r"['\"]?(?![A-Za-z0-9_-])")
VERIFY_RE = re.compile(r'__verify_' + NAME_TOKEN + r'__')
ROLE_RE = re.compile(r"\bYou are (?:agentmux agent )?['\"]?([a-z][a-z0-9]*(?:-[a-z0-9]+)+)['\"]?(?![A-Za-z0-9_-])")


def brief_names(text, known):
    # "You are the orchestrator named claude": the explicit name wins over the role word.
    named = [m.group(1) for m in NAMED_RE.finditer(text) if m.group(1) in known]
    if named:
        return list(dict.fromkeys(named))
    found = []
    for p in BRIEF_PATTERNS + [VERIFY_RE]:
        for m in p.finditer(text):
            n = m.group(1)
            if n in known and n not in found:
                found.append(n)
    return found


def pane_content_evidence(targets, known):
    """targets: list of Session needing evidence. Search distinctive snippets of their received
    turns in pane logs; the receiving pane is the log that holds snippets from the most turns."""
    snippets = {}   # snippet bytes -> set of session keys
    per_sess = collections.defaultdict(list)
    senders = {}    # snippet bytes -> envelope sender (its own pane echoes the send; not evidence)
    for s in targets:
        chosen = 0
        for raw in s.turns:
            if chosen >= 6:
                break
            txt, _ = unwrap(clean(raw or ''), s.cli)
            m = ENV_RE.search(txt)
            sender = None
            if m and not txt[:m.start()].strip():
                sender = m.group('sender')
                txt = txt[m.end():]
            lines = [l.strip() for l in txt.split('\n')[:8] if len(l.strip()) >= 45]
            if not lines:
                continue
            line = max(lines, key=len)
            snip = line[8:48]
            if len(snip) < 30 or '  ' in snip:
                continue
            b = snip.encode('utf-8')
            snippets.setdefault(b, set()).add((s.cli, s.sid))
            per_sess[(s.cli, s.sid)].append(b)
            if sender:
                senders.setdefault(b, set()).add(sender)
            chosen += 1
    if not snippets:
        return
    hits = collections.defaultdict(set)   # snippet -> set(log names)
    for f in sorted(glob.glob(PANE_LOGS + '/*.log')):
        name = os.path.basename(f)[:-4]
        try:
            data = open(f, 'rb').read()
        except OSError:
            continue
        for b in snippets:
            if data.find(b) != -1:
                hits[b].add(name)
        del data
    for key, snips in per_sess.items():
        s = SESSIONS[key]
        cnt = collections.Counter()
        for b in set(snips):
            for n in hits.get(b, ()):
                if n in senders.get(b, ()):
                    continue
                cnt[n] += 1
        if not cnt:
            continue
        ranked = sorted(cnt.items(), key=lambda x: (-x[1], x[0]))
        top, n1 = ranked[0]
        n2 = ranked[1][1] if len(ranked) > 1 else 0
        total = len(set(snips))
        if n1 * 2 < total or n1 <= n2:
            continue
        conf = 'med' if n1 >= 2 else 'low'
        s.evidence.append((top, 'pane-content', conf, '%d/%d snippets; runner-up %d' % (n1, total, n2)))


CONF_RANK = {'high': 3, 'med': 2, 'low': 1}
# Early panes were named after their CLI; a pane called "claude" never ran codex.
CLI_NAMES = {'claude', 'codex', 'grok'}


def resolve_mapping():
    known = known_names()
    jobs = run_assignments()
    cars = sidecars()
    # sidecar start match: one session per sidecar, nearest start within 60 s after spawn
    pairs = []
    for (name, cli, cwd, st) in cars:
        for key in sorted(SESSIONS):
            s = SESSIONS[key]
            if cli == s.cli and s.cwd and st and s.start and \
                    cwd.rstrip('/').lower() == s.cwd.rstrip('/').lower() and -5 <= s.start - st <= 60:
                pairs.append((abs(s.start - st), name, key, st))
    used_n, used_k = set(), set()
    for (dt, name, key, st) in sorted(pairs):
        if name in used_n or key in used_k:
            continue
        used_n.add(name)
        used_k.add(key)
        s = SESSIONS[key]
        s.evidence.append((name, 'sidecar-start', 'high', 'started %s, session %+.0fs' % (iso(st), s.start - st)))
    for key in sorted(SESSIONS):
        s = SESSIONS[key]
        # brief names in the first few received turns
        first = [t for t in s.turns[:4] if t]
        if first and claude_kind(first[0]) == 'teammate-message':
            m = re.search(r'You are "([^"]+)"', first[0])
            s.meta['claude_team'] = m.group(1) if m else True
            continue   # Claude Code native team member, not an agentmux pane
        for i, t in enumerate(first):
            nb = norm(clean(t))
            names = brief_names(nb[:3000], known)
            for n in names[:2]:
                s.evidence.append((n, 'brief-name', 'med', 'turn %d' % (i + 1)))
            dm = DISPATCH_RE.search(nb)
            if dm and dm.group(1).lower() in known:
                s.evidence.append((dm.group(1).lower(), 'dispatch-pointer', 'med', dm.group(1)))
            jm = JOB_RE.search(nb[:600])
            if jm and jm.group(1) in jobs:
                w, r = jobs[jm.group(1)]
                head = nb[:300].lower()
                role = None
                if re.search(r'\byou are (?:the )?(?:hired )?(?:\S+ )?worker\b', head):
                    role = 'worker'
                elif re.search(r'\byou are (?:the )?(?:\S+ )?reviewer\b', head):
                    role = 'reviewer'
                if role == 'worker' and w:
                    s.evidence.append((w, 'run-assign', 'med', jm.group(1)))
                elif role == 'reviewer' and r:
                    s.evidence.append((r, 'run-assign', 'med', jm.group(1)))
        for txt in s.meta.get('selfreport', []):
            for n in brief_names(txt, known)[:1]:
                s.evidence.append((n, 'self-report', 'med', 'compaction summary'))
    # env mentions inside the session's own files (commands the agent ran, tool output)
    for key in sorted(SESSIONS):
        s = SESSIONS[key]
        cnt = collections.Counter()
        for f in s.files:
            try:
                with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                    for line in fh:
                        if 'AGENTMUX_AGENT=' in line:
                            for m in ENV_MENTION.finditer(line):
                                if m.group(1) in known:
                                    cnt[m.group(1)] += 1
            except OSError:
                pass
        if cnt:
            ranked = sorted(cnt.items(), key=lambda x: (-x[1], x[0]))
            top, n1 = ranked[0]
            n2 = ranked[1][1] if len(ranked) > 1 else 0
            if n1 >= 2 * max(n2, 1) and n1 >= 2:
                s.evidence.append((top, 'env-mention', 'low', '%d mentions, runner-up %d' % (n1, n2)))
    # run-ref: courier envelopes carrying "ref <run>/<job>" narrow the recipient to that job's
    # worker or reviewer; if every such ref in the session leaves the same single name, use it.
    for key in sorted(SESSIONS):
        s = SESSIONS[key]
        cand = None
        nrefs = 0
        for t in s.turns:
            m = ENV_RE.search(t or '')
            if not m or not m.group('ref') or m.group('ref') not in jobs:
                continue
            w, r = jobs[m.group('ref')]
            names = {x for x in (w, r) if x and not (x in CLI_NAMES and x != s.cli)} - {m.group('sender')}
            if not names:
                continue
            nrefs += 1
            cand = names if cand is None else cand & names
        if cand is not None and len(cand) == 1 and nrefs >= 2:
            s.evidence.append((next(iter(cand)), 'run-ref', 'med', '%d job-ref envelopes' % nrefs))
    # brief-alias: a team brief names a ROLE ("You are agora-release") while the pane has another
    # name (tm-209-worker2). Learn role -> pane from sessions whose pane identity is high, and apply
    # it to same-role sessions within 36 h when every learned pairing agrees.
    def best_high(s):
        hs = sorted({n for (n, m, c, _) in s.evidence if c == 'high'})
        return hs[0] if len(hs) == 1 else None

    def role_of(s):
        first = next((t for t in s.turns if t), None)
        if not first:
            return None
        m = ROLE_RE.search(norm(clean(first))[:400])
        return m.group(1) if m else None
    alias = collections.defaultdict(list)
    for key in sorted(SESSIONS):
        s = SESSIONS[key]
        r = role_of(s)
        p = best_high(s)
        if r and p and s.start:
            alias[r].append((s.start, p))
    for key in sorted(SESSIONS):
        s = SESSIONS[key]
        if best_high(s):
            continue
        r = role_of(s)
        if not r or r not in alias or not s.start:
            continue
        near = {p for (st, p) in alias[r] if abs(st - s.start) <= 36 * 3600}
        if len(near) == 1:
            s.evidence.append((next(iter(near)), 'brief-alias', 'med', 'role %s' % r))
    # pane content for sessions that still lack a high-confidence identity
    for s in SESSIONS.values():
        s.evidence = list(dict.fromkeys(s.evidence))
    targets = []
    for key in sorted(SESSIONS):
        s = SESSIONS[key]
        best = max([CONF_RANK[c] for (_, _, c, _) in s.evidence] or [0])
        if best < 3 and s.turns:
            targets.append(s)
    pane_content_evidence(targets, known)
    # decide
    for key in sorted(SESSIONS):
        s = SESSIONS[key]
        by = collections.defaultdict(list)
        for (n, m, c, note) in s.evidence:
            if n in CLI_NAMES and n != s.cli:
                STATS['evidence_rejected_cross_cli_name'] += 1
                continue
            by[n].append((m, c, note))

        def score(item):
            n, ev = item
            best = max(CONF_RANK[c] for (_, c, _) in ev)
            strong = {m for (m, c, _) in ev if CONF_RANK[c] >= 2}
            eff = best
            if best == 2 and len(strong) >= 2:
                eff = 3
            return (eff, best, len({m for (m, _, _) in ev}), len(ev), n)
        if not by:
            hint = []
            if s.meta.get('claude_team'):
                hint.append('claude-native-team teammate %s' % s.meta['claude_team'])
            if s.cwd:
                hint.append('cwd=' + s.cwd)
            if s.store:
                hint.append('store=' + s.store)
            if s.meta.get('originator'):
                hint.append('originator=' + str(s.meta['originator']))
            s.agent_hint = '; '.join(hint) or None
            continue
        ranked = sorted(by.items(), key=score, reverse=True)
        top = ranked[0]
        sc = score(top)
        s.agent = top[0]
        methods = []
        for (m, c, _) in top[1]:
            if m not in methods:
                methods.append(m)
        s.map_method = '+'.join(sorted(methods))
        s.map_conf = {3: 'high', 2: 'med', 1: 'low'}[sc[0]]
        rivals = [(n, sorted({m for (m, _, _) in ev})) for n, ev in ranked[1:]
                  if max(CONF_RANK[c] for (_, c, _) in ev) >= 2]
        if rivals:
            s.map_conflict = [{'agent': n, 'methods': ms} for n, ms in rivals]
            if s.map_conf == 'high' and score(ranked[1])[0] >= 3:
                s.map_conf = 'med'


# --------------------------------------------------------------------------- output

def build():
    extract_codex_rollouts()
    extract_codex_logs()
    extract_codex_history()
    codex_shell_snapshots()
    extract_claude()
    extract_grok()
    extract_grok_unified()
    resolve_mapping()

    out = []
    for r in RECS:
        t = r['t']
        if t is None:
            STATS['dropped_no_time'] += 1
            continue
        if t > CUTOFF_TS:
            STATS['dropped_after_cutoff'] += 1
            continue
        s = SESSIONS.get((r['cli'], r['sid'])) if r['sid'] else None
        base = dict(r['detail'])
        base['cli'] = r['cli']
        base['session_id'] = r['sid']
        base['cwd'] = s.cwd if s else None
        base['t_precise'] = iso_ms(t)
        if s and s.agent:
            base['map_method'] = s.map_method
            base['map_conf'] = s.map_conf
            if s.map_conflict:
                base['map_conflict'] = s.map_conflict
        else:
            base['map_method'] = None
            base['map_conf'] = None
            base['agent_hint'] = s.agent_hint if s else None
        if s and s.meta.get('originator'):
            base['originator'] = s.meta['originator']
        if r['raw'] is None:
            segs = [{'prefix': None, 'body_sha': None, 'body_len': r['nobody_len'], 'detail': {}}]
        else:
            segs = body_fields(r['raw'], r['cli'])
        for sg in segs:
            d = dict(base)
            d.update(sg['detail'])
            if d.get('envelope') is None:
                d['envelope'] = False
            rec = {
                'src': 'receipts',
                'type': 'received',
                't': iso(t),
                't_basis': r['t_basis'],
                'agent': s.agent if s else None,
                'sender': d.get('env_sender'),
                'path': 'dispatch' if d.get('envelope_kind') == 'dispatch-pointer' else None,
                'prefix': sg['prefix'],
                'body_sha': sg['body_sha'],
                'body_len': sg['body_len'],
                'detail': {k: d[k] for k in sorted(d)},
                'ref': r['ref'],
            }
            out.append(rec)
    # Rescued records: per-agent claude-config/<agent>/ dirs are deleted when agentmux tears a
    # team down. Records extracted from them before deletion are kept in RESCUE and merged only
    # for sessions whose source transcript no longer exists.
    have = {(r['detail']['cli'], r['detail']['session_id']) for r in out}
    for ln, r in jsonl(RESCUE):
        k = (r['detail'].get('cli'), r['detail'].get('session_id'))
        src = (r.get('ref') or '').rsplit(':', 1)[0]
        if k in have or os.path.exists(src):
            STATS['rescue_skipped_source_present'] += 1
            continue
        out.append(r)
        STATS['rescue_merged'] += 1
    out.sort(key=lambda x: (x['t'], x['detail']['t_precise'], x['agent'] or '', x['detail']['cli'],
                            x['detail']['session_id'] or '', x['ref'],
                            (x['detail'].get('segment') or [0])[0]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
        for rec in out:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=False) + '\n')
    os.replace(tmp, OUT)
    return out


def report(out):
    h = hashlib.sha1(open(OUT, 'rb').read()).hexdigest()
    print('wrote %s  records=%d  sha1=%s' % (OUT, len(out), h))
    print('cutoff', iso(CUTOFF_TS))
    by_cli = collections.Counter(r['detail']['cli'] for r in out)
    print('\n== by cli'); [print('  %-7s %d' % kv) for kv in sorted(by_cli.items())]
    print('\n== by cli/source')
    for kv in sorted(collections.Counter((r['detail']['cli'], r['detail']['source']) for r in out).items()):
        print('  %-30s %d' % ('/'.join(kv[0]), kv[1]))
    print('\n== by agent')
    for kv in sorted(collections.Counter((r['agent'] or '(null)', r['detail']['cli']) for r in out).items(),
                     key=lambda x: (-x[1], x[0])):
        print('  %-28s %-6s %d' % (kv[0][0], kv[0][1], kv[1]))
    print('\n== mapping confidence (records)')
    for kv in sorted(collections.Counter((r['detail']['cli'], str(r['detail']['map_conf'])) for r in out).items()):
        print('  %-20s %d' % ('/'.join(kv[0]), kv[1]))
    print('\n== mapping (sessions with >=1 emitted record)')
    seen = {(r['detail']['cli'], r['detail']['session_id']) for r in out}
    mc = collections.Counter()
    mm = collections.Counter()
    for k in seen:
        s = SESSIONS.get(k)
        mc[(k[0], str(s.map_conf if s else None))] += 1
        mm[str(s.map_method if s else None)] += 1
    for kv in sorted(mc.items()):
        print('  %-20s %d' % ('/'.join(kv[0]), kv[1]))
    print('  methods:')
    for kv in sorted(mm.items(), key=lambda x: -x[1]):
        print('    %-50s %d' % kv)
    print('\n== date coverage per cli (UTC dates with records)')
    days = collections.defaultdict(collections.Counter)
    for r in out:
        days[r['detail']['cli'] + '/' + r['detail']['source']][r['t'][:10]] += 1
    for k in sorted(days):
        ks = sorted(days[k])
        print('  %-24s %s .. %s  %s' % (k, ks[0], ks[-1], ' '.join('%s:%d' % (d[5:], days[k][d]) for d in ks)))
    print('\n== envelope')
    print('  ', sorted(collections.Counter((r['detail']['cli'], r['detail'].get('envelope_kind') or '-')
                                         for r in out).items()))
    print('\n== conflicts:', sum(1 for k in seen if SESSIONS.get(k) and SESSIONS[k].map_conflict))
    for k in sorted(seen, key=lambda x: (x[0], x[1] or '')):
        s = SESSIONS.get(k)
        if s and s.map_conflict:
            print('   ', k, s.agent, s.map_method, s.map_conf, s.map_conflict)
    print('\n== stats')
    for k in sorted(STATS):
        print('  %-34s %d' % (k, STATS[k]))


if __name__ == '__main__':
    report(build())
