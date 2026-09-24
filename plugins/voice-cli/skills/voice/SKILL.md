---
name: voice
description: Drive Voice CLI, the local push-to-talk app that types speech into a terminal. Use when the user wants to talk to this session by voice, lock voice onto this terminal ("send my voice here", "lock voice to Claude"), switch push-to-talk and open mic, change or fix the microphone, check whether voice is working, or have Claude listen for a spoken answer.
---

# Voice CLI

Voice CLI runs on this Windows PC and types what the user says into one window. This skill
drives it through the `voice-cli` MCP server's `voice_*` tools. Those tools call the app's
authenticated API on 127.0.0.1. Nothing is recorded here, and no audio leaves the PC.

## First, check it is there

Call `voice_status`.

- **It works:** you get `state`, `mode` (`ptt` or `open`), `device` (the microphone),
  `target` (the locked window, or `null` when it follows focus) and `ptt_key`. Tell the user
  which key to hold and where the text will go.
- **It says Voice CLI is not reachable, or there is no token:** Voice CLI is not running or
  not installed. It starts at sign-in and lives in the notification area. To install it, run
  `VoiceCLI-Setup-<version>.exe`. To build it, see `voice-cli/README.md`. Do not start
  installers yourself.

## Send the user's voice to this session

1. `voice_windows` lists candidate windows. Pick this session's terminal: its title usually
   contains "Claude Code", the working folder or the shell name. If more than one matches,
   ask the user which one.
2. `voice_lock` with that `hwnd`. Prefer the hwnd to a title substring, because titles change
   as the terminal runs commands.
3. Tell the user to hold the talk key (`ptt_key` from `voice_status`, Right Ctrl by default)
   and speak. Saying "send it" on its own presses Enter.

`voice_unlock` sends text to whichever window has focus again.

## Other things the user may ask for

| Ask | Tool |
|---|---|
| "Always listen", "hands free" | `voice_mode` with `open` |
| "Only when I hold the key" | `voice_mode` with `ptt` |
| "Stop listening for a bit" / "resume" (open mic) | `voice_listening` with `on` false or true |
| "Use my headset" | `voice_devices`, then `voice_device` with part of its name |
| "Where is the overlay?" | `voice_show` |

## Listening for an answer

`voice_listen` waits for the next finished phrase and returns its text (`heard: true`), or
`heard: false` on timeout. Use it when you asked the user a question out loud, or they said
they will answer by voice. Voice CLI still types the phrase into its target window, so if
that window is this session, the same words also arrive as the next message. Do not act on
them twice.

## Limits

- Windows only. The MCP server runs with the Windows `python`, and the app listens on
  Windows loopback. It cannot be reached from inside WSL.
- There is deliberately no tool to quit Voice CLI. That is the user's call, from the tray icon.
- Settings the API does not expose, such as the talk key, the model and auto-Enter, live in
  `%APPDATA%\voicecli\config.json` or the overlay's right-click menu. Point the user there;
  do not edit that file while the app is running.
