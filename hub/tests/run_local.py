"""Small local test loop. Full means the hub suites, not a platform phase gate."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
FAST = ["hub.tests.test_local_runner", "hub.tests.test_governance", "hub.tests.test_fed_unit"]
LIVE = ["hub.tests.test_nats_federation", "hub.tests.test_fed_live"]
PROFILES = {"fast": FAST, "offline": FAST + ["hub.tests.test_hub_offline"],
            "live": LIVE, "full": FAST + ["hub.tests.test_hub_offline"] + LIVE}


def selector(test):
    # Class/module setup failures need a loadable selector, not _ErrorHolder's label.
    return re.sub(r"^(?:setUpClass|tearDownClass|setUpModule|tearDownModule) \((.*)\)$", r"\1", test.id())


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.failed_names = set()
        self.executed = set()
        self.timings = []

    def startTest(self, test):
        self.started = time.perf_counter()
        self.executed.add(test.id())
        super().startTest(test)

    def stopTest(self, test):
        self.timings.append({"test": test.id(), "seconds": round(time.perf_counter() - self.started, 4)})
        super().stopTest(test)

    def addFailure(self, test, err):
        self.failed_names.add(selector(test))
        super().addFailure(test, err)

    def addError(self, test, err):
        self.failed_names.add(selector(test))
        super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.failed_names.add(test.id())
        super().addSubTest(test, subtest, err)

    def addUnexpectedSuccess(self, test):
        self.failed_names.add(test.id())
        super().addUnexpectedSuccess(test)


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def atomic_json(path, data):
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", help="unittest module, class or method; overrides profile")
    parser.add_argument("--profile", choices=PROFILES, default="fast")
    parser.add_argument("--failed", action="store_true", help="retry failures from the last unsuccessful run")
    parser.add_argument("--keep-going", action="store_true", help="do not stop at the first failure")
    parser.add_argument("--list", action="store_true", help="print selected modules without starting fixtures")
    args = parser.parse_args(argv)
    if args.failed and args.tests:
        parser.error("choose --failed or explicit tests")
    if os.environ.get("AGENTMUX_FED_KIND") == "1":
        parser.error("this local runner does not reset a kind/shared cluster; use its separate qualification procedure")
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    cache = cache / "agentmux-tests" / hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
    failed_file = cache / "failed.json"
    names = args.tests or PROFILES[args.profile]
    if args.failed:
        names = json.loads(failed_file.read_text(encoding="utf-8"))["tests"] if failed_file.exists() else []
        if not names:
            print("No saved failing tests. No verification was performed.")
            return 0
    if args.list:
        print("\n".join(names))
        return 0
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    run = cache / (time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
    run.mkdir(mode=0o700)
    os.chdir(ROOT)
    source = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted((ROOT / "hub").rglob("*.py"))}
    for name in ("hub/requirements.txt", "hub/requirements.lock"):
        source[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    print(f"Running {', '.join(names)}; evidence: {run}", flush=True)
    started = time.perf_counter()
    with (run / "tests.log").open("w", encoding="utf-8") as log:
        output = Tee(sys.stderr, log)
        with contextlib.redirect_stdout(Tee(sys.stdout, log)), contextlib.redirect_stderr(output):
            prior_errors = len(unittest.defaultTestLoader.errors)
            suite = unittest.defaultTestLoader.loadTestsFromNames(names)
            load_failed = len(unittest.defaultTestLoader.errors) > prior_errors
            result = unittest.TextTestRunner(stream=output, verbosity=2, resultclass=TimedResult,
                                            failfast=not args.keep_going and args.profile != "full").run(suite)
    complete = result.wasSuccessful() and result.testsRun > 0 and not result.skipped and not result.expectedFailures
    retry = set(names) if load_failed or result.testsRun == 0 else result.failed_names.copy()
    retry.update(selector(t) for t, _ in result.skipped + result.expectedFailures)
    report = {"selection": names, "profile": "focused" if args.tests or args.failed else args.profile,
              "status": "passed" if complete else "failed-or-incomplete", "tests": result.testsRun,
              "seconds": round(time.perf_counter() - started, 3), "python": sys.version,
              "failures": sorted(result.failed_names), "retry": sorted(retry),
              "skips": [(t.id(), why) for t, why in result.skipped],
              "expectedFailures": [t.id() for t, _ in result.expectedFailures],
              "slowest": sorted(result.timings, key=lambda t: t["seconds"], reverse=True)[:10],
              "sourceSha256": source, "phaseGatePassed": False}
    atomic_json(run / "result.json", report)
    # Successful unrelated tests must not erase the last failing selection.
    if retry:
        atomic_json(failed_file, {"tests": sorted(retry), "run": str(run)})
    elif args.failed and complete:
        atomic_json(failed_file, {"tests": [], "run": str(run)})
    print(f"{report['status']}: {result.testsRun} tests in {report['seconds']:.2f}s; {run / 'result.json'}")
    for row in report["slowest"][:3]:
        print(f"  {row['seconds']:.3f}s {row['test']}")
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
