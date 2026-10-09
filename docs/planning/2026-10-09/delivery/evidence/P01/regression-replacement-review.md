# P01 regression replacement review

Codex reviewed these changes against accepted commit `f19c6473d56335b8eeb28704b02895b9d9ab7fcc` on October 9, 2026.

- `tests/storage/run.py`: only the report destination changes. `AGENTMUX_EVIDENCE_DIR` lets CI write fresh evidence outside the checkout. The default destination and every test assertion remain unchanged. The current storage report records 14 passing cases.
- `tests/leaf/run.py`: the same report-destination change preserves every assertion and default behavior. The current narrow leaf report records 11 passing cases.
- `tests/leaf/README.md`: the original text remains intact. Added sections explain the signed fixture, key handling, owner checks and limitations. They explicitly preserve the original fixture and historical evidence.

The replacement manifest binds these reviewed changes to exact file hashes. Its negative check removes an actual Python assertion in memory and requires rejection. This does not prove the quality of every assertion or grant phase acceptance. The signed fixture adds coverage; it does not replace the existing broker tests.
