#!/usr/bin/env bash
# Files that are PARSED rather than read must check out with LF.
#
#   bash <(tr -d '\r' < dashboard/check_line_endings.sh)
#
# WHY THIS EXISTS. Two bugs, one cause, both of which look like something else.
#
#   1. bash cannot source a CRLF file. `. dashboard/testlib.sh` fails with a
#      carriage-return "command not found" on every line and every helper goes
#      missing - so a suite dies at line 1 with exit 127 and no assertion output.
#
#   2. The task-management plugin parses its documents by splitting on the
#      frontmatter fence. CRLF means the fence stops matching, every document
#      parses to an EMPTY object, and `tm board` renders "undefined undefined".
#      2 of 2 epics and 19 of 22 tasks went unreadable this way on 2026-09-25 -
#      while the files themselves were perfectly intact. That is what makes it
#      dangerous: the obvious reading is "the store is corrupt", and it is not.
#
# core.autocrlf is true on this checkout, so a plain `git clone`, a branch switch
# or a `git checkout -- .` is enough to produce either. .gitattributes pins both
# sets to LF, and the sources are CRLF-tolerant now - this is the check that says
# so out loud rather than trusting both to stay correct.
#
# It reads the WORKING TREE, not the index, because the working tree is what bash
# and the plugin actually open.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that

# git ls-files, so this is about what a fresh clone gets rather than whatever
# scratch files happen to be lying around.
if ! command -v git >/dev/null 2>&1 || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo 'SKIP line-endings: not in a git checkout'
  echo 'passed 0, failed 0'
  exit 0
fi

crlf_in() {
  # Every tracked path matching $1 whose working-tree copy contains a CR, with
  # WHICH KIND and where. The two are different problems with different fixes:
  #
  #   CRLF endings     .gitattributes `text eol=lf` prevents them; a checkout on
  #                    a machine with core.autocrlf is the usual cause
  #   a lone CR        `eol=lf` does NOT touch it. It normalises line ENDINGS,
  #                    and a CR not followed by LF is not one - it is a content
  #                    bug, it survives every checkout, and it comes straight
  #                    back unless the source is fixed
  #
  # Reported as "CRLF found" once, on a file that had a single stray CR in the
  # middle of one line where a literal backslash-r had been mangled in an edit.
  # The message sent the reader looking for the wrong thing entirely.
  git ls-files -z -- "$1" | while IFS= read -r -d '' f; do
    [ -f "$f" ] || continue
    LC_ALL=C grep -qU $'\r' "$f" 2>/dev/null || continue
    python3 - "$f" <<'PY'
import sys
data = open(sys.argv[1], 'rb').read()
crlf = data.count(b'\r\n')
lone = data.count(b'\r') - crlf
bits = []
if crlf:
    bits.append(f'{crlf} CRLF line ending(s)')
if lone:
    where = [str(i) for i, line in enumerate(data.split(b'\n'), 1)
             if b'\r' in line.rstrip(b'\r')][:4]
    bits.append(f'{lone} lone CR(s) mid-line, line(s) ' + (', '.join(where) or '?'))
print(f"{sys.argv[1]}  -  " + '; '.join(bits))
PY
  done
}

report() {
  local label="$1" pattern="$2" why="$3" offenders
  offenders="$(crlf_in "$pattern")"
  if [ -z "$offenders" ]; then
    ok "$label: every tracked file is LF"
  else
    bad "$label: carriage returns found - $why"
    printf '%s\n' "$offenders" | sed 's/^/          /'
    # Only the advice that applies. The two causes need different fixes, and
    # printing the wrong one is how a message stops being read at all.
    case "$offenders" in
      *'lone CR'*)
        echo '          a lone CR is NOT prevented by the eol=lf pin - it is a' >&2
        echo '          content bug that survives every checkout; fix the source' >&2 ;;
      *)
        echo '          re-check out with the eol=lf pin in place' >&2 ;;
    esac
  fi
}

report 'shell scripts' '*.sh' \
  'bash cannot source a CRLF file; helpers vanish and the suite exits 127'
report 'the task store' '.bytedesk/task-management/*' \
  'the frontmatter fence stops matching and every document parses empty'

# The pins that keep it that way. A check that only looked at today's bytes would
# pass the moment someone removed the attribute and before anyone re-checked out.
if [ -f .gitattributes ]; then
  if grep -qE '^\*\.sh[[:space:]]+text[[:space:]]+eol=lf' .gitattributes; then
    ok '.gitattributes pins *.sh to LF'
  else
    bad '.gitattributes does not pin *.sh to LF; the next checkout reintroduces CRLF'
  fi
  if grep -qE '^\.bytedesk/task-management/\*\*[[:space:]]+text[[:space:]]+eol=lf' .gitattributes; then
    ok '.gitattributes pins the task store to LF'
  else
    bad '.gitattributes does not pin the task store to LF; the next checkout blanks the board'
  fi
else
  bad '.gitattributes is missing; nothing pins line endings'
fi

# And the belt to that braces: every direct source of testlib must strip CR
# itself, so a CRLF testlib arriving by some route git does not control - a zip,
# an editor, a Windows share - still works.
naked="$(git ls-files -z -- '*.sh' | xargs -0 grep -ln '^\. dashboard/testlib\.sh[[:space:]]*$' 2>/dev/null || true)"
if [ -z "$naked" ]; then
  ok 'every direct source of testlib strips CR itself'
else
  bad 'these source testlib without stripping CR, so a CRLF testlib breaks them:'
  printf '%s\n' "$naked" | sed 's/^/          /'
fi

finish
