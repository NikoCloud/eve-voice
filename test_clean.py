"""Dictation cleanup on real dictated messages (Niko's, from voice input), plus a few edge cases."""
import os
import time

os.environ.setdefault("EVE_WORKSPACE", os.path.join(os.environ["TEMP"], "eve-clean-test"))
import eve as E  # noqa: E402

SAMPLES = [
    "Okay, so I have two engineering questions for you. I want to build an AI a local AI butler that I can talk to.",
    "One last thing. Most of the turn-based things, including this I'm doing right now with you, uses direct "
    "text-to-speech. I mean, speech-to-text, I'm sorry. And it works, but it's also very token inefficient.",
    "No, no, no, no. I mean, the cloud, the cloud, uh, you know, cloud Opus, Sonnet, Anthropic, cloud mobile app.",
    "Yeah, but I chose turn by turn only because it's easier to build, and I didn't have a duplex model available "
    "that isn't like 50 something billion parameters big, you know? I need something that fits in the 16 gigabyte card.",
    "check the disk space on cachy os",
    "Um, ask Frank to, uh, restart the lfm 3 server. No wait, scratch that, ask him to check its logs first.",
    "Write a commit message saying exactly: fixed the the bug in 3.14.9",
    "So, um, so, the the rock m build on rdna four, uh, it keeps failing at at the linking step.",
]

os.makedirs(E.WORKSPACE / "sessions", exist_ok=True)
os.makedirs(E.HANDOFFS, exist_ok=True)


class Mini(E.Eve):  # just the cleanup, no Frank or speaker
    def __init__(self):
        self.last_prompt_tokens = 0
        self.session = E.Session.new()


eve = Mini()
for raw in SAMPLES:
    t0 = time.perf_counter()
    out, how = eve.clean(raw)
    ms = round((time.perf_counter() - t0) * 1000)
    print(f"[{how:5}] {ms:>4} ms  {len(raw.split()):>3} -> {len(out.split()):>3} words")
    print(f"   heard: {raw}")
    print(f"   clean: {out}\n")
