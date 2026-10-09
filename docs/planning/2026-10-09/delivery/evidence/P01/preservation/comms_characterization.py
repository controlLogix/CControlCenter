"""Offline characterization of retained communication analysis; no message delivery."""
import collections
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import platform
from pathlib import Path
import runpy
import sys
import subprocess
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[7]
SOURCE = ROOT / "analysis/comms-2026-09"
REPORT = Path(__file__).with_name("comms-result.json")
sys.dont_write_bytecode = True


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    candidate = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    hashes = {p.name: sha(p) for p in SOURCE.iterdir() if p.is_file()}
    cases, findings, writes = [], [], []
    guard = {"active": False}
    with tempfile.TemporaryDirectory(prefix="agentmux-comms-") as folder:
        root = Path(folder).resolve()
        def audit(event, args):
            if not guard["active"]:
                return
            if event in ("subprocess.Popen", "os.system", "os.exec", "socket.connect", "socket.bind"):
                raise AssertionError("External execution or network access forbidden")
            if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(args[0])).resolve()
                flags = args[2] or 0
                if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                    assert path.is_relative_to(root), str(path)
                    writes.append(path.relative_to(root).as_posix())
        sys.addaudithook(audit)
        guard["active"] = True
        def load(name):
            # Only path literals in disposable copies are redirected. Logic is unchanged.
            text = (SOURCE / (name + ".py")).read_text(encoding="utf-8")
            for old in ("/home/nick", "/mnt/c/Users/Nick", "/mnt/c/Dev/agentmux"):
                text = text.replace(old, root.as_posix() + "/absent")
            path = root / (name + ".py")
            path.write_text(text, encoding="utf-8", newline="\n")
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        courier = load("extract_courier")
        panes = load("extract_panes")
        trans = load("extract_transcripts")
        receipts = load("extract_receipts")
        body = "\x1b[31m\x1b[200~[agentmux] from alpha (request) ref fixture: hello\n  world\x1b[201~\x1b[0m"
        assert courier.normalize(body)[0] == trans.normalize(body)[0] == "hello world"
        assert courier.body_fields(body)[1] == trans.body_fields(body)[1] == hashlib.sha1(b"hello world").hexdigest()
        cases.append("courier/transcript ANSI, paste, envelope and whitespace normalization with exact body hash")
        assert courier.iso_z(courier.parse_ts("2026-09-29T12:00:00-0500")) == "2026-09-29T17:00:00Z"
        assert courier.parse_ts("2026-09-29T12:00:00") is None
        assert courier.basis_of(None) == "unknown"
        cases.append("explicit CDT conversion and unzoned timestamp uncertainty")
        torn = root / "torn.jsonl"
        torn.write_text('{"body":"whole"}\n{"body":', encoding="utf-8", newline="\n")
        assert list(receipts.jsonl(str(torn))) == [(1, {"body": "whole"})]
        assert receipts.STATS["bad_json_line"] == 1
        assert list(receipts.jsonl(str(root / "missing.jsonl"))) == []
        cases.append("receipt partial final line counted and missing source returns no fabricated record")
        courier.SNAP = root
        (root / "queue").mkdir()
        (root / "queue/alpha.jsonl").write_bytes(torn.read_bytes())
        courier.load_queue()
        assert len(courier.QUEUE) == 2 and courier.QUEUE[1]["bad"]
        assert courier.QUEUE[1]["offset"] == len(b'{"body":"whole"}\n')
        cases.append("courier torn queue record retains byte offset and bad-record marker")
        unknown = panes.time_for([], [], 4, 10)
        assert unknown[0] is None and unknown[1] == "unknown"
        when = panes.datetime(2026, 9, 29, 12, tzinfo=panes.CDT)
        anchors = panes.build_anchors([], 100, when, None)
        bounded = panes.time_for(anchors, [x[0] for x in anchors], 50, 100)
        assert bounded[1] == "file-mtime" and bounded[2]["t_method"] == "upper-bound"
        assert bounded[2]["t_lo"] is None
        cases.append("pane missing clocks remain unknown or explicit mtime upper bound")
        pane = root / "beta.log"
        frozen = b"Claude Code\n[agentmux] from alpha (request) ref fixture: synthetic pane message\n"
        pane.write_bytes(frozen + b"\nOpenAI Codex\nlate appended text\n")
        pane_rows, pane_stats = panes.scan_file(str(pane), len(frozen), "2026-09-29 12:00", {"alpha", "beta"})
        assert pane_stats["read"] == len(frozen) and pane_stats["cli"] == "claude"
        assert any(r["type"] == "arrived" and r["sender"] == "alpha" for r in pane_rows)
        assert all(r["detail"]["offset"] < len(frozen) for r in pane_rows)
        pane.write_bytes(frozen)
        _, shortened = panes.scan_file(str(pane), len(frozen) + 100, "2026-09-29 12:00", {"alpha", "beta"})
        assert shortened["truncated_since_index"] and shortened["read"] == len(frozen)
        cases.append("actual pane scan respects frozen byte cutoff and flags a log shortened after indexing")
        fixture = root / "transcript.jsonl"
        def turn(t, ident):
            return {"timestamp": t, "sessionId": "fixture", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": ident, "name": "Bash", "input": {"command": "agentmux send beta 'fixture message'"}}]}}
        fixture.write_text('\n'.join(json.dumps(turn(t, str(i))) for i,t in enumerate([trans.CUTOFF_UTC, "2026-09-30T02:56:02Z", None])) + '\n{"agentmux":', encoding="utf-8", newline="\n")
        records, stats = [], collections.Counter()
        trans.process_file(str(fixture), str(root), records, stats)
        assert len(records) == 2 and stats["after_cutoff"] == 1 and stats["bad_json"] == 1
        assert records[0]["t"] == trans.CUTOFF_UTC and records[1]["t_basis"] == "unknown"
        cases.append("transcript exact cutoff included, later intent excluded, torn line counted, absent time unknown")
        # The original missing-source policies are characterized without concealing gaps.
        try:
            courier.read_lines(root / "missing.log")
            raise AssertionError("expected original missing-file exception")
        except FileNotFoundError:
            findings.append({"id": "COMMS-01", "behavior": "Courier read_lines raises FileNotFoundError for a missing required log; receipt jsonl silently returns no rows. Missing-source diagnostics are inconsistent.", "source": "extract_courier.py:read_lines / extract_receipts.py:jsonl"})
        out = root / "out"
        out.mkdir()
        def dump(name, values):
            (out / name).write_text(''.join(json.dumps(x) + '\n' for x in values), encoding="utf-8", newline="\n")
        queues, received = [], []
        expected = {"wrong": "wrong-recipient", "skew": "received", "late": "unknown", "truncated": "truncated", "duplicate": "duplicated", "unknown": "unknown"}
        for i, name in enumerate(expected):
            text = name + " synthetic message " + "x" * 100
            row = {"src": "courier", "type": "queued", "t": "2026-09-20T12:00:00Z", "agent": name, "sender": "alpha", "prefix": text[:80], "body_sha": hashlib.sha1(text.encode()).hexdigest(), "body_len": len(text), "ref": str(root / (name + '.jsonl')) + ':1', "detail": {"kind": "request", "courier_outcome": "sent"}}
            queues.append(row)
            (root / (name + '.jsonl')).write_text(json.dumps({"body":text})+'\n', encoding="utf-8", newline="\n")
            if name not in ("unknown", "duplicate"):
                r = dict(row, src="receipts", type="received", agent="other" if name == "wrong" else name, ref=str(root / (name + '-receipt.jsonl'))+':1', detail={"cli":"claude", "session_id":name,"map_conf":"high", "envelope":True})
                r['t'] = "2026-09-20T11:58:00Z" if name == 'skew' else "2026-09-20T16:00:01Z" if name == 'late' else row['t']
                if name == 'truncated':r.update(body_sha="different", body_len=30)
                received.append(r)
            if name == 'duplicate':
                for n in range(2):queues.append(dict(row,type='sent',ref=str(root / 'send.log')+':'+str(n+1),detail={"queued_ref":row['ref'],"link":"duplicate-of-previous-send" if n else "fifo-first-attempt"}))
        dump('courier.jsonl',queues);dump('receipts.jsonl',received)
        dump('receipts.rescued-claude-config.jsonl',received[:1])
        for n in ['panes.jsonl','transcripts.jsonl']:dump(n,[])
        # Retain both actual historical judgment files byte-for-byte in this disposable run.
        for name in ['spotcheck.judgments.json','spotcheck.pass1.judgments.json']:
            (root/name).write_bytes((SOURCE/name).read_bytes())
        script=root/'correlate.py';script.write_bytes((SOURCE/'correlate.py').read_bytes())
        runs=[]
        for _ in range(2):
            with contextlib.redirect_stdout(io.StringIO()): namespace=runpy.run_path(str(script))
            rows=[json.loads(line) for line in (out/'outcomes.jsonl').read_text().splitlines()]
            assert {r['agent']:r['outcome'] for r in rows} == expected
            assert len(namespace['receipts']) == len(received)
            runs.append({n:sha(out/n) for n in ['outcomes.jsonl','spotcheck.sample.jsonl','summary.md']})
        assert runs[0] == runs[1]
        for name in ['spotcheck.judgments.json','spotcheck.pass1.judgments.json']:assert sha(root/name)==hashes[name]
        first = json.loads((root/'spotcheck.pass1.judgments.json').read_text(encoding='utf-8'))
        second = json.loads((root/'spotcheck.judgments.json').read_text(encoding='utf-8'))
        judgment_history = {
            'pass1': dict(collections.Counter(v['verdict'] for v in first.values())),
            'pass2': dict(collections.Counter(v['verdict'] for v in second.values())),
            'sharedIds': len(first.keys() & second.keys()),
            'changedSharedVerdicts': {k: [first[k]['verdict'],second[k]['verdict']] for k in sorted(first.keys() & second.keys()) if first[k]['verdict'] != second[k]['verdict']},
            'basis': 'Retained historical judgments, not newly verified raw-source conclusions.'}
        assert judgment_history['pass1'] == {'agree':49,'disagree':10,'unverifiable':2}
        assert judgment_history['pass2'] == {'agree':49,'unverifiable':2}
        cases.extend(["full correlator wrong-recipient, inclusive two-minute skew, four-hour overflow unknown, truncation, duplicate send and absent-source unknown", "duplicate rescued receipt removed without adding a turn", "two complete correlation runs yield identical three output hashes and retain both original judgment datasets"])
        guard['active']=False
    assert hashes == {p.name:sha(p) for p in SOURCE.iterdir() if p.is_file()}
    report={"schemaVersion":"1.0.0","status":"characterized-with-findings","components":["HAR-19","HAR-20"],"sourceSha256":hashes,"harnessSha256":sha(Path(__file__)),"cases":cases,"findings":findings,"determinism":runs,"writeAudit":{"allWritesWithinDisposableRoot":True,"paths":sorted(set(writes))},"sourceUnchanged":True,"limits":["Synthetic bounded characterization, not reanalysis of private historical logs.","No messaging, network access, shell commands or historical hardcoded paths invoked.","Extractor functions tested narrowly; not every historical format or complete extractor main is qualified.","Both historical judgment datasets retained unchanged; historical agreement is not current acceptance."]}
    report['historicalJudgmentComparison'] = judgment_history
    report.update(recordedAt=datetime.now(timezone.utc).isoformat(), sourceCommit=candidate,
                  command=[sys.executable, *sys.argv], environment={'platform': platform.platform(), 'python': sys.version},
                  sourceDirectory='analysis/comms-2026-09', exitCode=0,
                  sourceBinding='Commit is the checkout base; sourceSha256 identifies exact original files. Disposable copies redirect only path literals.')
    REPORT.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({"cases":len(cases),"findings":len(findings),"report":str(REPORT)}))


if __name__ == '__main__':
    main()
