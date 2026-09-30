"""Summarize every orchestration report into evals/orchestrations/SCOREBOARD.md.

    python3 hub/demo/scoreboard.py
"""
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(os.path.dirname(os.path.dirname(HERE)), "evals", "orchestrations")

rows = []
for p in sorted(glob.glob(os.path.join(D, "*.json"))):
    r = json.load(open(p))
    st = r.get("stats", {})
    failed = [k for k, v in (r.get("checks") or {}).items() if not v]
    rows.append((r["run"], r["scenario"], "YES" if r.get("error_free") else "no", ", ".join(failed) or "-",
                 len(r.get("agents", [])), st.get("work_items", 0), st.get("deliveries", 0), st.get("acked", 0),
                 json.dumps(st.get("bells", {})), sum(len(m) for m in st.get("modal_answers", []) if m),
                 st.get("extra_enters", 0), st.get("duration_s", 0), "; ".join(r.get("errors", []))[:160] or "-"))

lines = ["# Orchestration scoreboard", "",
         "Every live run of `hub/demo/orchestrate.py`. ERROR-FREE means all of E1-E6 held (see the script header).",
         "", "| run | scenario | error-free | failed checks | agents | work items | deliveries | acked | bells | "
             "modal answers | extra Enters | seconds | errors |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    lines.append("| " + " | ".join(str(x).replace("|", "/") for x in r) + " |")
ok = [r for r in rows if r[2] == "YES"]
lines += ["", f"**{len(ok)} of {len(rows)} runs error-free.**"]
open(os.path.join(D, "SCOREBOARD.md"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
