# Real-provider test readiness

The original four scenarios remain required: calibration, team, cross-repository and swarm. They must use their original provider assignments and satisfy each E1–E6 assertion. Shell workers and fake providers cannot replace them.

The Windows Grok authentication file is absent. The recorded process, user and machine scopes have no `XAI_API_KEY`. WSL's default Grok authentication file is also absent. These are bounded presence observations, not an exhaustive credential search. No sign-in, credential copy or model call was performed. A Windows-owned credential source has been requested.

The original readiness plan retains separate prerequisites for Windows-local client state, selected-hub callbacks, tool paths and process cleanup. Current provider versions and Boolean credential observations in that plan describe its earlier inspection; they are not a new authenticated run.

Further research found that Codex documents separate `sqlite_home`, `log_dir` and `history.persistence` overrides. This may allow Windows-local runtime state while keeping the Windows authentication/configuration source, but it is only a candidate approach until the installed client and original launcher are tested. See the [official configuration reference](https://developers.openai.com/codex/config-reference/).

Claude's configuration-directory override moves settings, session history and plugins together. Its session-specific settings flag can override selected values while retaining omitted file settings. These documented options do not prove mixed Windows/WSL session isolation. See [settings precedence](https://code.claude.com/docs/en/settings) and the [CLI reference](https://code.claude.com/docs/en/cli-reference).

P01-T04 and the P01 gate remain open. No P06 integration, production adapter or phase advancement is accepted by these observations.
