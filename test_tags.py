"""Checks for place_tags / strip_tags / Catchy OS."""
from eve import place_tags, strip_tags, speech_text
CASES = [
    ("[Sigh] I have bad news. Frank's job failed.", "I have bad news. [Sigh] Frank's job failed."),
    ("Done! [laughter] That was quick.", "Done! [Laughter] That was quick."),
    ("Oh. [Laughter] Wow. [Sigh] Fine. [Laughter] Okay.", "Oh. [Laughter] Wow. [Sigh] Fine. Okay."),
    ("Check [Giggle] this.", "Check this."),
    ("[Sigh]", ""),
    ("No tags here.", "No tags here."),
]
bad = 0
for src, want in CASES:
    got = place_tags(src); ok = got == want; bad += not ok
    print("ok  " if ok else "FAIL", repr(got), "" if ok else f"want {want!r}")
for src, want in [("I have bad news. [Sigh] Frank's job failed.", "I have bad news. Frank's job failed."),
                  ("[Laughter] Hi.", "Hi.")]:
    got = strip_tags(src); ok = got == want; bad += not ok
    print("ok  " if ok else "FAIL", "strip", repr(got))
got = speech_text("The disk on cachyos is full, CachyOS says."); print("ok  " if got.count("Catchy OS") == 2 else "FAIL", repr(got)); bad += got.count("Catchy OS") != 2
print("all passed" if not bad else f"{bad} failed")
