# P01 regression replacement review

Codex reviewed these changes against accepted commit `f19c6473d56335b8eeb28704b02895b9d9ab7fcc` on October 9, 2026.

- `tests/storage/run.py`: only the report destination changes. `AGENTMUX_EVIDENCE_DIR` lets CI write fresh evidence outside the checkout. The default destination and every test assertion remain unchanged. The current storage report records 14 passing cases.
- `tests/leaf/run.py`: the same report-destination change preserves every assertion and default behavior. The current narrow leaf report records 11 passing cases.
- `tests/leaf/README.md`: the original text remains intact. Added sections explain the signed fixture, key handling, owner checks and limitations. They explicitly preserve the original fixture and historical evidence.

The replacement manifest binds these reviewed changes to exact file hashes. Its negative check removes an actual Python assertion in memory and requires rejection. This does not prove the quality of every assertion or grant phase acceptance. The signed fixture adds coverage; it does not replace the existing broker tests.


## Storage extension after a2e9ee6

Codex reviewed three added storage cases: lost final batch acknowledgment, a stale KV projection with owner/policy revalidation, and fixture rejection of unsupported atomicity claims. All 14 previous cases remain; all 17 pass under WSL. An AST multiset comparison against the accepted snapshot confirms that every original `require` call and `assert` expression remains. This checks retention, not semantic equivalence by itself; the changed control flow and passing output were also inspected. The README retains each original line and adds the scope and limits of these cases. Their exact replacement hashes are recorded in the manifest. Earlier report-destination-only review above remains historical.

A fourth extension connects the actual conditional-write winner to a controllable fake worker/provider. The fixture reads the retained owner record before dispatch, denies the loser, suppresses the winner's duplicate and observes one actual callback, admission and completion. All 18 cases pass. Its imported helper is included in the source hashes. Dispatch deduplication is explicitly in memory and does not claim production external-effect fencing. The original assertion comparison still passes.
