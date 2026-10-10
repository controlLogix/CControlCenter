# Provenance and limits

This is newly maintained Agentmux repository code and guidance, created for the P01 preservation repair. Original plugin source was not recovered. Version 0.1.0 and author Agentmux maintainers identify this maintained replacement only, not the original package. No upstream version, author or license claim is made; no repository license file was found during the approved scope review. Publication and release licensing are outside this local repair.

Original names agent-new, agent-roster, agent-edit and agent-remove come from commit ef513e0606c49e7527ba0415fa830fed564c458b. Names team-compose, team-dispatch, team-merge, agent-config and agent-doctor, plus the hook/MCP structure, come from bc81405c81faef89dcbe638415a5dba8974d1e7f. Commit ef08abc2a3b89325cc3f71b431156267e2bc08fa explains guarded member integration. Those commit messages are historical claims, not current test evidence.

Behavior is derived from current taskmgmt/coordination.py, dispatch.py, agentdefs.py and setup_auth.py; dashboard/boardagents.py and boardteams.py; docs/CONTRACTS_agents.md; and the unchanged external plugin tests. Current executable contracts take precedence over historical wording. Original skill prose, full parser behavior and packaging metadata remain unknown.

The detailed approved restoration scope and bounded search record live in docs/planning/2026-10-09/delivery/evidence/P01/plugin-restoration-spec.md and recovery-evidence.json in the runtime repository. Passing compatibility tests demonstrates the maintained replacement's observed behavior, not source equality with the unavailable original. Unsupported host execution, real-provider qualification and later plugin framework work remain separate.
