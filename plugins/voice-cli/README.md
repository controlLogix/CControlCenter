# voice-cli plugin

A Claude Code plugin for [Voice CLI](../../voice-cli/README.md), the local Whisper
push-to-talk app in this repo. It lets a session see and steer the app: lock voice onto its
own terminal, switch push-to-talk and open mic, change microphone, and wait for the user's
next spoken phrase.

| Path | What |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest |
| `.mcp.json` | Starts `mcp/voice_mcp.py` with the Windows `python` |
| `mcp/voice_mcp.py` | stdio MCP server, standard library only, over the app's HTTP API |
| `skills/voice/SKILL.md` | When and how to use the tools |
| `tests/test_voice_mcp.py` | Drives the real server over stdio against a stub API. No app, no network |

## Install

```powershell
claude plugin marketplace add gtownarmy-design/Forktah     # or a local checkout path
claude plugin install voice-cli@forktah
```

Voice CLI itself must be installed and running (see `voice-cli/README.md`). The plugin
starts nothing and installs nothing.

## Tools

| Tool | API call |
|---|---|
| `voice_status` | `GET /health` (with token: state, mode, device, target, options) |
| `voice_devices`, `voice_windows` | `GET /devices`, `GET /windows` |
| `voice_lock` `{title \| hwnd}`, `voice_unlock` | `POST /target` |
| `voice_mode` `{mode: ptt \| open}` | `POST /mode` |
| `voice_listening` `{on}` | `POST /listening` |
| `voice_device` `{device}` | `POST /device` |
| `voice_show` | `POST /show` |
| `voice_listen` `{timeout_s?, partials?}` | `GET /events` until the next `final` |

`POST /quit` is deliberately not exposed: closing the user's microphone app is not a
decision for an agent to make.

## Security

- The token is read from `%APPDATA%\voicecli\api-token` on every call, sent only to
  `127.0.0.1`, and never returned in a tool result.
- The app's own guards still apply: it accepts only loopback Host headers, refuses any
  request with an `Origin`, and requires the bearer token.
- `VOICECLI_URL` and `VOICECLI_TOKEN_FILE` override the address and token path. The tests
  use them. Nothing else should need to.

## Test

```powershell
python plugins/voice-cli/tests/test_voice_mcp.py
```
