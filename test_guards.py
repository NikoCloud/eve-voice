"""Checks for the guards added after the 2026-11-12 phantom-turn loop: silence transcripts, the
'Eve promised to ask Frank' fallback, and speaking the rest of a reply after a streamed first sentence."""
import os
import tempfile
os.environ.setdefault("EVE_WORKSPACE", tempfile.mkdtemp())
import eve as E
E.WORKSPACE.mkdir(parents=True, exist_ok=True)
import eve_ui as U

bad = 0


def check(ok, label):
    global bad
    bad += not ok
    print("ok  " if ok else "FAIL", label)


Q = E.CFG["quiet_rms"]
for text, rms, want in [("Thank you.", Q - 1, True), (" Thank you. ", 30, True), (".", 5000, True), ("...", 5000, True),
                        ("", 5000, True), ("Thanks for watching!", 100, True), ("you", 60, True),
                        ("Thank you.", Q + 1, False), ("Thank you.", 3000, False),
                        ("Check the disk on cachyos.", 60, False), ("Thank you, that's all for today.", 60, False)]:
    check(U._phantom(text, rms) is want, f"phantom {text!r} at level {rms} -> {want}")

for text, want in [("I'll ask Frank to look into it.", True), ("Let me ask Frank.", True),
                   ("I will have Frank check the logs.", True), ("Let me pass this to Frank.", True),
                   ("I'll hand that over to Frank.", True), ("I'm going to get Frank to do it.", True),
                   ("Not yet. I'll tell you when Frank is done.", False),
                   ("I'll have the result once Frank finishes.", False),
                   ("I have sent you what Frank found.", False), ("Let me tell you what Frank said.", False),
                   ("I'll ask Frank's engine for its status.", False), ("Frank is idle.", False)]:
    check(bool(E._PROMISED_FRANK.search(text)) is want, f"promise {text!r} -> {want}")

sp = E.Speaker(False)
sp.enabled = True  # queue only; no thread, no audio device
for full, first, want in [("I'm on it. Checking the drives now.", "I'm on it.", ["Checking the drives now."]),
                          ("Sure: here it is. Second part.", "Sure:\nhere it is.", ["Second part."]),
                          ("Done.  Two spaces. More.", "Done.", ["Two spaces. More."]),
                          ("Only one sentence here.", "Only one sentence here.", []),
                          ("Different opening. Then more.", "Something else entirely.", ["Different opening. Then more."])]:
    while not sp.q.empty():
        sp.q.get()
    sp.show_and_say_rest(full, first)
    got = []
    while not sp.q.empty():
        got.append(sp.q.get())
    check(got == want, f"rest after {first!r}: {got}")
print("all passed" if not bad else f"{bad} failed")
