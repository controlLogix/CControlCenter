# voicecli

Talk to any LLM command-line tool (Claude Code, Codex, Grok, Gemini, aider, or a plain shell) by voice.

- **Local transcription.** faster-whisper runs on the CPU, so there's no cloud, API key or GPU.
- **Live overlay.** An always-on-top, opaque window shows words as you speak and never takes keyboard focus.
- **Typed into the active CLI.** Each finished phrase is typed into whichever window has focus.
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
```

The first run downloads the Whisper models (~500 MB for `small.en` + `base.en`) into the Hugging Face cache.

## Use

1. Start `voicecli`, then click into the terminal running your CLI.
2. Speak. Grey italic text is the live preview. When you pause (0.7 s), the phrase is finalized and typed into that terminal.
3. Say **"send it"** (also "submit", "press enter", "go ahead") on its own to press Enter, or run with `--enter` to submit every phrase automatically.
4. **Ctrl+Alt+Space** pauses/resumes listening (double-clicking the overlay does too).
5. Right-click the overlay for: microphone, opacity, typing on/off, auto-Enter, quit. Drag it anywhere; the position is remembered.

## Options

| flag | default | |
|---|---|---|
| `-d, --device` | Windows default | mic index or part of its name, e.g. `-d focusrite` |
| `-m, --model` | `small.en` | model for the final text: `tiny.en` `base.en` `small.en` `medium.en` `large-v3` `distil-large-v3` |
| `--partial-model` | `base.en` | faster model for the live preview; `same` reuses `--model` |
| `--language` | auto | for multilingual models, e.g. `de` |
| `--enter / --no-enter` | off | press Enter after every phrase |
| `--type / --no-type` | on | type into the focused window (off = transcript only) |
| `--opacity` | `1.0` | overlay opacity, 0.2–1.0 |
| `--silence-ms` | `700` | pause that ends a phrase |
| `--hotkey` | `ctrl+alt+space` | toggle listening |
| `--port` | `47821` | local API |
| `--no-overlay` | | headless: stdout + API only |
| `-v` | | also emit mic `level` events |

Flags are saved to `%APPDATA%\voicecli\config.json`, so the next run starts the same way.

## API (127.0.0.1:47821)

| | |
|---|---|
| `GET /health` | state, current device, model, options |
| `GET /devices` | microphones |
| `GET /events` | Server-Sent Events: `state` `device` `speech_start` `partial` `final` `typed` `discard` `hint` `error` `option` |
| `POST /listening` `{"on": false}` | pause / resume |
| `POST /device` `{"device": "hyperx"}` | switch mic |

stdout carries the same events as one JSON object per line, e.g.

```json
{"type": "partial", "text": "list all the files in"}
{"type": "final", "text": "List all the files in the current directory.", "audio_s": 4.74, "latency_s": 1.21}
{"type": "typed", "action": "typed", "window": "Windows PowerShell"}
```

## How it works

```
mic ─▶ MicStream (WASAPI → DirectSound → MME fallback, resampled to 16 kHz)
     ─▶ Transcriber: energy VAD with adaptive noise floor + 300 ms pre-roll
          • while speaking: base.en re-transcribes the utterance every ~0.4 s → partial
          • after 0.7 s silence: small.en (beam 3) → final
     ─▶ App fan-out: stdout JSONL · overlay · SSE · SendInput (Unicode) into the foreground window
```

On an i7-12700K, `base.en` partials take ~0.4 s and a `small.en` final takes ~1.2 s for 5 s of speech.

## Notes

- Windows blocks typing into apps running as administrator from a normal process. If your terminal is elevated, run voicecli elevated too.
- If the overlay warns "Mic is silent", check the headset's mute switch or pick another input.
- `tests/sim_engine.py <wav…>` replays WAV files through the real engine; `tests/check_inject.py` checks Unicode typing; `tests/demo_overlay.py` shows the overlay with scripted text.
