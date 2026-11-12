"""Checks for speech_text(): what Eve says vs what she shows."""
from eve import speech_text

CASES = [
    (r"The actual user install at C:\Users\someone\AppData\Local\Programs\Python\Python312 is Python 3.12.10.",
     "The actual user install at the Python312 folder is Python 3.12.10."),
    (r"The default python lives in C:\Users\someone\AppData\Local\hermes\tools\python-3.14.9+20261021-win32-x64.",
     "The default python lives in this folder."),
    ("The largest folder in /mnt/models is /mnt/models/diffusion at 614 GB, then /mnt/models/llm at 369 GB.",
     "The largest folder in the models folder is the diffusion folder at 614 GB, then the llm folder at 369 GB."),
    ("It's in /mnt/models.", "It's in the models folder."),
    (r"I wrote the brief to C:\Users\someone\eve\workspace\handoffs\20261108-163232-job1.md.",
     "I wrote the brief to this file."),
    ("Frank changed /home/someone/voice-test/ming-server.json.", "Frank changed the ming server JSON file."),
    ("The log is ~/eve/workspace/eve.log.", "The log is the eve log file."),
    ("Everything is on C:\\ right now.", "Everything is on the C drive right now."),
    ("Frank's build is 3.14.9+20261021 now.", "Frank's build is the version on screen now."),
    ("Commit 2bd378ed1b is live.", "Commit the hash on screen is live."),
    ("The server is at 203.0.113.10:8085.", "The server is at the address on screen."),
    ("See https://hf.co/LiquidAI/LFM3-1.7B for details.", "See the link for details."),
    ("Both C:\\a\\2026-11-08-a1.txt, C:\\c\\2026-11-08-b2.txt and C:\\e\\2026-11-08-c3.txt changed.",
     "Both these files changed."),
    ("You have 99 GB free on C: and 1027 GB on S:.", "You have 99 GB free on C: and 1027 GB on S:."),
    ("Use either and/or, it's 1/2 done.", "Use either and/or, it's 1/2 done."),
    ("Version 4.2 is fine.", "Version 4.2 is fine."),
    ("The file frank_api_key is set.", "The file frank api key is set."),
]
bad = 0
for src, want in CASES:
    got = speech_text(src)
    ok = got == want
    bad += not ok
    print(("ok  " if ok else "FAIL"), repr(got) + ("" if ok else f"\n      want {want!r}"))
print("all passed" if not bad else f"{bad} failed")
