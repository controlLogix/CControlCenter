#!/usr/bin/env bash
# Vendored third-party code: are these the bytes that were reviewed?
#
#   bash <(tr -d '\r' < dashboard/check_vendor.sh)
#
# WHAT THIS PROTECTS. dashboard/vendor and field/vendor exist because the
# dashboard and the sidecar have to install from a clone, offline: plant-side
# boxes where `sudo apt install` is somebody else's change request and outbound
# PyPI is often blocked. Committed dependencies make that true - and make the
# repo the place a supply-chain problem would live, since nothing re-downloads
# them and nothing re-checks them.
#
# So this checks OFFLINE properties only. The wheel sha256 in each README is
# provenance, not a gate: verifying it needs PyPI, and a check that only works
# where PyPI is reachable is useless on exactly the machines this policy is for.
#
#   1. Every vendored file matches MANIFEST.sha256, and the manifest lists every
#      file - so neither editing a file nor adding one passes quietly.
#   2. No compiled extension anywhere. "py3-none-any" is what makes one
#      committed copy correct on every platform; a .so would make it correct on
#      exactly one, silently, until someone ran it somewhere else.
#   3. Every vendored package has a licence file and a README row.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that

VENDORS='dashboard/vendor field/vendor'

# Two different questions, so two different file lists, and mixing them up is
# how a gate starts crying wolf:
#
#   - "are the bytes that will RUN the reviewed ones?" is about the working
#     tree, because that is what Python imports.
#   - "is anything unexpected COMMITTED?" is about the index, because a
#     developer's __pycache__ is not a supply-chain event and failing on it
#     would fail on every machine that has ever imported the vendored code.
#
# tracked_in() answers the second. Outside a git checkout - an archived tree, a
# release tarball - it falls back to the working tree and the checks still mean
# something, just more strictly.
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  tracked_in() { git ls-files -- "$1"; }
  TRACKED='tracked'
else
  tracked_in() { find "$1" -type f 2>/dev/null | sort; }
  TRACKED='present'
fi

# ── 1. no compiled extensions ────────────────────────────────────────────────
binaries=""
for dir in $VENDORS; do
  [ -d "$dir" ] || continue
  found=$(find "$dir" -type f \( -name '*.so' -o -name '*.so.*' -o -name '*.pyd' \
            -o -name '*.dll' -o -name '*.dylib' \) 2>/dev/null)
  [ -z "$found" ] || binaries="$binaries$found"$'\n'
done
if [ -z "$binaries" ]; then
  ok 'vendor: no compiled extensions; one committed copy is correct everywhere'
else
  bad 'vendor: compiled extensions found; these are correct on one platform only'
  printf '%s' "$binaries" | sed 's/^/          /'
fi

# Byte-compiled output is not source and must never be COMMITTED: it is a second
# copy of the code that no longer has to agree with the first. Locally generated
# .pyc files are ignored by .gitignore and are nobody's problem.
cached=""
for dir in $VENDORS; do
  [ -d "$dir" ] || continue
  found=$(tracked_in "$dir" | grep -E '(^|/)__pycache__/|\.pyc$' || true)
  [ -z "$found" ] || cached="$cached$found"$'\n'
done
if [ -z "$cached" ]; then
  ok "vendor: no byte-compiled output is $TRACKED"
else
  bad 'vendor: byte-compiled output is committed alongside the source'
  printf '%s' "$cached" | sed 's/^/          /'
fi

# ── 2. the manifest ──────────────────────────────────────────────────────────
for dir in $VENDORS; do
  manifest="$dir/MANIFEST.sha256"
  if [ ! -d "$dir" ]; then
    continue
  fi
  if [ ! -f "$manifest" ]; then
    # dashboard/vendor predates this policy and carries JS as well as Python;
    # say so rather than failing, so the check reports a real gap instead of
    # being switched off.
    echo "  SKIP  vendor: $dir has no MANIFEST.sha256 (not yet under the hash policy)"
    continue
  fi

  drifted="" missing=""
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    want="${line%% *}"
    rel="${line#*  }"
    file="$dir/$rel"
    if [ ! -f "$file" ]; then
      missing="$missing$rel"$'\n'
      continue
    fi
    got=$(sha256sum "$file" 2>/dev/null | cut -d' ' -f1)
    [ "$got" = "$want" ] || drifted="$drifted$rel"$'\n'
  done < "$manifest"

  if [ -n "$drifted" ] || [ -n "$missing" ]; then
    bad "vendor: $dir does not match its manifest"
    [ -z "$drifted" ] || { echo '          changed:'; printf '%s' "$drifted" | sed 's/^/            /'; }
    [ -z "$missing" ] || { echo '          missing:'; printf '%s' "$missing" | sed 's/^/            /'; }
  else
    ok "vendor: $dir matches its manifest"
  fi

  # An unlisted file is the interesting case: a manifest that only covers what
  # someone remembered to list would pass while a whole extra module sat beside
  # it. README.md and the manifest itself are the only exemptions.
  unlisted=""
  while IFS= read -r file; do
    rel="${file#"$dir"/}"
    case "$rel" in MANIFEST.sha256|README.md) continue ;; esac
    grep -qF "  $rel" "$manifest" || unlisted="$unlisted$rel"$'\n'
  done < <(tracked_in "$dir")
  if [ -z "$unlisted" ]; then
    ok "vendor: every $TRACKED file in $dir is in its manifest"
  else
    bad "vendor: $dir has $TRACKED files the manifest does not list"
    printf '%s' "$unlisted" | sed 's/^/          /'
  fi
done

# ── 3. licence and provenance ────────────────────────────────────────────────
for dir in $VENDORS; do
  [ -d "$dir" ] || continue
  if [ ! -f "$dir/README.md" ]; then
    bad "vendor: $dir has no README recording version, licence and origin"
    continue
  fi
  if grep -qiE 'licen[cs]e' "$dir/README.md" && grep -qE 'sha256' "$dir/README.md"; then
    ok "vendor: $dir records a licence and a pinned hash"
  else
    bad "vendor: $dir/README.md does not record both a licence and a sha256"
  fi
  licences=$(find "$dir" -maxdepth 2 -type f -iname '*licen[cs]e*' 2>/dev/null | wc -l)
  if [ "$licences" -gt 0 ]; then
    ok "vendor: $dir ships $licences licence file(s)"
  else
    bad "vendor: $dir ships no licence file; redistributing without one is not ours to do"
  fi
done

# ── 4. is the vendoring real? ────────────────────────────────────────────────
# Without this the whole directory is decorative: a machine with the package
# pip-installed would import the installed copy, every test would pass, and
# nobody would find out until a plant-side box with no PyPI ran it.
#
# So: strip site-packages from sys.path entirely, put field/vendor at the front,
# and require the import to work AND to have come from here.
if [ -d field/vendor/pycomm3 ]; then
  # -B: a check must not leave __pycache__ in the tree it is auditing.
  out=$(python3 -B -c '
import sys
sys.path = [p for p in sys.path if "site-packages" not in p and "dist-packages" not in p]
sys.path.insert(0, "field/vendor")
import pycomm3
from pycomm3 import LogixDriver, CIPDriver      # the two the sidecar needs
print(pycomm3.__version__, pycomm3.__file__)
' 2>&1)
  rc=$?
  case "$out" in
    *"field/vendor"*|*"field\\vendor"*)
      if [ "$rc" = 0 ]; then
        ok "vendor: pycomm3 imports with no site-packages (${out%% *})"
      else
        bad "vendor: pycomm3 import failed: $out"
      fi ;;
    *)
      bad "vendor: pycomm3 did not import from field/vendor; the vendoring is not what runs"
      printf '          %s\n' "$out" ;;
  esac
else
  bad 'vendor: field/vendor/pycomm3 is missing'
fi

finish
