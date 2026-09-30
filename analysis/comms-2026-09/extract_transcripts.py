#!/usr/bin/env python3
"""Extract orchestrator-side messaging intents and delivery observations from
Claude Code transcripts (JSONL) into out/transcripts.jsonl.

Read-only, stdlib-only, deterministic. See README.md for the record schema.

Run in WSL (paths are WSL form):
    python3 extract_transcripts.py            # writes out/transcripts.jsonl

Determinism: records are sorted, keys are sorted, and every transcript entry whose
timestamp is after CUTOFF_UTC is ignored.  CUTOFF_UTC is the comms snapshot time
(/home/nick/agentmux-comms-snapshot/20260929-215601 = 2026-09-29 21:56:01 CDT), so
sessions that are still being written (this analysis session among them) produce the
same output on every run.
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
OUT_DIR = os.path.join(os.getcwd(), "out")
OUT_FILE = os.path.join(OUT_DIR, "transcripts.jsonl")

CUTOFF_UTC = "2026-09-30T02:56:01Z"          # snapshot 20260929-215601 CDT
SELF_MTIME_AFTER = datetime(2026, 9, 30, 2, 30, 0, tzinfo=timezone.utc)  # 2026-09-29 21:30 CDT
SELF_MARKER = b"comms-2026-09"

WIN_PROJECTS = "/mnt/c/Users/Nick/.claude/projects"
NAMED_DIRS = [
    "C--Dev-agentmux", "C--Dev", "C--Dev-workspace", "C--theWork-git",
    "C--Users-Nick", "C--Users-Nick-orca-workspaces-agentmux-agentmux",
]
WSL_PROJECTS = "/home/nick/.claude-wsl/projects"

VERBS = ("send", "ask", "key", "post", "unblock", "dispatch", "inbox")
PATH_OF_VERB = {"send": "send", "ask": "ask", "key": "key", "post": "post",
                "unblock": "unblock", "dispatch": "dispatch", "inbox": None,
                "clear-modals": "clear-modals"}

# Which flags take a value, per verb (from agentmux.sh usage + arg loops).
VALUE_FLAGS = {
    "send": set(),
    "ask": {"--timeout", "-t", "--quiet", "-q", "--lines", "-n"},
    "post": {"--kind", "--ref", "--from"},
    "key": set(),
    "unblock": set(),
    "inbox": set(),
    "dispatch": {"--cli"},
    "clear-modals": set(),
}
BOOL_FLAGS = {
    "send": {"--force"},
    "ask": {"--all", "--force"},
    "post": {"--strict"},
    "key": set(),
    "unblock": {"--dry-run", "--all"},
    "inbox": {"--clear"},
    "dispatch": {"--dry-run"},
    "clear-modals": {"--dry-run", "--all", "--force"},
}
NO_RECIPIENT = {"dispatch"}          # first positional is a task id, not an agent

# An agentmux invocation: optional path, agentmux[.cmd|.sh] or $AM, then a verb that
# is followed by whitespace/end/;/quote (so `tmux -L agentmux send-keys` never matches).
INVOKE_RE = re.compile(
    r"(?P<cmd>(?:[A-Za-z]:)?(?:[\w.~$\\/-]*[\\/])?agentmux(?:\.cmd|\.sh)?|\$\{?AM\}?)"
    r"[ \t]+(?P<verb>" + "|".join(VERBS) + r")(?=[ \t\r\n;|&)\"']|$)")
CLEAR_RE = re.compile(r"(?:[\w.~$\\/-]*[\\/])?clear-modals\.sh\b")

# Statement words that mean "this is text about agentmux, not a run of it".
NON_EXEC_WORDS = {
    "echo", "printf", "grep", "egrep", "rg", "sed", "awk", "cat", "less", "head", "tail",
    "write-output", "write-host", "select-string", "git", "cp", "mv", "chmod", "ls",
    "diff", "wc", "tr", "file", "stat", "sha1sum", "md5sum", "vim", "nano", "code",
    "tee", "print", "rm", "shellcheck", "dos2unix", "touch", "find", "xxd", "od",
}
WRAPPER_WORDS = {"timeout", "env", "sudo", "setsid", "nohup", "exec", "time", "command",
                 "bash", "sh", "call", "&", "cmd", "cmd.exe", "wsl", "wsl.exe", "then",
                 "do", "else", "if", "while", "until", "!", "{", "(", "out=$(", "$("}

SKIP_RESULT_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "NotebookEdit",
                     "TodoWrite", "StructuredOutput"}

OBS_RE = re.compile(
    r"Pasted Content|not submitted|didn.?t submit|press(?:ed)? Enter|extra Enter|"
    r"stuck in (?:the )?(?:input|composer)|swallowed|never (?:got|received|arrived)|"
    r"\bmodal|Update available|\btrust|--force|dead.?letter|deferred|gave up|"
    r"wrong pane|identity", re.I)
MENTION_RE = re.compile(r"agentmux|\bpanes?\b|\bagents?\b", re.I)
PREFILTER = re.compile(
    rb"agentmux|clear-modals|Pasted Content|not submitted|didn.{0,3}t submit|"
    rb"press(?:ed)? Enter|extra Enter|stuck in|swallowed|never (?:got|received|arrived)|"
    rb"modal|Update available|trust|--force|dead.?letter|deferred|gave up|wrong pane|"
    rb"identity", re.I)
TOOL_USE_ID_RE = re.compile(rb'"type":"tool_use","id":"(toolu_[A-Za-z0-9_]+)","name":"([^"]+)"')
RESULT_ID_RE = re.compile(rb'"tool_use_id":"(toolu_[A-Za-z0-9_]+)"')

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")
PASTE_RE = re.compile(r"\x1b\[20[01]~|\[20[01]~")
ENVELOPE_RE = re.compile(r"^\s*\[agentmux\] from (\S+) \(([^)]*)\) ref (\S+):\s?")
WS_RE = re.compile(r"\s+")
EXIT_RE = re.compile(r"^Exit code (-?\d+)")
RC_RE = re.compile(r"\b(?:rc|RC|exit|EXIT)[ _]?(?:\w*)=(-?\d+)")


# ----------------------------------------------------------------- normalization

def normalize(body):
    """Return (normalized_text, envelope_dict_or_None)."""
    s = ANSI_RE.sub("", body)
    s = PASTE_RE.sub("", s)
    env = None
    m = ENVELOPE_RE.match(s)
    if m:
        env = {"from": m.group(1), "kind": m.group(2), "ref": m.group(3)}
        s = s[m.end():]
    s = WS_RE.sub(" ", s).strip()
    return s, env


def body_fields(body):
    if body is None:
        return "", None, 0, None
    norm, env = normalize(body)
    sha = hashlib.sha1(norm.encode("utf-8")).hexdigest() if norm else None
    return norm[:80], sha, len(body), env


def to_utc(ts):
    if not ts or not isinstance(ts, str):
        return None
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


# ----------------------------------------------------------------- shell scanning

HEREDOC_RE = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][\w-]*)\1")


def quote_state_map(cmd):
    """For each char index, the quote state ('', "'", '"') of an outer shell scan, with
    heredoc bodies scanned as their own region.  Also returns heredoc body spans with
    the command line that opened them."""
    n = len(cmd)
    state = [""] * (n + 1)
    heredocs = []          # (body_start, body_end, opener_line_text)
    i = 0
    q = ""
    pending = []           # heredoc delimiters opened on the current line
    line_start = 0
    while i < n:
        c = cmd[i]
        state[i] = q
        if q == "":
            if c == "\\" and i + 1 < n:
                state[i + 1] = q
                i += 2
                continue
            if c == "'":
                q = "'"
            elif c == '"':
                q = '"'
            elif c == "<" and cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
                m = HEREDOC_RE.match(cmd, i)
                if m:
                    pending.append(m.group(2))
                    for k in range(i, m.end()):
                        state[k] = ""
                    i = m.end()
                    continue
            elif c == "#" and (i == 0 or cmd[i - 1] in " \t\n;"):
                # comment to end of line
                j = cmd.find("\n", i)
                j = n if j < 0 else j
                for k in range(i, j):
                    state[k] = "#"
                i = j
                continue
            elif c == "\n":
                opener = cmd[line_start:i]
                line_start = i + 1
                if pending:
                    # consume heredoc bodies in order; each is its own scan region
                    pos = i + 1
                    new = []
                    for delim in pending:
                        body_start = pos
                        body_end = n
                        while pos < n:
                            e = cmd.find("\n", pos)
                            e = n if e < 0 else e
                            if cmd[pos:e].strip() == delim:
                                body_end = pos
                                pos = min(e + 1, n)
                                break
                            pos = e + 1
                        else:
                            body_end = n
                        new.append((body_start, min(body_end, n), opener))
                    pending = []
                    for k in range(i, min(pos, n)):
                        state[k] = ""
                    for (bs, be, op) in new:
                        sub_state, sub_hd = quote_state_map(cmd[bs:be])
                        for k in range(bs, be):
                            state[k] = sub_state[k - bs]
                        heredocs.append((bs, be, op))
                        for (sbs, sbe, sop) in sub_hd:
                            heredocs.append((bs + sbs, bs + sbe, sop))
                    i = max(pos, i + 1)
                    line_start = i
                    continue
        elif q == "'":
            if c == "'":
                q = ""
        elif q == '"':
            if c == "\\" and i + 1 < n:
                state[i + 1] = q
                i += 2
                continue
            if c == '"':
                q = ""
        i += 1
    state[n] = q
    return state, heredocs


def extract_nested(cmd, pos, q):
    """Given an invocation starting at pos inside an outer quoted string of type q,
    return the unescaped inner text up to the close of that outer string."""
    out = []
    i = pos
    n = len(cmd)
    if q == '"':
        while i < n:
            c = cmd[i]
            if c == "\\" and i + 1 < n and cmd[i + 1] in '"\\$`':
                out.append(cmd[i + 1])
                i += 2
                continue
            if c == "\\" and i + 1 < n and cmd[i + 1] == "\n":
                i += 2
                continue
            if c == '"':
                break
            out.append(c)
            i += 1
    else:
        while i < n:
            if cmd.startswith("'\\''", i):
                out.append("'")
                i += 4
                continue
            if cmd.startswith("'\"'\"'", i):
                out.append("'")
                i += 5
                continue
            if cmd[i] == "'":
                break
            out.append(cmd[i])
            i += 1
    return "".join(out)


STOP_CHARS = set(";&|<>\n`")


def lex_words(s, pos=0, powershell=False):
    """Lex shell words from s[pos:] until an unquoted statement terminator.
    Returns (words, has_expansion, end_index)."""
    words = []
    has_exp = False
    n = len(s)
    i = pos
    depth = 0
    while True:
        while i < n and s[i] in " \t\r":
            i += 1
        if i < n and s[i] == "\\" and i + 1 < n and s[i + 1] == "\n":
            i += 2
            continue
        if powershell and i < n and s[i] == "`" and i + 1 < n and s[i + 1] in "\r\n":
            i += 2
            continue
        if i >= n:
            break
        c = s[i]
        if c in STOP_CHARS and not (powershell and c == "`"):
            break
        if c == ")" and depth == 0:
            break
        if c == "#":
            break
        w = []
        quoted = False
        while i < n:
            c = s[i]
            if c in " \t\r":
                break
            if c in STOP_CHARS and not (powershell and c == "`"):
                break
            if c == ")" and depth == 0:
                break
            if c == "'":
                j = s.find("'", i + 1)
                j = n if j < 0 else j
                w.append(s[i + 1:j])
                quoted = True
                i = j + 1
                if powershell and i < n and s[i] == "'":
                    w.append("'")        # PowerShell '' inside single quotes
                continue
            if c == '"':
                i += 1
                quoted = True
                while i < n and s[i] != '"':
                    if s[i] == "\\" and not powershell and i + 1 < n and s[i + 1] in '"\\$`\n':
                        if s[i + 1] != "\n":
                            w.append(s[i + 1])
                        i += 2
                        continue
                    if powershell and s[i] == "`" and i + 1 < n:
                        w.append(s[i + 1])
                        i += 2
                        continue
                    if s[i] == "$":
                        has_exp = True
                        if s.startswith("$(", i):
                            k = _match_paren(s, i + 1)
                            w.append(s[i:k])
                            i = k
                            continue
                    w.append(s[i])
                    i += 1
                i += 1
                continue
            if c == "\\" and not powershell and i + 1 < n:
                if s[i + 1] == "\n":
                    i += 2
                    continue
                w.append(s[i + 1])
                i += 2
                continue
            if c == "$":
                has_exp = True
                if s.startswith("$(", i):
                    k = _match_paren(s, i + 1)
                    w.append(s[i:k])
                    i = k
                    continue
            if c == "(":
                depth += 1
            w.append(c)
            i += 1
        word = "".join(w)
        # a bare fd number glued to a redirect (2>&1) is not an argument
        if not quoted and word.isdigit() and i < n and s[i] in "<>":
            break
        if word or quoted:
            words.append(word)
    return words, has_exp, i


def _match_paren(s, i):
    """s[i] == '('; return index just past the matching ')'."""
    depth = 0
    n = len(s)
    q = ""
    while i < n:
        c = s[i]
        if q:
            if c == q:
                q = ""
            elif c == "\\" and q == '"':
                i += 1
        elif c in "'\"":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


SEG_SPLIT_RE = re.compile(r"(?:;|&&|\|\||\||\(|\{|\bdo\b|\bthen\b|\belse\b|\$\(|`|\n)")


def segment_prefix(cmd, pos):
    """Text of the current statement before pos (same line, after the last separator)."""
    ls = cmd.rfind("\n", 0, pos) + 1
    line = cmd[ls:pos]
    parts = SEG_SPLIT_RE.split(line)
    return parts[-1] if parts else ""


def statement_words(prefix):
    return re.findall(r"[^\s]+", prefix)


def first_command_word(prefix):
    """First non-assignment, non-wrapper word of the statement prefix (lowercased)."""
    words = statement_words(prefix)
    skip_next = False
    for w in words:
        if skip_next:
            skip_next = False
            continue
        lw = w.lower().strip("\"'")
        if re.match(r"^[A-Za-z_]\w*=", w):
            continue
        if lw in ("timeout",):
            skip_next = True
            continue
        if re.match(r"^-?\d+(\.\d+)?[smh]?$", lw):
            continue
        if lw in WRAPPER_WORDS or lw.startswith("-"):
            continue
        base = re.split(r"[\\/]", lw)[-1]
        return base
    return ""


def parse_args(verb, words):
    """Split argv after the verb into recipient, flags, body words."""
    vflags = VALUE_FLAGS.get(verb, set())
    bflags = BOOL_FLAGS.get(verb, set())
    flags = []
    positional = []
    i = 0
    while i < len(words):
        w = words[i]
        if w in vflags and i + 1 < len(words):
            flags.append([w, words[i + 1]])
            i += 2
            continue
        m = re.match(r"^(--[a-z-]+)=(.*)$", w)
        if m and m.group(1) in vflags:
            flags.append([m.group(1), m.group(2)])
            i += 1
            continue
        if w in bflags:
            flags.append([w, True])
            i += 1
            continue
        positional.append(w)
        i += 1
    recipient = None
    body_words = positional
    if verb not in NO_RECIPIENT and verb != "unblock" and positional:
        recipient = positional[0]
        body_words = positional[1:]
    elif verb == "unblock" and positional:
        recipient = positional[0]
        body_words = positional[1:]
    return recipient, flags, body_words, positional


def find_invocations(cmd, powershell):
    """Yield dicts describing each agentmux / clear-modals invocation in cmd."""
    state, heredocs = quote_state_map(cmd)
    out = []

    def in_file_heredoc(pos):
        inner = [h for h in heredocs if h[0] <= pos < h[1]]
        inner.sort(key=lambda h: (h[1] - h[0], h[0]))
        for bs, be, opener in inner[:1]:
            if True:
                fw = first_command_word(opener)
                if fw in ("cat", "tee") or re.search(r"(?:^|\s)(?:cat|tee)\b[^|]*>", opener) \
                        or re.search(r">\s*\S+\s*<<", opener):
                    return True, opener
                return False, opener
        return False, None

    matches = []
    for m in INVOKE_RE.finditer(cmd):
        matches.append((m.start(), m.end(), m.group("verb"), m.group("cmd")))
    for m in CLEAR_RE.finditer(cmd):
        matches.append((m.start(), m.end(), "clear-modals", m.group(0)))
    matches.sort()
    for start, end, verb, cmdword in matches:
        q = state[start]
        if q == "#":
            continue
        filehd, opener = in_file_heredoc(start)
        if filehd:
            continue
        prefix = segment_prefix(cmd, start)
        # "-L agentmux" is tmux's socket name, not the CLI
        if re.search(r"-L\s*$", prefix):
            continue
        fw = first_command_word(prefix)
        if fw in NON_EXEC_WORDS:
            continue
        if verb == "clear-modals":
            pw = statement_words(prefix)
            if pw and pw[-1] in ("-n",):          # bash -n (syntax check only)
                continue
            if fw not in ("", "bash", "sh") and not fw.endswith("clear-modals.sh"):
                continue
        if q in ("'", '"'):
            inner = extract_nested(cmd, end, q)
            words, has_exp, _ = lex_words(inner, 0, powershell=False)
            nested = q
        else:
            words, has_exp, _ = lex_words(cmd, end, powershell=powershell)
            nested = ""
        env = {}
        for a in re.findall(r"(?:^|\s)([A-Za-z_]\w*)=(\S+)", prefix):
            env[a[0]] = a[1].strip("\"'")
        out.append({"pos": start, "verb": verb, "cmdword": cmdword, "words": words,
                    "has_exp": has_exp, "nested": nested, "env": env,
                    "via_heredoc": opener is not None})
    return out


# ----------------------------------------------------------------- transcript walk

def text_of_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text" and isinstance(b.get("text"), str):
                    parts.append(b["text"])
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts)
    return ""


def excerpt_around(text, m, width=400):
    start = max(0, m.start() - 120)
    s = text[start:start + width * 2]
    s = WS_RE.sub(" ", ANSI_RE.sub("", s)).strip()
    return s[:width]


def file_list():
    files = []
    roots = []
    if os.path.isdir(WIN_PROJECTS):
        for d in sorted(os.listdir(WIN_PROJECTS)):
            full = os.path.join(WIN_PROJECTS, d)
            if not os.path.isdir(full):
                continue
            if d in NAMED_DIRS or d.startswith("-"):
                roots.append(full)
    if os.path.isdir(WSL_PROJECTS):
        for d in sorted(os.listdir(WSL_PROJECTS)):
            full = os.path.join(WSL_PROJECTS, d)
            if os.path.isdir(full):
                roots.append(full)
    for r in roots:
        for dp, dn, fn in os.walk(r):
            dn.sort()
            for f in sorted(fn):
                if f.endswith(".jsonl"):
                    files.append((os.path.join(dp, f), r))
    return sorted(set(files)), roots


def process_file(path, root, records, stats):
    tool_names = {}
    pending = {}           # tool_use_id -> list of intent records
    self_marker = False
    last_intent = None
    project = os.path.basename(root)
    projects_home = os.path.dirname(root)
    is_sub = "/subagents/" in path
    with open(path, "rb") as fh:
        for lineno, raw in enumerate(fh, 1):
            if not self_marker and SELF_MARKER in raw:
                self_marker = True
            if b'"tool_use"' in raw:
                for tid, name in TOOL_USE_ID_RE.findall(raw):
                    tool_names[tid.decode()] = name.decode()
            want = PREFILTER.search(raw) is not None
            if not want and pending and b"tool_use_id" in raw:
                for tid in RESULT_ID_RE.findall(raw):
                    if tid.decode() in pending:
                        want = True
                        break
            if not want:
                continue
            try:
                e = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                stats["bad_json"] += 1
                continue
            if not isinstance(e, dict):
                continue
            ts = e.get("timestamp")
            t = to_utc(ts)
            if t is not None and t > CUTOFF_UTC:
                stats["after_cutoff"] += 1
                continue
            msg = e.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            ref = "%s:%d" % (path, lineno)
            base_detail = {"session_id": e.get("sessionId"), "subagent": is_sub,
                           "sidechain": bool(e.get("isSidechain")), "project": project, "projects_home": projects_home,
                           "ts_raw": ts}
            blocks = content if isinstance(content, list) else (
                [{"type": "text", "text": content}] if isinstance(content, str) else [])
            for bi, b in enumerate(blocks):
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "tool_use" and role == "assistant":
                    name = b.get("name")
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    cmd = inp.get("command")
                    if name not in ("Bash", "PowerShell") or not isinstance(cmd, str):
                        continue
                    invs = find_invocations(cmd, powershell=(name == "PowerShell"))
                    if not invs:
                        continue
                    home = None
                    hm = re.search(r"AGENTMUX_HOME=([^\s;\"']+)", cmd)
                    if hm:
                        home = hm.group(1)
                    for k, inv in enumerate(invs):
                        verb = inv["verb"]
                        recipient, flags, body_words, positional = parse_args(verb, inv["words"])
                        body = " ".join(body_words) if body_words else None
                        if verb == "dispatch":
                            body = None
                        prefix, sha, blen, env_hdr = body_fields(body)
                        sender = None
                        for f in flags:
                            if f[0] == "--from":
                                sender = f[1]
                        if sender is None and "AGENTMUX_AGENT" in inv["env"]:
                            sender = inv["env"]["AGENTMUX_AGENT"]
                        det = dict(base_detail)
                        det.update({
                            "tool": name, "tool_use_id": b.get("id"),
                            "verb": verb, "argv": [inv["cmdword"], verb] + inv["words"],
                            "flags": flags, "force": any(f[0] == "--force" for f in flags),
                            "positional": positional,
                            "body_has_expansion": inv["has_exp"],
                            "recipient_unexpanded": bool(recipient and "$" in recipient),
                            "nested_in_quote": inv["nested"] or None,
                            "in_heredoc": inv["via_heredoc"],
                            "env_prefix": inv["env"] or None,
                            "agentmux_home": home,
                            "test_home": bool(home),
                            "invocation_index": k, "invocations_in_command": len(invs),
                            "description": inp.get("description"),
                            "result": None,
                        })
                        if verb == "dispatch" and positional:
                            det["task_id"] = positional[0]
                        if env_hdr:
                            det["envelope"] = env_hdr
                        rec = {"src": "transcripts", "type": "intent", "t": t,
                               "t_basis": "utc" if t else "unknown",
                               "agent": recipient, "sender": sender,
                               "path": PATH_OF_VERB.get(verb),
                               "prefix": prefix, "body_sha": sha, "body_len": blen,
                               "detail": det, "ref": ref, "_k": (lineno, bi, k)}
                        records.append(rec)
                        pending.setdefault(b.get("id"), []).append(rec)
                        last_intent = rec
                        stats["intent"] += 1
                elif bt == "tool_result":
                    tid = b.get("tool_use_id")
                    rtext = text_of_content(b.get("content"))
                    if tid in pending:
                        tur = e.get("toolUseResult") if isinstance(e.get("toolUseResult"), dict) else {}
                        is_err = bool(b.get("is_error"))
                        em = EXIT_RE.match(rtext or "")
                        exit_code = int(em.group(1)) if em else (None if is_err else 0)
                        kind = "ok"
                        if rtext.startswith("The user doesn't want to proceed") or \
                                "tool use was rejected" in rtext[:300]:
                            kind = "rejected"
                        elif tur.get("interrupted"):
                            kind = "interrupted"
                        elif is_err:
                            kind = "error"
                        res = {"is_error": is_err, "exit_code": exit_code,
                               "exit_code_basis": "Exit code line" if em else "is_error flag",
                               "kind": kind,
                               "output_head": rtext[:300],
                               "stderr_head": (tur.get("stderr") or "")[:300] or None,
                               "rc_echoes": RC_RE.findall(rtext)[:8],
                               "result_ref": ref, "result_t": t}
                        for rec in pending.pop(tid):
                            rec["detail"]["result"] = res
                    src_tool = tool_names.get(tid)
                    if src_tool in SKIP_RESULT_TOOLS:
                        continue
                    maybe_obs(records, stats, rtext, "tool_result", src_tool, t, ref,
                              base_detail, last_intent, (lineno, bi, 0))
                elif bt in ("text", "thinking"):
                    txt = b.get("text") if bt == "text" else b.get("thinking")
                    if not isinstance(txt, str):
                        continue
                    speaker = "assistant" if role == "assistant" else "user"
                    if speaker == "user" and (e.get("isMeta") or txt.lstrip().startswith("<")):
                        speaker = "user-meta"
                    maybe_obs(records, stats, txt, speaker + ("-thinking" if bt == "thinking" else ""),
                              None, t, ref, base_detail, last_intent, (lineno, bi, 0))
    return self_marker


def maybe_obs(records, stats, text, kind, src_tool, t, ref, base_detail, last_intent, key):
    if not text:
        return
    m = OBS_RE.search(text)
    if not m:
        return
    if not MENTION_RE.search(text):
        return
    kws = sorted({x.group(0).lower() for x in OBS_RE.finditer(text)})
    ex = excerpt_around(text, m)
    det = dict(base_detail)
    det.update({"kind": kind, "result_of_tool": src_tool, "keywords": kws,
                "excerpt": ex, "text_len": len(text),
                "code_like": bool(re.search(r"^\s*\d+[\t→]|\bdef \w+\(|\(\)\s*\{|^\s*case .*\bin\b",
                                            text[:4000], re.M)),
                "last_intent_agent": last_intent["agent"] if last_intent else None,
                "last_intent_ref": last_intent["ref"] if last_intent else None})
    norm, _ = normalize(ex)
    records.append({"src": "transcripts", "type": "observation", "t": t,
                    "t_basis": "utc" if t else "unknown", "agent": None, "sender": None,
                    "path": None, "prefix": norm[:80], "body_sha": None,
                    "body_len": len(text), "detail": det, "ref": ref, "_k": key})
    stats["observation"] += 1


def session_key(path):
    """projects-dir/session-uuid for a main transcript or any file under its folder."""
    parts = path.split("/")
    for i, seg in enumerate(parts):
        if seg == "projects" and i + 2 < len(parts):
            return parts[i + 1] + "/" + re.sub(r"\.jsonl$", "", parts[i + 2])
    return path


def main():
    files, roots = file_list()
    records = []
    stats = {"intent": 0, "observation": 0, "bad_json": 0, "after_cutoff": 0}
    self_files = []
    for p, root in files:
        start = len(records)
        marker = process_file(p, root, records, stats)
        try:
            mt = datetime.fromtimestamp(os.stat(p).st_mtime, tz=timezone.utc)
        except OSError:
            mt = None
        is_self = bool(marker and mt and mt > SELF_MTIME_AFTER)
        if is_self:
            self_files.append(p)
        for r in records[start:]:
            r["detail"]["self_session"] = is_self
            r["detail"]["self_session_basis"] = "mtime+marker" if is_self else None
            r["_f"] = p
    # A subagent file of the analysis session may have stopped being written before
    # 21:30 CDT; it still belongs to that session, so flag the whole session tree.
    self_keys = {session_key(p) for p in self_files}
    for r in records:
        if not r["detail"]["self_session"] and session_key(r["_f"]) in self_keys:
            r["detail"]["self_session"] = True
            r["detail"]["self_session_basis"] = "same session tree"
    # agents mentioned in observations: names seen as intent recipients
    names = sorted({r["agent"] for r in records if r["type"] == "intent" and r["agent"]
                    and "$" not in r["agent"] and len(r["agent"]) >= 3
                    and re.match(r"^[\w.-]+$", r["agent"])})
    name_re = re.compile(r"(?<![\w-])(" + "|".join(re.escape(x) for x in
                                                   sorted(names, key=lambda s: (-len(s), s)))
                         + r")(?![\w-])") if names else None
    for r in records:
        if r["type"] == "observation" and name_re:
            found = sorted(set(name_re.findall(r["detail"]["excerpt"])))
            r["detail"]["mentioned_agents"] = found
            r["agent"] = found[0] if len(found) == 1 else None
    records.sort(key=lambda r: (r["t"] or "", r["_f"], r["_k"], r["type"]))
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = OUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fo:
        for r in records:
            r.pop("_k", None)
            r.pop("_f", None)
            fo.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, OUT_FILE)
    ts = [r["t"] for r in records if r["t"]]
    print("files scanned:", len(files), "roots:", len(roots))
    print("stats:", json.dumps(stats, sort_keys=True))
    print("self_session files:", len(self_files))
    for p in self_files:
        print("  ", p)
    if ts:
        print("t range:", min(ts), "..", max(ts))
    print("wrote", OUT_FILE, len(records), "records")


if __name__ == "__main__":
    main()
