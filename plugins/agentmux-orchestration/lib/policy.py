"""Pre-tool defense in depth. Never execute or evaluate tool command text.

This deliberately accepts a narrow mutation grammar. Runtime authorization and
checksums remain authoritative. This separate live-worker check has a race and
does not add live-worker enforcement to the dashboard mutation endpoint.
"""
import os
from pathlib import Path
import re
import shlex
import urllib.parse
from gateway import Refused, read, rows

NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
TASK = re.compile(r"(?:EP|TM|ADR|SP|CAP)-[0-9]{3,9}")


def protected(path):
    if not isinstance(path, str) or not path or "\0" in path:
        raise Refused("invalid mutation path")
    try:
        absolute = Path(path).expanduser().absolute()
        resolved = absolute.resolve()
    except (OSError, RuntimeError, ValueError):
        raise Refused("cannot resolve mutation path") from None
    targets = set()
    roots = [Path.cwd() / ".agentmux/agents", Path.cwd() / ".claude/agents",
             Path(os.environ.get("AGENTMUX_HOME", str(Path.home() / ".agentmux"))) / "agents",
             Path.home() / ".claude/agents"]
    for candidate in (absolute, resolved):
        parts = candidate.parts
        for index in range(len(parts) - 1):
            if parts[index] in (".agentmux", ".claude") and parts[index + 1] == "agents":
                tail = parts[index + 2:]
                if not tail:
                    targets.add("*")
                elif len(tail) == 1 and tail[0].endswith(".md"):
                    targets.add(tail[0][:-3])
        for root in roots:
            root = root.resolve()
            if candidate == root or candidate in root.parents:
                targets.add("*")
            elif candidate.parent == root and candidate.suffix == ".md":
                targets.add(candidate.stem)
    return targets


def protect_live(names):
    if not names:
        return
    for worker in rows(read("/api/agents"), "agents"):
        definition = worker.get("agentdef")
        if definition is None:
            continue
        if not isinstance(definition, str):
            raise Refused("dashboard worker definition is invalid")
        if "*" not in names and definition not in names:
            continue
        state = worker.get("state")
        if state in ("attached", "detached"):
            raise Refused("definition used by live worker " + str(worker.get("name", "unknown"))[:128])
        if state != "stale":
            raise Refused("cannot establish whether the matching worker is live")


def hire(args):
    if args.count("--json") > 1:
        raise Refused("hire accepts at most one --json output flag")
    args = [arg for arg in args if arg != "--json"]
    names = []
    other = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--name":
            i += 1
            if i >= len(args):
                raise Refused("hire needs exactly one literal --name")
            names.append(args[i])
        elif arg.startswith("--name="):
            names.append(arg[7:])
        else:
            other.append(arg)
        i += 1
    if len(names) != 1:
        raise Refused("hire needs exactly one literal --name")
    if len(other) != 1 or not TASK.fullmatch(other[0]) or not NAME.fullmatch(names[0]):
        raise Refused("hire refused: use one literal task ID and one literal name, with no overrides")
    task, name = other[0], names[0]
    data = read("/api/board/roster", {"id": task})
    if data.get("id") != task:
        raise Refused("hire refused: roster identity does not match the task")
    matches = [row for row in rows(data, "members") if row.get("agent_name") == name]
    if len(matches) != 1 or matches[0].get("status") != "approved":
        raise Refused("hire refused: recruit and approve " + name + " for " + task)


def shell(value):
    if not isinstance(value, dict):
        raise Refused("shell input must be an object")
    keys = [key for key in ("command", "cmd") if key in value]
    if len(keys) != 1 or not isinstance(value[keys[0]], str):
        raise Refused("shell input needs exactly one command string")
    command = value[keys[0]]
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        raise Refused("ambiguous shell quoting; use a direct literal command") from None
    decoded = urllib.parse.unquote(command)
    if re.search(r"/api/board/(hire|agentdef|agentdrop)(?:[/?\s\"']|$)", decoded):
        raise Refused("use coordination.py rather than direct HTTP mutations")
    mutations = [i for i, token in enumerate(tokens) if token in ("hire", "agentdef", "agentdrop")]
    # Literal reads cannot change a definition. Redirection/compound syntax is
    # deliberately excluded from this small read-only command set.
    if (tokens and Path(tokens[0]).name in ("cat", "head", "tail", "ls", "stat", "grep", "rg")
            and not any(token == "--pre" or token.startswith("--pre=") for token in tokens)
            and not any(char in command for char in ("$", "`", "\n", "\r"))
            and not any(token and all(char in ";&|<>()" for char in token) for token in tokens)):
        return
    names = set()
    for token in tokens:
        candidate = token
        if token.startswith("-"):
            if "=" in token:
                candidate = token.split("=", 1)[1]
            elif len(token) > 2 and token[:2] in ("-t", "-o", "-f", "-i"):
                candidate = token[2:]
            else:
                continue
        if candidate and not all(char in ";&|<>()" for char in candidate):
            names.update(protected(candidate))
    mutation_programs = {"rm", "mv", "cp", "install", "tee", "sed", "perl", "python", "python3"}
    dynamic_mutation = tokens and Path(tokens[0]).name in mutation_programs
    if mutations or names or dynamic_mutation:
        if any(char in command for char in ("$", "`", "\n", "\r")) or any(
                token and all(char in ";&|<>()" for char in token) for token in tokens):
            raise Refused("ambiguous shell mutation; use one direct literal command")
    if len(mutations) > 1:
        raise Refused("multiple mutations are not supported in one command")
    if mutations:
        index = mutations[0]
        prefix = tokens[:index]
        direct = prefix and Path(prefix[-1]).name in ("coordination.py", "agentmux", "agentmux.sh")
        installed = len(prefix) >= 2 and prefix[-1] == "coordination" and Path(prefix[-2]).name == "runtime.py"
        expected = 1 if direct else 2
        if not (direct or installed) or len(prefix) not in (expected, expected + 1):
            raise Refused("unsupported mutation command; use coordination.py directly")
        if len(prefix) == expected + 1 and not re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", Path(prefix[0]).name):
            raise Refused("unsupported command wrapper; use coordination.py directly")
        verb, args = tokens[index], tokens[index + 1:]
        if verb == "hire":
            hire(args)
        else:
            if len(args) < 2 or args[0] not in ("repo", "global") or not NAME.fullmatch(args[1]):
                raise Refused("definition writes need a writable scope and literal name")
            names.add(args[1])
    protect_live(names)


def edit(value):
    paths = []
    patches = []
    def collect(item):
        if isinstance(item, str):
            patches.append(item)
        elif isinstance(item, dict):
            for key in ("file_path", "path"):
                if key in item:
                    if not isinstance(item[key], str):
                        raise Refused("edit path must be a string")
                    paths.append(item[key])
            for key in ("patch", "input"):
                if key in item:
                    if not isinstance(item[key], str):
                        raise Refused("patch must be a string")
                    patches.append(item[key])
            if "edits" in item:
                if not isinstance(item["edits"], list):
                    raise Refused("edits must be a list")
                for child in item["edits"]:
                    collect(child)
        else:
            raise Refused("unsupported edit input")
    collect(value)
    for patch in patches:
        destinations = re.findall(r"^\*\*\* (?:Update File|Add File|Delete File|Move to): (.+)$", patch, re.M)
        if not destinations:
            raise Refused("unsupported patch format; provide explicit patch destinations")
        paths.extend(destinations)
    if not paths:
        raise Refused("edit needs an explicit destination")
    names = set()
    for path in paths:
        names.update(protected(path))
    protect_live(names)
