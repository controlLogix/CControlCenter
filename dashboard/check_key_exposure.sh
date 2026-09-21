#!/usr/bin/env bash
# Report where an AWS_BEARER_TOKEN_BEDROCK is readable, and whether its file mode is
# meaningful. Prints fingerprints and modes only — never the key.
#
# An AUDIT tool, not a lookup. agentmux no longer reads Claude Code's settings.json for a
# key; that convenience is how one credential ended up copied into three files. The Claude
# paths are still listed here because the point is to see every place a key is readable —
# including ones this project must not touch.
#   bash <(tr -d '\r' < dashboard/check_key_exposure.sh)
#
# POSIX modes are MEANINGLESS on drvfs (/mnt/...), where everything reports 777 and NTFS
# ACLs actually govern. Reporting 777 there as an exposure would be crying wolf; missing
# a real 777 on the Linux filesystem would be worse. So the filesystem is checked too.
set -u
python3 - <<'PY'
import hashlib, json, os, pathlib, re, stat

def finger(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]

def describe(path):
    real = os.path.realpath(path)
    on_mnt = real.startswith("/mnt/")
    link = " -> " + real if os.path.islink(path) else ""
    mode = stat.S_IMODE(os.lstat(path).st_mode)
    if on_mnt:
        verdict = "mode not meaningful (drvfs; NTFS ACLs govern)"
    elif mode & 0o077:
        verdict = f"EXPOSED: mode {mode:o} allows group/other access"
    else:
        verdict = f"ok (mode {mode:o})"
    return link, verdict

home = pathlib.Path.home()
candidates = [home / ".claude-wsl" / "settings.json",
              home / ".claude" / "settings.json",
              home / ".agentmux" / "env",
              home / ".agentmux" / "auth.json"]

rows = []
for path in candidates:
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    key = None
    if path.suffix == ".json":
        try:
            key = (json.loads(text).get("env") or {}).get("AWS_BEARER_TOKEN_BEDROCK")
        except ValueError:
            key = None
    if not key:
        match = re.search(r"AWS_BEARER_TOKEN_BEDROCK=['\"]?([^'\"\n]+)", text)
        key = match.group(1) if match else None
    if not key:
        continue
    link, verdict = describe(path)
    rows.append((str(path) + link, finger(key), len(key), key[:4], verdict))

if not rows:
    print("  no AWS_BEARER_TOKEN_BEDROCK found anywhere")
else:
    for where, fp, length, prefix, verdict in rows:
        print(f"  {where}")
        print(f"      {prefix}... {length} chars  sha256:{fp}  {verdict}")
    print()
    unique = {r[1] for r in rows}
    print(f"  distinct keys: {len(unique)}"
          + ("  (one key, reused)" if len(unique) == 1 else "  (MULTIPLE keys)"))
PY
