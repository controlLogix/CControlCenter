#!/usr/bin/env bash
# Does the financial-artifact guard actually catch anything?
#
#   bash <(tr -d '\r' < dashboard/test_no_financial_artifacts.sh)
#
# WHY THIS IS A SUITE OF ITS OWN. check_no_financial_artifacts.sh protects the
# one mistake in Phase 5 that cannot be undone: a push to a PUBLIC remote. A
# guard against that which silently always passed would be worse than no guard,
# because it would be counted as coverage - smoke.sh:181 is the recorded
# precedent in this repo for exactly that.
#
# check_test_failability.sh cannot prove this one. Its method is to run a suite
# against a commit where the bug was present, and there has never been a
# financial artifact in this repo - which is the whole point. So the proof is by
# CONSTRUCTION: plant each kind of violation in a throwaway clone and require
# the check to find it, then remove it and require the check to pass.
#
# The negative half matters as much as the positive. A check that fired on a
# clean tree would be switched off within a week, and then the real one goes
# through unnoticed.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that

if ! command -v git >/dev/null 2>&1; then
  echo 'SKIP financial guard: git is unavailable, so no fixture clone can be built'
  echo 'passed 0, failed 0'
  exit 0
fi

REPO="$PWD"
FIX="$(mktemp -d)" || exit 2
trap 'rm -rf "$FIX"' EXIT

# A fixture clone: the real check and the real .gitignore, over a tiny tree.
mkdir -p "$FIX/dashboard" "$FIX/docs"
cp dashboard/check_no_financial_artifacts.sh dashboard/testlib.sh "$FIX/dashboard/"
cp .gitignore "$FIX/.gitignore"
cp docs/investing-boundary.md "$FIX/docs/" 2>/dev/null || true
git -C "$FIX" init -q
git -C "$FIX" config user.email 'guard@example.invalid'
git -C "$FIX" config user.name 'Financial guard test'
git -C "$FIX" add -A >/dev/null 2>&1
git -C "$FIX" commit -qm base >/dev/null 2>&1

# gh must not answer inside the fixture - its visibility probe is about the REAL
# remote, and the fixture has none. Shadow ONLY gh, with a stub that declines:
# the first version of this restricted PATH instead and took git with it, so the
# check skipped entirely and every "catch" below was measured against a check
# that never ran. Two of them reported ok for that reason.
mkdir -p "$FIX/stub"
printf '#!/bin/sh\nexit 1\n' > "$FIX/stub/gh"
chmod +x "$FIX/stub/gh"
run_check() {
  (cd "$FIX" && PATH="$FIX/stub:$PATH" bash <(tr -d '\r' < dashboard/check_no_financial_artifacts.sh) 2>&1)
}

# `git add -f` throughout: .gitignore is one of the things under test, so the
# planted file has to get past it to prove the OTHER checks work. A violation
# that .gitignore already stopped would prove nothing about them.
plant() { mkdir -p "$FIX/$(dirname "$1")"; printf '%s\n' "$2" > "$FIX/$1"; git -C "$FIX" add -f "$1" >/dev/null 2>&1; }
unplant() { git -C "$FIX" rm -q -f --cached "$1" >/dev/null 2>&1; rm -f "$FIX/$1"; }

expect_caught() {  # $1 label, $2 needle the failure must contain
  local out; out="$(run_check)"
  if printf '%s' "$out" | grep -q '  FAIL' && printf '%s' "$out" | grep -qiF "$2"; then
    ok "caught: $1"
  else
    bad "MISSED: $1 (the guard did not fail, or did not say why)"
    printf '%s\n' "$out" | sed 's/^/          /'
  fi
}

# ── the clean tree must pass, or nothing below means anything ────────────────
clean_out="$(run_check)"
if printf '%s' "$clean_out" | grep -q 'SKIP financial artifacts: not in a git checkout'; then
  # A skipped check reports no failures, so every "caught" below would pass for
  # the wrong reason. That is exactly what the first version of this did.
  bad 'the guard SKIPPED in the fixture; nothing below would be measuring anything'
  printf '%s\n' "$clean_out" | sed 's/^/          /'
elif printf '%s' "$clean_out" | grep -q '  FAIL'; then
  bad 'the guard fails on a CLEAN tree, so every catch below is meaningless'
  printf '%s\n' "$clean_out" | sed 's/^/          /'
else
  ok 'a clean tree passes, so a failure below means something'
fi

# ── each kind of violation ───────────────────────────────────────────────────
plant 'investing/positions.json' '{"AAPL": 100}'
expect_caught 'a positions file committed under investing/' 'investing'
unplant 'investing/positions.json'

plant 'broker/orders.jsonl' '{"symbol":"AAPL","side":"buy"}'
expect_caught 'an order record committed under broker/' 'broker'
unplant 'broker/orders.jsonl'

plant 'docs/holdings.csv' 'symbol,qty'
expect_caught 'a holdings file anywhere in the tree, by its NAME' 'holdings.csv'
unplant 'docs/holdings.csv'

plant 'dashboard/settings_example.py' 'ACCOUNT_NUMBER = "Z12345678"'
expect_caught 'a value labelled as an account number' 'account'
unplant 'dashboard/settings_example.py'

plant 'SUBMIT_DISABLED' ''
expect_caught 'the kill-switch sentinel committed' 'SUBMIT_DISABLED'
unplant 'SUBMIT_DISABLED'

# ── the pins themselves ──────────────────────────────────────────────────────
cp "$FIX/.gitignore" "$FIX/.gitignore.bak"
grep -v '^investing/$' "$FIX/.gitignore.bak" > "$FIX/.gitignore"
git -C "$FIX" add -A >/dev/null 2>&1
expect_caught 'a .gitignore pin removed, so the next artifact would be staged' 'investing/'
mv "$FIX/.gitignore.bak" "$FIX/.gitignore"
git -C "$FIX" add -A >/dev/null 2>&1

rm -f "$FIX/docs/investing-boundary.md"
git -C "$FIX" add -A >/dev/null 2>&1
expect_caught 'the document saying where artifacts DO go, deleted' 'investing-boundary'
git -C "$FIX" checkout -q -- docs/investing-boundary.md 2>/dev/null || \
  cp "$REPO/docs/investing-boundary.md" "$FIX/docs/"
git -C "$FIX" add -A >/dev/null 2>&1

# ── and it must NOT fire on ordinary code ────────────────────────────────────
#
# The false-positive half. A bare nine-digit number is a port, a timestamp or an
# id far more often than an account, and a guard that flagged the shape would be
# switched off within a week - taking the real catch with it.
plant 'dashboard/ordinary.py' 'TIMEOUT_MS = 123456789
PORT = 44818
run_id = "987654321"
# the account team asked for this
counts = {"accounts": 12}'
clean_again="$(run_check)"
if printf '%s' "$clean_again" | grep -q '  FAIL'; then
  bad 'the guard fires on ordinary code with bare digits; it would be switched off'
  printf '%s\n' "$clean_again" | sed 's/^/          /'
else
  ok 'ordinary code with bare digits and the word "account" does not trip it'
fi
unplant 'dashboard/ordinary.py'

finish
