# voicecli

Talk to any LLM command-line tool (Claude Code, Codex, Grok, Gemini, aider, or a plain shell) by voice.

- **Local transcription.** faster-whisper runs on the CPU, so there's no cloud, API key or GPU.
- **Push-to-talk or open mic.** Hold **Right Ctrl** to talk (the default), or switch to always listening in the right-click menu.
- **Live overlay.** An always-on-top, opaque window shows words as you speak and never takes keyboard focus.
- **Typed into your CLI.** Each finished phrase goes to the window that has focus, or to one window you lock (**Ctrl+Alt+L**) so you can keep working in other apps.
- **Taskbar launcher.** `install-shortcuts.ps1` adds a "Voice CLI" shortcut; launching it again brings the running overlay forward.
- **Selectable microphone.** Pick one on the command line, over the API or from the overlay's right-click menu. The choice is remembered.
- **Service interface.** JSONL events on stdout, plus an HTTP/SSE API on `127.0.0.1` (the seam for the planned ByteDesk plugin).

> The original plan was the superwhisper CLI, but its installer supports macOS only
> (`superwhisper is macOS-only`). This project covers the same ground on Windows.

## Install

Requires [uv](https://docs.astral.sh/uv/) (it provides Python 3.12).

```powershell
cd C:\Users\brent\voice-cli
uv sync
uv run voicecli devices        # list microphones
uv run voicecli                # start: overlay + typing
powershell -ExecutionPolicy Bypass -File install-shortcuts.ps1   # Start menu + desktop shortcut
```

To pin it, open Start, right-click **Voice CLI** and choose **Pin to taskbar** (Windows doesn't let apps pin themselves).

The first run downloads the Whisper models (~500 MB for `small.en` + `base.en`) into the Hugging Face cache.

## Use

1. Start Voice CLI. Click into the terminal running your CLI, or lock onto it with **Ctrl+Alt+L** (press again to unlock).
2. **Hold Right Ctrl** and talk; grey italic text is the live preview. Release it and the phrase is typed. With a locked window, voicecli switches to it, types, and switches back to your app.
3. Say **"send it"** (also "submit", "press enter", "go ahead") on its own to press Enter, or turn on "Press Enter after each phrase".
4. Right-click the overlay for: listening mode (push-to-talk / open mic), microphone, which window to send text to, typing on/off, auto-Enter, opacity, hide, quit. Drag it anywhere, including another monitor; the position is remembered.
5. **Ctrl+Alt+V** hides/shows the overlay. In open-mic mode, **Ctrl+Alt+Space** pauses/resumes.

Nothing is typed when the desktop, the taskbar or the overlay itself has focus; the overlay shows "not typed" instead.

## Options

| flag | default | |
|---|---|---|
| `-d, --device` | Windows default | mic index or part of its name, e.g. `-d focusrite` |
| `--mode` | `ptt` | `ptt` (hold the key) or `open` (always listening) |
| `--ptt-key` | `rctrl` | `rctrl` `ralt` `capslock` `f13` `mouse4` `mouse5` or a combo like `ctrl+win` |
| `-m, --model` | `small.en` | model for the final text: `tiny.en` `base.en` `small.en` `medium.en` `large-v3` `distil-large-v3` |
| `--partial-model` | `base.en` | faster model for the live preview; `same` reuses `--model` |
| `--language` | auto | for multilingual models, e.g. `de` |
| `--enter / --no-enter` | off | press Enter after every phrase |
| `--type / --no-type` | on | type into the focused window (off = transcript only) |
| `--opacity` | `1.0` | overlay opacity, 0.2–1.0 |
| `--silence-ms` | `700` | pause that ends a phrase |
| `--hotkey` | `ctrl+alt+space` | open mic: pause/resume |
| `--port` | `47821` | local API |
| `--no-overlay` | | headless: stdout + API only |
| `-v` | | also emit mic `level` events |

Flags are saved to `%APPDATA%\voicecli\config.json`, so the next run starts the same way.

## API (127.0.0.1:47821)

| | |
|---|---|
| `GET /health` | state, current device, model, options |
| `GET /devices` | microphones |
| `GET /windows` | windows text can be sent to |
| `GET /events` | Server-Sent Events: `state` `mode` `device` `target` `speech_start` `partial` `final` `typed` `discard` `hint` `error` `option` |
| `POST /mode` `{"mode": "open"}` | push-to-talk / open mic |
| `POST /listening` `{"on": false}` | open mic: pause / resume |
| `POST /device` `{"device": "hyperx"}` | switch mic |
| `POST /target` `{"title": "claude"}` / `{"hwnd": 123}` / `{}` | lock to a window / follow focus |
| `POST /show`, `POST /quit` | bring the overlay forward / exit |

stdout carries the same events as one JSON object per line, e.g.

```json
{"type": "partial", "text": "list all the files in"}
{"type": "final", "text": "List all the files in the current directory.", "audio_s": 4.74, "latency_s": 1.21}
{"type": "typed", "action": "typed", "window": "Windows PowerShell"}
```

## How it works

```
mic ─▶ MicStream (WASAPI → DirectSound → MME fallback, resampled to 16 kHz)
     ─▶ Transcriber: phrase = key held (push-to-talk) or energy VAD + 0.7 s silence (open mic), 300 ms pre-roll
          • while speaking: base.en re-transcribes the phrase every ~0.4 s → partial
          • at the end: small.en (beam 3) → final
     ─▶ App fan-out: stdout JSONL · overlay · SSE · SendInput (Unicode) into the focused or locked window
```

On an i7-12700K, `base.en` partials take ~0.4 s and a `small.en` final takes ~1.2 s for 5 s of speech.

## Notes

- Windows blocks typing into apps running as administrator from a normal process. If your terminal is elevated, run voicecli elevated too.
- If the overlay warns "Mic is silent", check the headset's mute switch or pick another input.
- `tests/sim_engine.py [--ptt] <wav…>` replays WAV files through the real engine; `tests/check_inject.py` checks Unicode typing; `tests/check_lock.py` checks delivery to a locked background window.

## Voice → Ableton

The Ableton MCP (`~/ableton-mcp-extended`) is registered with Claude Code (user scope). Open a Claude Code session, lock voicecli to it (Ctrl+Alt+L), then hold Right Ctrl and ask, e.g., "what's on track 3 and what EQ is on it?". Ableton needs **AbletonMCP** selected as a Control Surface (Preferences → Link, Tempo & MIDI, Input/Output: None).
