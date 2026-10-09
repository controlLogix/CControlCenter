# Full dashboard run on fba373a

The unchanged candidate ran all 62 suites: 48 direct entries and 14 entries selected by the runner loop. The full run took 402.5 seconds and failed two suites. This is failed preservation evidence, not phase acceptance.

- Field-panel concurrency: test_field_panels.py line 451 assumed a second loopback scan was still running when the next request arrived. The returned error was null and the assertion raised AttributeError.
- Browser navigation: 48 checks passed and one failed. The exact ordered list omitted the existing Federation view introduced by commit 3aec6c03 after Hub.
- External plugin coverage: test_orchestration_plugin.py skipped 16 tests and test_plugin_skills.py skipped four tests because AGENTMUX_PLUGIN_ROOT was absent. Their zero-check summaries are not passes. Follow-up logs retain every skipped test.
- Gateway: 57 checks passed on Python 3.14; the archived Python 3.12 bytecode differential was explicitly unavailable. The separate existing Python 3.12 report remains necessary.

The detached native checkout retained full Git history. Runtime sources were unchanged, tracked status was clean, the dashboard on port 8787 was unchanged, and the residue wrapper found no covered state changes. The environment had private home, state, temporary files, provider configuration directories and tmux sockets, with no provider credentials inherited. One owned remaining process was terminated; the later process scan found none. The temporary socket kill returned 1 and remains recorded, rather than counted as a successful kill.

Exact Playwright 1.64.0 and its browser manifest/lock are retained. Browser installation succeeded and the real Firefox test ran. Installation and test logs, runner scripts, source hashes, failures and skip inspection remain available. The full runner log was preserved through an open file handle because the existing residue wrapper removes its temporary log. No original test was changed during this full run.

The separate focused E2E report, when present, records only the navigation assertion correction and its actual browser result. It does not turn this failed full run into a pass.
