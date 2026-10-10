# Windows/WSL prerequisite results

These are actual P01 preparation probes against installed tools and disposable synthetic files. They do not execute any of the four required real-provider scenarios or accept P06 client integration. The repository candidate was `f250627c352775e07d9a78b8d51c0e1a6445255b`; no runtime source changed.

| Probe | Observed result | Remaining limit |
| --- | --- | --- |
| Windows profile directory junction | 16 checks passed. Creating the junction needed no elevation. Installed Codex saved a dummy key and changed a feature setting in the canonical synthetic files. Alias and canonical paths identify the same files. | The whole profile shares logs and future session files. No real credential refresh, session isolation, WSL client launch, concurrent sessions or update behavior was tested. |
| NTFS files and tools | WSL and Windows exchanged exact binary markers in a path containing spaces. WSL launched installed Windows Python with the translated working directory and spaced argument. Windows Python/python3 and Git were available; Git initialized and inspected a disposable repository. | Generic Python/Git interoperability does not prove the agent clients use these tools or correctly route callbacks. The original cross-repository `~/hubdemo/calc` issue remains. |
| Windows descendant cleanup | A synthetic parent was created suspended, placed in an unnamed Windows Job Object, and resumed. Its child inherited that job. Exact handles proved both live before cleanup and terminal with exit code 73 after termination. | This does not prove WSL/tmux provider launches enter that job. Integration into a bounded real-provider supervisor still needs actual evidence. |

The earlier native file-symlink failure remains recorded in `../windows-link-failure`. A directory junction offers a different sharing method; it does not turn that failed test into a pass. Junction sharing can preserve Windows ownership without credential copying, but private per-agent state has not been established by this probe.

The NTFS report retains the initial exit-128 Git query outside a repository, followed by successful queries in a disposable repository. The report also retains hashes of earlier report revisions; only its final raw report is archived here. The generic forwarder and its client map were unchanged, and seven WSL client command links resolved to that forwarder; Pi was absent. Link presence alone does not qualify the clients.

Codex reviewed the producers, raw results and declared limits. `archive.json` binds the allowlisted raw bytes. Synthetic credential files, profile logs and the generated Git repository are excluded from the archive. The junction dummy-login output means a string was saved; it is not successful authentication. Proxy settings were used, but no packet capture or universal network-denial proof is claimed.

P01-T04 remains in progress. Grok still needs an available Windows-owned credential source. Before model runs, prove actual per-agent client/tool/callback attribution and fixture-specific Windows descendant containment. Preserve the original providers, scenarios and E1–E6 assertions. Ordinary Windows-owned client persistence is distinct from copying credentials into WSL; a requirement for zero personal-profile writes was a conservative preparation constraint, not a proven supported client feature.
