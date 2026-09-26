---
id: "TM-043"
kind: "task"
status: "open"
created: "2026-09-26T02:03:34.168Z"
board: "controllogix/ccontrolcenter"
title: "Resolve mcp, agents and skills from WSL when every MCP server is a Windows process"
epic: "EP-002"
acceptance: [{"text":"host: windows servers are launched by the field sidecar's mcp_bridge and exposed as MCP Streamable HTTP at /mcp/<name> with a shared secret","done":false},{"text":"host: wsl servers pass straight through as stdio","done":false},{"text":"Skills are materialised to AGENTMUX_HOME on ext4 and COPIED, fingerprinted by content hash, never symlinked","done":false},{"text":"settingSources is ['project'] and deliberately not 'user', so a mode is a complete reproducible description","done":false},{"text":"A test asserts posture: unrestricted never produces bypassPermissions","done":false},{"text":"/api/modes reports each server's host and a live tools/list digest, so a silently wrong resolution is visible","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:03:34.210Z"
---

Phase 2.4, and the largest gap in the blade spec. Every MCP server on this
machine is a Windows process: modbus is npx modbus-mcp, word is an exe, and
codesys_rt must sit beside the IDE. The API is in WSL. So 'mcp: [codesys_rt,
modbus, drawio]' in a mode file cannot resolve to a WSL stdio spawn - a Linux
modbus-mcp sees different NICs and no COM ports, and there is no Linux codesys_rt.

Running Windows stdio through interop was rejected for four reasons, and CRLF on
stdout corrupting JSON-RPC framing is the decisive one.

posture: unrestricted must NEVER map to permissionMode bypassPermissions. Posture
is a PANE concept and a subagent inherits the parent's mode. Hard-code it to
undefined and assert it.