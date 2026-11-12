# Eve (test build)

Eve is a thin voice front end for Frank. Her program runs on Windows. Her model (Gemma 4 E4B heretic), voice (Ming 3.0, UK_Charlotte) and speech-to-text (Whisper large-v3-turbo) run on cachyos, on the RX 9070 XT only. Frank is reached through Hermes's API server (Runs API).

This is a test setup. Nothing in production starts it.

## Local settings (`eve_local.json`)

Machine addresses are not in the code. Copy `eve_local.example.json` to `eve_local.json` (git-ignored) and fill in:
- `hosts.cachyos`: the address of the Linux box that runs the models.
- `allowed_hosts`: names the UI may be reached by besides this PC, such as your Tailscale machine name.

Without the file the code points at documentation addresses (203.0.113.x) that don't answer.

## Setup (Windows, once)

```bash
cd %USERPROFILE%\dev\eve
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Start the model servers (cachyos)

```bash
ssh cachyos '~/voice-test/start-eve-servers.sh'
```

This starts three tmux sessions on cachyos's Tailnet address (`hosts.cachyos` in `eve_local.json`):

| Session | Port | What runs |
|---|---|---|
| `eve-llm` | 8085 | E4B, two slots of 128K each |
| `eve-tts` | 8087 | Ming |
| `eve-stt` | 8088 | Whisper |

The UI can do this too: the **Start servers** button appears next to the status lights whenever one of the three is down, and **Stop servers** when all are up. The brain takes about 30 seconds to load.

The LLM server runs two separate 128K slots (`-c 262144 -np 2`, no `--kv-unified`). With `--kv-unified`, every side job on slot 1 (dictation rewrite, title, Frank digest) made slot 0 re-read the whole conversation on the next turn.

To stop them:

```bash
ssh cachyos 'tmux kill-session -t eve-llm; tmux kill-session -t eve-tts; tmux kill-session -t eve-stt'
```

## Run Eve's UI (Windows)

The easy way: double-click **Start Eve.bat** in this folder. It starts Eve and opens her page; close its window to stop her. Or from a terminal:

```bash
cd %USERPROFILE%\dev\eve
.venv\Scripts\python eve_ui.py
```

Or run the native desktop app (`pywebview` window + system tray icon + global `Right Ctrl` hold-to-talk):

```bash
.venv\Scripts\python eve_desktop.py
```

Then open http://127.0.0.1:8899 (or on your phone over Tailscale at https://<your-machine>.<your-tailnet>.ts.net:8899). To speak to her, hold **Right Ctrl** (works globally across Windows even when another window is focused) or hold the **Talk** button; you can also type.
- **Talk key:** with the global key on, hold Right Ctrl to talk and release to send; hold Shift with it to get the transcript in the text box first. Tap-to-toggle is on the on-screen Talk button. Without the global key (`--no-hotkey`, or on another device), Right Ctrl works as before while the page has focus: hold to send, tap to toggle.
- **Phone / Tailscale Gateway:** served over HTTPS via `tailscale serve --bg --https=8899 http://127.0.0.1:8899`. On a phone, the UI switches to a mobile tab layout with browser microphone capture and WebAudio streaming playback.
- **Thinking budget & streaming TTS:** configurable in the UI (`256 tok`, `128 tok`, `Tools` only, or `Off`), and LLM responses stream sentence-by-sentence so Ming TTS starts speaking on the first sentence.
- **Portrait ring:** shows her state. Grey is idle, teal is listening, amber is thinking, green is speaking.
- **Frank's jobs:** shown on the right, with live steps, a Cancel button, and his full result.
- **Paths:** Windows paths in the conversation open in Explorer.
- **Options:** `--desktop` opens the native window + tray icon; `--no-hotkey` disables global Right Ctrl; `--no-audio` turns voice off; `--new` starts a new session.

## Run Eve in the terminal (Windows)

```bash
cd %USERPROFILE%\dev\eve
.venv\Scripts\python eve.py
```

At the prompt, either type a message, or press Enter on an empty line to talk, then press Enter again to stop.

Other modes:
- `--no-audio`: text only.
- `--wav-dir DIR`: write her speech to files instead of playing it.
- `--script FILE`: send each line of the file as a turn. See `test_script.txt`.
- `--new`: start a new session instead of resuming the last one.

## Dictation cleanup

Spoken input is cleaned before Eve sees it, the way Wispr Flow does it. The raw transcript stays in the log, and in the UI under "show what I heard".
- **In code, always, instantly:** fillers (um, uh), stutters ("the the", "the cloud, the cloud"), and names Whisper gets wrong, using `vocab.txt` (one rule per line: `heard form | other form -> Correct`).
- **E4B, only when needed:** used when the speech has self-corrections ("no wait", "scratch that", "I mean", "sorry") or runs past 60 words. It uses Eve's second slot in a throwaway context, takes about 150–400 ms, and is guarded: a rewrite that grows, collapses, or drops a number is thrown away and the code-cleaned version is used instead.
- **Verbatim:** saying "verbatim", "word for word", "saying exactly" or "quote unquote" skips all cleanup for that message.

`test_clean.py` runs the cleanup on real dictated samples.

## Web search

Eve's `web_search` tool asks SearXNG on cachyos first (free, unlimited). If that fails or finds nothing, it falls back to Exa, which costs about $0.007 a search out of Exa's monthly free credit. The Exa key is read from Frank's `.env` when needed and never copied. Bigger lookups go to Frank.

## Safety

- **Her page only:** the UI refuses requests that don't come from its own page, on this PC or at her Tailscale address. The names are listed exactly in `ALLOWED_HOSTS` in `eve_ui.py`; serving her under another name means adding it there.
- **The talk key can't fire by accident:** global Right Ctrl only counts when held on its own for 0.4 s or more. A tap, or Right Ctrl used in a shortcut, records nothing. A recording that is silent, or that Whisper turns into a stock phrase like "Thank you." at a low mic level, is dropped and never becomes a turn. Each recording's level is in `eve.log` (`STT ... level=`); the threshold is `quiet_rms` in `eve.py`.
- **cachyos is read-only for Eve:** `run_cachyos` takes one plain command (pipes allowed) from a short list, and refuses options that write, run a program, change a setting or never return. `test_cachyos_filter.py` checks it without touching cachyos.
- **Failures show on screen:** if her model, voice, ears or the speakers don't respond, a red notice says which, and she goes back to idle.

## Sessions

- **Saving:** each conversation is saved as it happens to `sessions\<id>.jsonl` in the workspace.
- **Resuming:** on start, Eve resumes the last session if it was active in the past 4 hours, otherwise she starts a new one. Saying "new session" also starts a fresh one.
- **Context:** E4B has 128K of context per slot (two slots). The whole session stays in context until a prompt passes 64K tokens (half the window, to keep latency down). Then the older half is folded into a short summary.
- **Frank's jobs:** saved in `jobs.json` with numbers that carry across sessions, so a follow-up to job 3 works the next day. If Eve stops while Frank is mid-job, she checks the job's outcome with Hermes on restart and still tells you the result.
- **Follow-ups:** a follow-up job reuses the earlier job's Frank session. A new job gets a fresh one.

## Where things live

- **System prompt:** `eve_prompt.md`.
- **Eve's workspace:** `%USERPROFILE%\eve\workspace`. It's the only place she can write.
- **Handoff briefs for Frank:** `handoffs\` inside the workspace.
- **Log:** `eve.log` inside the workspace.
- **Frank's key:** read from `%LOCALAPPDATA%\hermes\profiles\frank\.env` (`API_SERVER_KEY`).
