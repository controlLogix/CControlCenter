# Windows-backed dashboard qualification

Both runs used committed candidate `09fe9c749ff674c0dd5ca4fa7c53abfbe23cadcd`, a detached native Linux checkout, Windows-owned Codex 0.162.1 through its WSL forwarder, and private home, state, provider configuration and tmux directories. No native Linux Codex substitution was used. The archive manifest verifies all 403 tested source hashes against committed Git blobs and preserves copied evidence bytes.

| Evidence | Result | Meaning |
| --- | --- | --- |
| failed-candidate | Exit 1; 62 suites; 449.222 seconds | The temporary Unix socket path exceeded the Linux path-length limit in one hub-panel test. The unchanged runner continued and retained that failure. |
| passed-candidate | Exit 0; 62 suites; 479.113 seconds | The same source ran with a short owned temporary root. The hub-panel test first passed separately, then the complete runner and residue wrapper passed. |

The later run passed the repaired residue checks (26), MQTT checks (57), field-panel checks (213), Firefox browser checks (49), and authentication configuration checks (81). This is a runner pass with explicit missing coverage, not phase acceptance.

## Remaining limits

- Two external-plugin suites reported zero checks because the required Agentmux orchestration plugin was absent: 16 and four tests were skipped. They are not passes. Their exact skip details are retained in the earlier `../preservation/dashboard-full-fba373a/` evidence. An unrelated orchestration plugin cannot substitute for them.
- Python 3.14 could not load the archived Python 3.12 gateway bytecode. The 57 current gateway checks passed; the separate existing Python 3.12 differential report remains necessary.
- The isolation probes show that the actual Windows client received the private CODEX_HOME and rejected unique invalid fields from its private base configuration and profile. The Windows environment probe reported no provider API keys. These are configuration-routing checks, not a system-wide file-access audit. The harness did not open default credential files.
- A valid private profile reached a Windows state-database initialization failure over a Linux UNC path. That failure is retained. Neither the configuration tests nor the dashboard run qualify Windows Codex inference or state storage on UNC paths; no provider inference is claimed.
- Both runs left the dashboard on port 8787 unchanged and recorded no remaining owned Linux processes after cleanup. The passing run's short temporary root was removed. Windows process-wide access auditing was not performed.

## Evidence integrity and privacy

Original failed results are kept separately from the passing rerun. Raw JSON, logs, scripts and other files in this directory use `-text` so Git does not rewrite bytes referenced by hashes. `archive-manifest.json` records copied bytes and checks bound log and harness hashes. It excludes itself from its file digest list.

The evidence was reviewed as synthetic local fixture output: paths, source hashes, command versions, configuration-field markers and error messages. No real token values, private transcripts or model reasoning are included. Credential checks record presence booleans only. A scan for private-key blocks and common API-token/JWT forms found none; that scan supplements the bounded fixture review rather than proving every possible secret format absent.
