# Voice CLI

Talk to any command-line tool (Claude Code, Codex, Grok, Gemini, aider, or a plain shell) by voice.
Hold a key, speak, let go, and the words are typed into the window you chose, even while you work in
another app. The typical setup: lock Voice CLI onto a Claude Code terminal, then keep working in
Ableton or a browser while Claude drives them through MCP.

- **Standalone Windows app.** `VoiceCLI.exe` carries its own runtime and speech models. No Python and no command line.
- **Starts when you sign in** and lives in the notification area; pin it to the taskbar.
- **Local and offline.** faster-whisper on the CPU, with models shipped inside the install. Nothing leaves the PC.
- **Push-to-talk or open mic.** Hold **Right Ctrl** (the default), or switch to always listening.
- **Live overlay.** Always on top; shows words as you speak and never takes keyboard focus.
- **Send text anywhere.** To whatever has focus, or to one window you lock (**Ctrl+Alt+L**).
- **Robust.** Survives a wireless headset switching off and on, falls back to the default mic, and runs as one instance.
- **Authenticated local API** (HTTP + Server-Sent Events): what the voice-cli Claude Code plugin (`plugins/voice-cli/`) talks to.

## Install

Run `VoiceCLI-Setup-<version>.exe`. It installs for your Windows user only (no admin prompt) into
`%LOCALAPPDATA%\Programs\VoiceCLI`, adds **Voice CLI** to the Start menu (and the desktop), and by
default starts it at every sign-in.

**Pin it to the taskbar** (Windows doesn't let programs pin themselves): open Start, type
*Voice CLI*, right-click it and choose **Pin to taskbar**. Clicking the pinned icon starts Voice CLI,
or brings the running one forward.

Upgrading: run the newer setup. It closes the running app, replaces it and starts it again.
Settings are kept. Uninstall from **Settings → Apps**.

### Silent deployment (Intune, SCCM, scripts)

```powershell
VoiceCLI-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART            # start at sign-in + desktop icon
VoiceCLI-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /TASKS="startup"   # no desktop icon
"%LOCALAPPDATA%\Programs\VoiceCLI\unins000.exe" /VERYSILENT                   # uninstall
"%LOCALAPPDATA%\Programs\VoiceCLI\VoiceCLI.exe" --self-test                  # exit code 0 = healthy install
```

Run these as the user the app is for: it installs per user.

## Use

1. Click into the terminal running your CLI, or lock onto it with **Ctrl+Alt+L** (press again to unlock).
2. **Hold Right Ctrl** and talk. Grey italic text is the live preview. Release it and the phrase is typed.
   With a locked window, Voice CLI switches to it, types, and switches back to your app.
3. Say **"send it"** (also "submit", "press enter", "go ahead") on its own to press Enter, or turn on
   *Press Enter after each phrase*.
4. **Right-click the overlay** to change listening mode, microphone, target window, typing, auto-Enter,
   opacity, *Start with Windows* and *Open log folder*, or to hide or quit. Drag it anywhere; the
   position is remembered.
5. **Tray icon:** click to show the overlay. Right-click for Show/Hide, Start with Windows, Open log folder and Quit.
6. **Ctrl+Alt+V** hides or shows the overlay. In open-mic mode **Ctrl+Alt+Space** pauses and resumes.

Nothing is typed when the desktop, the taskbar or the overlay itself has focus; the overlay shows
"not typed" instead. If the chosen mic disappears, Voice CLI uses the Windows default until it comes
back, then switches back on its own, and shows a notification each time.

## Settings

`%APPDATA%\voicecli\config.json` (changes from the menus are saved there). Invalid values are ignored
field by field and logged.

| key | default | |
|---|---|---|
| `device` | Windows default | mic name, or part of it |
| `mode` | `ptt` | `ptt` (hold the key) or `open` (always listening) |
| `ptt_key` | `rctrl` | `rctrl` `ralt` `capslock` `f13` `mouse4` `mouse5` or a combo like `ctrl+win` |
| `model` / `partial_model` | `small.en` / `base.en` | final text / live preview (both ship with the app) |
| `language` | auto | for multilingual models, e.g. `de` |
| `auto_enter` / `type_text` | `false` / `true` | press Enter after each phrase / type at all |
| `opacity` | `1.0` | 0.2–1.0 |
| `silence_ms` | `700` | open mic: pause that ends a phrase (100–5000) |
| `hotkey` / `lock_hotkey` / `show_hotkey` | `ctrl+alt+space` / `ctrl+alt+l` / `ctrl+alt+v` | |
| `port` | `47821` | local API |
| `log_transcripts` | `false` | write spoken text and window titles to the log (off: only their length) |
| `allow_download` | `false` | let other models (e.g. `medium.en`) download from Hugging Face |

## Privacy and logs

- Audio is processed in memory and never written to disk or sent anywhere.
- Log: `%LOCALAPPDATA%\voicecli\logs\voicecli.log` (1 MB, 5 rotations). It records states, devices
  and which program text was typed into, but not **what** was said or the window titles, unless
  `log_transcripts` is on.
- Versions before 1.0 wrote transcripts to `%APPDATA%\voicecli\voicecli.log`. That file is no longer
  used; delete it if you don't want those old phrases kept.

## API (`127.0.0.1:47821`)

Every request needs the token from `%APPDATA%\voicecli\api-token` (created on first run, private to
your Windows user). Requests from browsers are refused.

```powershell
$h = @{ Authorization = "Bearer " + (Get-Content "$env:APPDATA\voicecli\api-token") }
Invoke-RestMethod http://127.0.0.1:47821/health -Headers $h
Invoke-RestMethod http://127.0.0.1:47821/target -Method Post -Headers $h -ContentType application/json -Body '{"title":"claude"}'
```

| | |
|---|---|
| `GET /health` | without a token: `{ok, app, version}` only. With a token: state, device, target, options |
| `GET /devices` | microphones |
| `GET /windows` | windows text can be sent to |
| `GET /events` | Server-Sent Events: `state` `mode` `device` `target` `speech_start` `partial` `final` `typed` `discard` `hint` `error` `option` |
| `POST /mode` `{"mode": "open"}` | push-to-talk / open mic |
| `POST /listening` `{"on": false}` | open mic: pause / resume |
| `POST /device` `{"device": "hyperx"}` | switch mic |
| `POST /target` `{"title": "claude"}` / `{"hwnd": 123}` / `{}` | lock to a window / follow focus |
| `POST /show`, `POST /quit` | bring the overlay forward / exit |

POST bodies must be `Content-Type: application/json` objects of at most 64 KiB.

## How it works

```
mic ─▶ MicStream (WASAPI → DirectSound → MME fallback, 16 kHz)  ◀── watchdog: reconnect / fall back / return
     ─▶ Transcriber: phrase = key held (push-to-talk) or energy VAD + 0.7 s silence (open mic), 300 ms pre-roll
          • while speaking: base.en re-transcribes about every 0.4 s → partial
          • phrase done → queue → final worker: small.en (beam 3) → final   (capture never waits)
     ─▶ App fan-out: overlay · tray · log (redacted) · SSE · SendInput (Unicode) into the focused or locked window
```

On an i7-12700K, `base.en` partials take ~0.4 s and a `small.en` final takes ~1.2 s for 5 s of speech.
Architecture review and hardening notes: [docs/AUDIT.md](docs/AUDIT.md).

## Build

Requires [uv](https://docs.astral.sh/uv/) and Inno Setup 6 (`winget install JRSoftware.InnoSetup --scope user`).

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

This runs the tests and freezes the app with PyInstaller (`dist\VoiceCLI\`). It adds the pinned,
SHA-256-verified models (`packaging\fetch_models.py`), runs `VoiceCLI.exe --self-test`, and compiles
`dist\VoiceCLI-Setup-<version>.exe`. Set `VOICECLI_SIGN_THUMBPRINT` to a code-signing certificate's
thumbprint to sign the exe, the installer and the uninstaller.

Developing from source:

```powershell
uv sync --group dev
uv run pytest                      # automated tests
uv run voicecli                    # run from source (console: JSONL events on stdout)
uv run voicecli devices            # list microphones
uv run voicecli --no-overlay -v    # headless
```

`tests/manual/` has hardware checks: `check_inject.py` (Unicode typing), `check_lock.py` (delivery to
a locked background window), and `sim_engine.py <wav…>` (replays recordings through the real engine).

## Notes

- Windows blocks typing into apps running as administrator from a normal process. If your terminal
  is elevated, run Voice CLI elevated too.
- If the overlay warns "Mic is sending pure silence", check the headset's mute switch or pick another input.

## Voice → Ableton

The Ableton MCP (`~/ableton-mcp-extended`) is registered with Claude Code (user scope). Open a Claude
Code session, lock Voice CLI to it (Ctrl+Alt+L), then hold Right Ctrl and ask, e.g., "what's on track 3
and what EQ is on it?". Ableton needs **AbletonMCP** selected as a Control Surface (Preferences → Link,
Tempo & MIDI; Input/Output: None).
