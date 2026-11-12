"""Build a long fake Eve session (~135K tokens) with planted facts, in a separate test workspace."""
import json
import pathlib
import sys
import time

WS = pathlib.Path(sys.argv[1])
DOCS = pathlib.Path("docs")  # any folder of prose .md files
TURNS = int(sys.argv[2]) if len(sys.argv) > 2 else 46
CHUNK = 11500  # characters of doc text per tool result, about 2.9K tokens

paras = []
for f in sorted(DOCS.rglob("*.md*")):
    for p in f.read_text(encoding="utf-8", errors="ignore").split("\n\n"):
        if len(p.strip()) > 80:
            paras.append(p.strip())
text = "\n\n".join(paras)

FACTS = {
    2: "Remember this: the spare key is under the blue flowerpot by the back door.",
    8: "For the record, Frank's job 7 was the BSR invoice fix, and it's finished.",
    15: "My dentist appointment moved to Thursday at 3 in the afternoon.",
    40: "The guest Wi-Fi password is tangerine42.",
}

(WS / "sessions").mkdir(parents=True, exist_ok=True)
path = WS / "sessions" / "20261108-120000.jsonl"
pos = 0
with open(path, "w", encoding="utf-8") as f:
    def w(m):
        f.write(json.dumps({**m, "ts": round(time.time())}, ensure_ascii=False) + "\n")
    for t in range(TURNS):
        if t in FACTS:
            w({"role": "user", "content": FACTS[t]})
            w({"role": "assistant", "content": "Got it, I'll remember that."})
        doc = f"notes\\doc{t:02d}.md"
        w({"role": "user", "content": f"Read {doc} and tell me what it's about."})
        call = {"type": "function", "id": f"call{t}", "function": {"name": "read_file",
                                                                  "arguments": json.dumps({"path": doc})}}
        w({"role": "assistant", "content": "Reading it now.", "tool_calls": [call]})
        w({"role": "tool", "tool_call_id": f"call{t}", "content": text[pos:pos + CHUNK]})
        pos += CHUNK
        w({"role": "assistant", "content": f"It's part of the Hermes documentation, section {t + 1}. "
                                           f"It covers configuration and agent behavior."})
print(path, path.stat().st_size, "bytes")
