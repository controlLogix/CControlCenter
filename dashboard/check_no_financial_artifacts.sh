#!/usr/bin/env bash
# No financial artifact is ever committed, because this repo is PUBLIC.
#
#   bash <(tr -d '\r' < dashboard/check_no_financial_artifacts.sh)
#
# WHY THIS EXISTS BEFORE THE FEATURE IT GUARDS. `gh repo view` says
# controlLogix/CControlCenter, isPrivate: false, and .bytedesk/task-management/
# is committed. Phase 5 adds a brokerage session: positions, balances, account
# numbers, order records, research packs. Every one of those is a thing that
# must never reach a public remote, and a push cannot be taken back - a deleted
# file stays in the history, and by then it has been cloned and indexed.
#
# So the boundary comes first. Same discipline as the write ticket before the
# write route: a guard added afterwards is a guard added after something is
# already doing it the old way.
#
# WHAT IS ACTUALLY CHECKED, and what is not. This is deliberately PRECISE
# rather than broad, because a gate that cries wolf stops being read - and this
# one has to still be trusted in a year:
#
#   * no tracked file under a financial path
#   * .gitignore pins those paths, so a future file lands ignored rather than
#     staged
#   * no tracked file NAMED as a financial record
#   * no account number that says it is one
#
# IT CANNOT CATCH a number that is an account number and never says so. Nine
# digits in a source file are indistinguishable from a port, a timestamp or an
# id, and grepping for them would fire on half the repo. That limit is stated
# rather than papered over: this check makes the careless case impossible, not
# the determined one.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that

if ! command -v git >/dev/null 2>&1 || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo 'SKIP financial artifacts: not in a git checkout; there is nothing to publish'
  echo 'passed 0, failed 0'
  exit 0
fi

# This file names every pattern it looks for, so it must exempt itself or it is
# its own first offender. Same reason check_field_writes.sh exempts itself.
SELF='dashboard/check_no_financial_artifacts.sh'
EXEMPT="$SELF|dashboard/test_no_financial_artifacts.sh"

# ── 1. is the repo actually public? ──────────────────────────────────────────
#
# Reported rather than assumed, and NOT a failure either way: a private repo is
# not licence to commit an account number, and gh may be unavailable or logged
# out. The point is that the reader knows which situation they are in.
if command -v gh >/dev/null 2>&1 &&
   visibility=$(gh repo view --json isPrivate -q .isPrivate 2>/dev/null); then
  if [ "$visibility" = "false" ]; then
    ok 'financial artifacts: the remote is PUBLIC, so this check is load-bearing'
  else
    ok 'financial artifacts: the remote is private (this check still applies)'
  fi
else
  echo 'SKIP financial artifacts: gh could not report visibility; assuming public'
fi

# ── 2. nothing tracked under a financial path ────────────────────────────────
# agentmux-broker/ is NOT listed: it holds the broker's SOURCE, and the plan
# runs pytest against it. Artifacts that land inside it are caught by the
# filename rules below and pinned by agentmux-broker/profile|captures. Listing
# the directory flagged the code this guard exists to protect - the same mistake
# the .gitignore pin made an hour earlier.
tracked_under=$(git ls-files -- \
  'investing/*' '*/investing/*' \
  'broker/*' '*/broker/*' \
  '*/research/sessions/*' 2>/dev/null | grep -vE "^($EXEMPT)$" || true)
if [ -z "$tracked_under" ]; then
  ok 'financial artifacts: no tracked file under an investing or broker path'
else
  bad 'financial artifacts: these are COMMITTED and would go to a public remote'
  printf '%s\n' "$tracked_under" | sed 's/^/          /'
fi

# ── 3. no tracked file named as a financial record ───────────────────────────
#
# Filenames, not content: precise, and they are what a brokerage integration
# actually produces.
named=$(git ls-files 2>/dev/null | grep -viE "^($EXEMPT)$" |
        grep -iE '(^|/)(broker-orders|positions|balances|holdings|portfolio|order-history|tax-lots)\.(json|jsonl|csv)$|(^|/)SUBMIT_DISABLED$' || true)
if [ -z "$named" ]; then
  ok 'financial artifacts: no tracked file is named as a position, order or balance record'
else
  bad 'financial artifacts: these filenames are brokerage records'
  printf '%s\n' "$named" | sed 's/^/          /'
fi

# ── 4. no account number that says it is one ─────────────────────────────────
#
# Anchored on the WORD, not on the digits. A bare nine-digit number is a port, a
# timestamp or an id far more often than it is an account, and grepping for the
# shape would fire on half the repo and be switched off within a week.
labelled=$(git grep -nIiE '\b(account|acct)[-_ ]?(number|num|no|id)?\b["'"'"']?\s*[:=]\s*["'"'"']?[A-Z]?[0-9]{8,}' \
             -- . ':!dashboard/check_no_financial_artifacts.sh' \
                  ':!dashboard/test_no_financial_artifacts.sh' 2>/dev/null || true)
if [ -z "$labelled" ]; then
  ok 'financial artifacts: no value labelled as an account number is committed'
else
  bad 'financial artifacts: a value labelled as an account number is committed'
  printf '%s\n' "$labelled" | sed 's/^/          /'
fi

# ── 5. the pins that keep it that way ────────────────────────────────────────
#
# A check that only looked at today's tree would pass the moment someone wrote a
# positions file and before anyone ran the gate again. The .gitignore entries
# are what make the next one land ignored instead of staged, so their ABSENCE
# is the thing worth failing on - exactly as check_line_endings.sh treats the
# eol pins.
missing=""
# agentmux-broker/ is deliberately NOT here: it holds the broker's SOURCE, and
# pinning the whole directory blocked the code this boundary exists to guard.
# Only the paths an artifact could land in are pinned.
for pin in 'investing/' 'broker/' 'research/sessions/'            'agentmux-broker/profile/' 'agentmux-broker/captures/'; do
  # ANCHORED to a whole line, so it matches the RULE and not a mention of the
  # path in a comment. The first version used grep -qF, and .gitignore's own
  # comment block names "$AGENTMUX_HOME/investing/" - so deleting the actual
  # rule still passed. Matching prose about the thing instead of the thing is
  # the same mistake as a grep that trips on a docstring.
  # CR-TOLERANT, because anchoring the match made it line-ending sensitive.
  # .gitignore is not pinned in .gitattributes, so under core.autocrlf it checks
  # out with trailing carriage returns and an exact whole-line match misses
  # every rule. This passed locally on LF and failed in the gate clone - which
  # is the fresh-Windows-clone case, and the one that matters.
  tr -d '\r' < .gitignore 2>/dev/null | grep -qxF "$pin" || missing="$missing$pin"$'\n'
done
if [ -z "$missing" ]; then
  ok '.gitignore pins every path a financial artifact would be written to'
else
  bad '.gitignore does not pin these, so the next artifact written there is staged'
  printf '%s' "$missing" | sed 's/^/          /'
fi

# ── 6. the destinations are outside the repo, in writing ─────────────────────
#
# The pins stop an artifact being committed. This is the other half: the code
# has to be pointed somewhere else to begin with, and that decision belongs in a
# document rather than in whoever-wrote-it's memory.
# The FILE, not a pattern any comment could satisfy. The first version grepped
# docs/*.md and .gitignore together - and .gitignore's own comment block names
# both destinations, so deleting the document entirely still passed. A check for
# a document has to check for the document.
BOUNDARY_DOC='docs/investing-boundary.md'
if [ -f "$BOUNDARY_DOC" ] &&
   grep -qi 'LOCALAPPDATA' "$BOUNDARY_DOC" 2>/dev/null &&
   grep -qi 'AGENTMUX_HOME' "$BOUNDARY_DOC" 2>/dev/null; then
  ok "financial artifacts: $BOUNDARY_DOC records where they DO go"
else
  bad "financial artifacts: $BOUNDARY_DOC is missing, or no longer names both destinations"
fi

finish
