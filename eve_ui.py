"""Eve's local web UI: http://127.0.0.1:8899

Runs Eve in-process and streams what she does to the page over SSE.
  python eve_ui.py            voice through the PC speakers, mic via push-to-talk
  python eve_ui.py --no-audio text only
  python eve_ui.py --wav-dir D write speech to files instead of playing it (testing)
"""
import argparse
import asyncio
import base64
import io
import json
import os
import pathlib
import re
import subprocess
import threading
import time
import wave

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import eve as E

HERE = pathlib.Path(__file__).resolve().parent
app = FastAPI()
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
STATE = {"eve": None, "audio": True, "rec": None, "frames": [], "state": "idle"}
PTT_LOCK = threading.Lock()
clients: set[asyncio.Queue] = set()
browser_audio_clients: set[asyncio.Queue] = set()
loop: asyncio.AbstractEventLoop | None = None


def broadcast(ev):
    if ev.get("type") == "state":
        STATE["state"] = ev["state"]
    if loop is None:
        return
    targets = clients
    if ev.get("type") == "audio":
        # Her voice as sound data (about 120 KB a second) goes only to pages that play it: the ones that
        # connected for browser audio, or every page when "This Browser Tab" is the chosen output.
        eve = STATE["eve"]
        targets = clients if (eve and eve.speaker.browser_only) else browser_audio_clients
    for q in list(targets):
        loop.call_soon_threadsafe(q.put_nowait, ev)


E._listeners.append(broadcast)

# Names this page may be reached by (localhost + Tailscale). Anything else is refused (see local_only below).
ALLOWED_HOSTS = {"127.0.0.1", "localhost", *E.EXTRA_HOSTS}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Only Eve's own page (on this PC or over Tailscale) may talk to her. Without this, any web page open in
    a browser could POST to 127.0.0.1 and start the microphone or send her a message.
    - Host must be one of ours (stops a hostile site that re-points its own name at 127.0.0.1).
    - If the browser says which page the request came from (Origin), it must match this Host over http or https."""
    host = request.headers.get("host", "")
    host_only = host.rsplit(":", 1)[0].lower()
    origin = request.headers.get("origin")
    host_ok = host_only in ALLOWED_HOSTS  # exact names only: "any *.ts.net" would trust every tailnet's names
    origin_ok = origin is None or origin in (f"http://{host}", f"https://{host}")
    if not host_ok or not origin_ok:
        E.log(f"REFUSED {request.method} {request.url.path} host={host!r} origin={origin!r}")
        return JSONResponse({"ok": False, "reason": "forbidden"}, status_code=403)
    return await call_next(request)


SERVICES = [  # (key, label, url, what it is)
    ("llm", "Eve's brain", f"http://{E.HOSTS['cachyos']}:8085/health", "E4B on the 9070 XT"),
    ("tts", "Voice", f"http://{E.HOSTS['cachyos']}:8087/health", "Ming on the 9070 XT"),
    ("stt", "Ears", f"http://{E.HOSTS['cachyos']}:8088/", "Whisper on the 9070 XT"),
    ("frank", "Frank", "http://127.0.0.1:8642/health", "Hermes API server"),
    ("engine", "Frank's engine", f"http://{E.HOSTS['cachyos']}:8080/health", "Qwen3.8-27B llama-server"),
]
HEALTH = {}


def check_health():
    """Ping each service every 10 s; report status and round-trip time to the page."""
    import urllib.request
    while True:
        for key, label, url, what in SERVICES:
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(url, timeout=3) as r:
                    ok = r.status == 200
            except Exception:
                ok = False
            HEALTH[key] = {"key": key, "label": label, "what": what, "ok": ok,
                           "ms": round((time.perf_counter() - t0) * 1000) if ok else None}
        E.emit("health", services=list(HEALTH.values()))
        time.sleep(10)


@app.on_event("startup")
async def _startup():
    global loop
    loop = asyncio.get_running_loop()
    threading.Thread(target=check_health, daemon=True).start()


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    clients.add(q)
    want_audio = request.query_params.get("browser_audio") == "1"
    if want_audio:
        browser_audio_clients.add(q)
        if STATE["eve"]:
            STATE["eve"].speaker.browser_audio = True

    async def gen():
        try:
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            clients.discard(q)
            browser_audio_clients.discard(q)
            if STATE["eve"]:
                STATE["eve"].speaker.browser_audio = bool(browser_audio_clients)
    return StreamingResponse(gen(), media_type="text/event-stream")


def transcript(eve):
    """The session as the page shows it: user and Eve lines, tool calls folded in."""
    out = []
    for m in eve.session.history:
        if m["role"] == "user":
            out.append({"type": "user", "text": m["content"]})
        elif m["role"] == "assistant":
            text = m.get("content") or ""
            if text.startswith("[No answer:"):
                out.append({"type": "error", "text": "Eve couldn't answer: her model didn't respond."})
                continue
            mark = re.match(r"\[Frank finished job (\d+), (\w+)\]\s*", text)
            if mark:
                out.append({"type": "note", "text": f"Frank finished job {mark.group(1)} ({mark.group(2)})"})
                text = text[mark.end():]
            text = E.strip_tags(text)
            if text:
                out.append({"type": "eve", "text": text})
        elif m["role"] == "system" and m["content"].startswith("Earlier in this session"):
            out.append({"type": "note", "text": "Earlier conversation was compacted into a summary."})
    return out


@app.get("/state")
def state():
    eve = STATE["eve"]
    return {"session": eve.session.id, "title": eve.session.title, "sessions": E.Session.recent(),
            "tokens": eve.last_prompt_tokens, "compact_at": E.CFG["compact_at"],
            "window": E.CFG["context_window"], "jobs": eve.frank.view(),
            "transcript": transcript(eve), "state": STATE["state"], "audio": STATE["audio"],
            "think_mode": E.CFG.get("think_mode", "256"), "hotkey": bool(STATE.get("hotkey")),
            "audio_device": eve.speaker.device, "audio_devices": E.list_output_devices(),
            "health": list(HEALTH.values())}


@app.get("/audio_devices")
def get_audio_devices():
    eve = STATE["eve"]
    devs = E.list_output_devices(refresh=True)
    return {"ok": True, "device": eve.speaker.device, "devices": devs}


@app.post("/audio_device")
def set_audio_device(body: dict):
    eve = STATE["eve"]
    dev = (body.get("device") or "default").strip()
    eve.speaker.set_device(dev)
    devs = E.list_output_devices()
    E.emit("audio_device", device=eve.speaker.device, devices=devs)
    if body.get("test"):
        eve.speaker.interrupt()
        eve.speaker.say_raw("Voice check, loud and clear.")
    return {"ok": True, "device": eve.speaker.device, "devices": devs}


@app.post("/think")
def set_think(body: dict):
    mode = str(body.get("mode", "256"))
    if mode not in ("256", "128", "tools", "off"):
        return JSONResponse({"ok": False, "reason": "invalid mode"}, status_code=400)
    E.CFG["think_mode"] = mode
    E.CFG["think"] = mode != "off"
    if mode in ("128", "256"):
        E.CFG["think_budget"] = int(mode)
    E.log(f"THINK_MODE set to {mode}")
    E.emit("think_mode", mode=mode)
    return {"ok": True, "think_mode": mode}


@app.post("/audio_mode")
def set_audio_mode(body: dict):
    browser_on = bool(body.get("browser_audio"))
    if STATE["eve"]:
        STATE["eve"].speaker.browser_audio = browser_on or bool(browser_audio_clients)
    return {"ok": True, "browser_audio": browser_on}


@app.post("/interrupt")
def interrupt(body: dict | None = None):
    if STATE["eve"]:
        STATE["eve"].speaker.interrupt()
    if (body or {}).get("listening"):
        E.emit("state", state="listening")
    elif not STATE["rec"]:
        E.emit("state", state="idle")
    return {"ok": True}


@app.post("/say")
async def say(body: dict):
    text = (body.get("text") or "").strip()
    raw = (body.get("raw") or "").strip() or None  # set when the text came from the mic (and maybe was edited)
    if text:
        threading.Thread(target=STATE["eve"].turn, args=(text,), kwargs={"raw": raw}, daemon=True).start()
    return {"ok": True}


# What Whisper writes when it is handed silence or room noise. On 2026-11-12 the global talk key recorded
# silence about 180 times in 18 minutes and each one became a "Thank you." turn that Eve answered out loud.
_SILENCE_PHRASES = {"thank you", "thanks", "thank you very much", "thank you so much", "thanks for watching",
                    "thank you for watching", "you", "bye", "bye bye", "okay", "ok", "so", "oh", "hmm"}


def _level(wav_bytes: bytes) -> float:
    """Loudness of a 16-bit WAV as RMS (0 to 32768)."""
    import numpy as np
    a = np.frombuffer(wav_bytes[44:len(wav_bytes) - (len(wav_bytes) - 44) % 2], dtype="<i2")
    return float(np.sqrt(np.mean(a.astype("float64") ** 2))) if len(a) else 0.0


def _phantom(text: str, rms: float) -> bool:
    """True if this 'transcript' is Whisper filling in silence rather than something Niko said."""
    words = re.sub(r"[^\w\s']", "", text).strip().lower()
    if not words:  # nothing but punctuation
        return True
    return rms < E.CFG["quiet_rms"] and words in _SILENCE_PHRASES


def _handle_ptt_wav(wav_bytes: bytes, review: bool = False):
    """Shared transcription + dictation cleanup for both PC mic (/ptt/stop) and browser/phone mic (/ptt/audio)."""
    rms = _level(wav_bytes)
    if rms < E.CFG["quiet_rms"] / 5:  # near-silent: don't even ask Whisper
        E.log(f"PTT dropped: silence (level {rms:.0f})")
        E.emit("state", state=STATE["eve"].speaker.resting_state())
        return {"ok": False, "reason": "silence"}
    E.emit("state", state="thinking")

    def heard_nothing(e):
        E.log("STT failed:", repr(e))
        E.emit("error", text=f"Eve couldn't hear that: her speech-to-text didn't respond ({e}).")
        E.emit("state", state="idle")

    if review:
        t0 = time.perf_counter()
        try:
            raw = E.transcribe(wav_bytes)
        except Exception as e:
            heard_nothing(e)
            return {"ok": False, "reason": "stt"}
        if raw and _phantom(raw, rms):
            E.log(f"PTT dropped: {raw!r} at level {rms:.0f} looks like silence")
            raw = ""
        clean, how = STATE["eve"].clean(raw) if raw else ("", "none")
        E.log(f"STT+CLEAN (review) {round((time.perf_counter() - t0) * 1000)}ms {how}")
        E.emit("timing", stage="heard", ms=round((time.perf_counter() - t0) * 1000))
        E.emit("state", state="idle")
        return {"ok": bool(clean), "text": clean, "raw": raw}

    def work():
        t0 = time.perf_counter()
        try:
            text = E.transcribe(wav_bytes)
        except Exception as e:
            heard_nothing(e)
            return
        ms = round((time.perf_counter() - t0) * 1000)
        E.log(f"STT {ms}ms level={rms:.0f}")
        E.emit("timing", stage="heard", ms=ms)
        if text and _phantom(text, rms):
            E.log(f"PTT dropped: {text!r} at level {rms:.0f} looks like silence")
            text = ""
        if text:
            t1 = time.perf_counter()
            clean, how = STATE["eve"].clean(text)
            E.log(f"CLEAN {how} {round((time.perf_counter() - t1) * 1000)}ms")
            E.emit("timing", stage="heard", ms=round((time.perf_counter() - t0) * 1000))
            STATE["eve"].turn(clean, raw=text)
        else:
            E.emit("state", state=STATE["eve"].speaker.resting_state())
    threading.Thread(target=work, daemon=True).start()
    return {"ok": True}


def ptt_discard():
    """Stop recording and throw the audio away (the talk key turned out to be part of a shortcut, or a tap)."""
    with PTT_LOCK:
        rec = STATE["rec"]
        if not rec:
            return
        try:
            rec.stop()
            rec.close()
        except Exception:
            pass
        STATE["rec"] = None
        STATE["frames"] = []
    E.emit("state", state=STATE["eve"].speaker.resting_state())


@app.post("/ptt/start")
def ptt_start():
    with PTT_LOCK:
        if not STATE["audio"] or STATE["rec"]:
            return {"ok": False}
        import sounddevice as sd
        STATE["eve"].speaker.interrupt()
        STATE["frames"] = []
        rec = sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                             callback=lambda d, n, t, s: STATE["frames"].append(d.copy()))
        rec.start()
        STATE["rec"] = rec
        E.emit("state", state="listening")
        return {"ok": True}


@app.post("/ptt/stop")
def ptt_stop(body: dict | None = None):
    """mode "send" (default): transcribe and send to Eve. mode "review": transcribe and hand the cleaned text
    back to the page for the text box, without sending."""
    review = (body or {}).get("mode") == "review"
    with PTT_LOCK:
        rec = STATE["rec"]
        if not rec:
            return {"ok": False}
        rec.stop()
        rec.close()
        STATE["rec"] = None
        frames = STATE["frames"]
    import numpy as np
    audio = np.concatenate(frames) if frames else np.zeros((0, 1), dtype="int16")
    if len(audio) < 16000 * 0.3:
        E.emit("state", state="idle")
        return {"ok": False, "reason": "too short"}
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(audio.tobytes())
    return _handle_ptt_wav(buf.getvalue(), review=review)


@app.post("/ptt/audio")
def ptt_audio(body: dict):
    """Receive base64-encoded 16 kHz mono WAV recorded in the browser (e.g. phone over Tailscale HTTPS)."""
    b64 = body.get("wav") or ""
    if not b64:
        E.emit("state", state="idle")
        return {"ok": False, "reason": "empty"}
    try:
        wav_bytes = base64.b64decode(b64)
    except Exception:
        E.emit("state", state="idle")
        return {"ok": False, "reason": "bad base64"}
    if len(wav_bytes) < 44 + int(16000 * 2 * 0.3):
        E.emit("state", state="idle")
        return {"ok": False, "reason": "too short"}
    if STATE["eve"] and body.get("browser_audio"):
        STATE["eve"].speaker.browser_audio = True
    return _handle_ptt_wav(wav_bytes, review=(body.get("mode") == "review"))


@app.post("/replay")
def replay(body: dict):
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False}
    STATE["eve"].speaker.replay(text, (body.get("spoken") or "").strip() or None)
    return {"ok": True}


@app.post("/jobs/{jid}/cancel")
def cancel(jid: int):
    return {"message": STATE["eve"].frank.cancel(jid)}


@app.post("/servers/{action}")
def servers(action: str):
    """Start or stop Eve's three model servers on cachyos (the script and the stop command live in E.CFG)."""
    if action not in ("start", "stop"):
        return JSONResponse({"ok": False, "reason": "unknown action"}, status_code=404)
    try:
        out = E.ssh_cachyos(E.CFG[f"servers_{action}"], timeout=30)
    except Exception as e:
        E.log(f"SERVERS {action} failed:", repr(e))
        return {"ok": False, "reason": f"Couldn't reach cachyos: {e}"}
    E.log(f"SERVERS {action}:", out.strip()[:300] or "(no output)")
    return {"ok": True, "output": out.strip()[:600]}


def announce_session(eve, switched=False, new=False):
    E.emit("session", id=eve.session.id, title=eve.session.title, tokens=eve.last_prompt_tokens,
           compact_at=E.CFG["compact_at"], window=E.CFG["context_window"], new=new, switched=switched)
    E.emit("sessions", sessions=E.Session.recent(), current=eve.session.id)


@app.post("/session/new")
def new_session():
    eve = STATE["eve"]
    with eve.turn_lock:
        if eve.session.history:  # an untouched session is reused rather than piling up empty ones
            eve.session = E.Session.new()
        eve.last_prompt_tokens = 0
    announce_session(eve, new=True)
    return {"session": eve.session.id}


@app.get("/sessions")
def sessions():
    return {"sessions": E.Session.recent(), "current": STATE["eve"].session.id}


@app.post("/session/switch")
def switch_session(body: dict):
    eve = STATE["eve"]
    path = E.SESSIONS / f"{body.get('id', '')}.jsonl"
    if not path.exists() or path.parent != E.SESSIONS:
        return JSONResponse({"ok": False, "reason": "no such session"}, status_code=404)
    with eve.turn_lock:
        eve.session = E.Session.load(path)
        eve.last_prompt_tokens = 0
    announce_session(eve, switched=True)
    return {"ok": True, "transcript": transcript(eve)}


@app.post("/reveal")
def reveal(body: dict):
    """Show a path in Explorer. Files are selected, never opened, so nothing runs."""
    p = pathlib.Path(body.get("path", ""))
    if not p.exists():
        return JSONResponse({"ok": False, "reason": "not found"}, status_code=404)
    if p.is_dir():
        subprocess.Popen(["explorer", str(p)])
    else:
        subprocess.Popen(["explorer", "/select,", str(p)])
    return {"ok": True}


def start_global_hotkey():
    """Global Right Ctrl hold-to-talk (Shift + Right Ctrl to review in the text box) via pynput,
    so Niko can talk to Eve even when another window is focused or Eve is minimized to the tray.
    Because the key works everywhere, it only counts as talking when it is held on its own for 0.4 s or
    more: a quick tap, or Right Ctrl used with another key, records nothing."""
    try:
        from pynput import keyboard
    except ImportError:
        E.log("HOTKEY pynput not installed; global Right Ctrl disabled")
        return
    import queue
    shift_keys = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
    state = {"down": False, "shifts": set(), "mode": "send", "t": 0.0, "combo": False}
    HOLD_S = 0.4  # shorter presses are taps or slips, not talking
    jobs: queue.Queue = queue.Queue()  # start / stop / discard run in the order the keys happened

    def worker():
        while True:
            fn = jobs.get()
            try:
                fn()
            except Exception as e:
                E.log("HOTKEY action failed:", repr(e))

    def stop(mode):
        if STATE["rec"] is None:
            return
        res = ptt_stop({"mode": mode})
        if mode == "review" and isinstance(res, dict) and res.get("ok"):
            E.emit("draft", text=res.get("text", ""), raw=res.get("raw", ""))

    def on_press(key):
        if key in shift_keys:
            state["shifts"].add(key)
        elif key == keyboard.Key.ctrl_r:
            if state["down"]:  # key auto-repeat while held
                return
            state.update(down=True, combo=False, t=time.monotonic(),
                         mode="review" if state["shifts"] else "send")
            jobs.put(ptt_start)
        elif state["down"] and not state["combo"]:
            # another key while Right Ctrl is down: it's a shortcut (Ctrl+C, Ctrl+arrow), not talking to Eve
            state["combo"] = True
            jobs.put(ptt_discard)

    def on_release(key):
        if key in shift_keys:
            state["shifts"].discard(key)
        elif key == keyboard.Key.ctrl_r and state["down"]:
            state["down"] = False
            if state["combo"]:
                return
            if time.monotonic() - state["t"] < HOLD_S:
                jobs.put(ptt_discard)
            else:
                mode = state["mode"]
                jobs.put(lambda: stop(mode))

    threading.Thread(target=worker, daemon=True).start()
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.daemon = True
    listener.start()
    STATE["hotkey"] = True  # the page then leaves Right Ctrl to this listener, so the two never both act on it
    E.log("HOTKEY global Right Ctrl hold-to-talk active")


def run_desktop(port: int):
    """Run Eve in a native pywebview window with a system tray icon (closing the window hides to tray)."""
    import urllib.request
    import webview
    import pystray
    from PIL import Image

    srv_thread = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning"),
        daemon=True,
    )
    srv_thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"{url}/state", timeout=0.5):
                break
        except Exception:
            time.sleep(0.1)

    quitting = {"flag": False}
    win = webview.create_window("Eve", url, width=1240, height=840, min_size=(380, 560), background_color="#0b0d12")

    def on_closing():
        if not quitting["flag"]:
            win.hide()
            return False
        return True

    win.events.closing += on_closing

    def show_win(icon=None, item=None):
        win.show()
        try:
            win.restore()
        except Exception:
            pass

    def tray_new_session(icon=None, item=None):
        new_session()
        show_win()

    def quit_app(icon=None, item=None):
        quitting["flag"] = True
        try:
            if icon:
                icon.stop()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        os._exit(0)

    img = Image.open(HERE / "static" / "eve.jpg")
    menu = pystray.Menu(
        pystray.MenuItem("Show Eve", show_win, default=True),
        pystray.MenuItem("New Session", tray_new_session),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Eve", quit_app),
    )
    tray = pystray.Icon("eve", img, "Eve (Right Ctrl to talk)", menu)
    threading.Thread(target=tray.run, daemon=True).start()
    webview.start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--no-hotkey", action="store_true", help="disable global Right Ctrl hold-to-talk")
    ap.add_argument("--desktop", action="store_true", help="open native pywebview desktop window + system tray")
    ap.add_argument("--wav-dir")
    ap.add_argument("--new", action="store_true")
    ap.add_argument("--port", type=int, default=8899)
    a = ap.parse_args()
    E.HANDOFFS.mkdir(parents=True, exist_ok=True)
    E.SESSIONS.mkdir(parents=True, exist_ok=True)
    STATE["audio"] = not a.no_audio  # mic / push-to-talk available
    STATE["eve"] = E.Eve(audio=STATE["audio"] and not a.wav_dir, wav_dir=a.wav_dir, new_session=a.new)
    eve = STATE["eve"]
    # When she stops speaking: still "listening" if the mic is open, "thinking" if the reply isn't finished
    eve.speaker.resting_state = lambda: ("listening" if STATE["rec"] is not None
                                         else "thinking" if eve.turn_lock.locked() else "idle")
    if STATE["audio"] and not a.no_hotkey and not a.wav_dir:  # --wav-dir is a test run: never grab the key
        start_global_hotkey()
    print(f"Eve UI on http://127.0.0.1:{a.port}  (session {STATE['eve'].session.id})")
    if a.desktop:
        run_desktop(a.port)
    else:
        uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
