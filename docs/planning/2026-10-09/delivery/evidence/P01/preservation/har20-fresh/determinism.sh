#!/usr/bin/env bash
# Run correlate.py -> spotcheck.py -> correlate.py twice and compare sha1 of every output.
set -eu
cd "$(dirname "$0")"
run() {
  python3 correlate.py >/dev/null
  python3 spotcheck.py >/dev/null
  python3 correlate.py
  sha1sum out/outcomes.jsonl out/summary.md out/spotcheck.sample.jsonl out/spotcheck.raw.jsonl spotcheck.judgments.json
}
run > /home/ryan/.cache/agentmux-governance/har20-4d6vov3v/det-1.txt
run > /home/ryan/.cache/agentmux-governance/har20-4d6vov3v/det-2.txt
cat /home/ryan/.cache/agentmux-governance/har20-4d6vov3v/det-1.txt
if cmp -s /home/ryan/.cache/agentmux-governance/har20-4d6vov3v/det-1.txt /home/ryan/.cache/agentmux-governance/har20-4d6vov3v/det-2.txt; then echo "DETERMINISTIC: identical sha1 across two runs"; else echo "DIFFERENT"; diff /home/ryan/.cache/agentmux-governance/har20-4d6vov3v/det-1.txt /home/ryan/.cache/agentmux-governance/har20-4d6vov3v/det-2.txt || true; fi
rm -f /home/ryan/.cache/agentmux-governance/har20-4d6vov3v/det-1.txt /home/ryan/.cache/agentmux-governance/har20-4d6vov3v/det-2.txt
