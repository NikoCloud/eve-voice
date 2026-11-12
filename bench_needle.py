"""Needle-in-a-haystack + deep-context speed test for Eve's LFM3 server.

Haystack: real prose (Hermes docs). For each context length:
  - single: one fact hidden at 10%, 50%, 90% depth
  - decoy:  the same fact plus two near-identical decoys elsewhere
  - decode: a 200-word summary, to measure generation speed with that much context loaded
Prompt caching is off, so every prompt-processing number is a cold read.
"""
import json
import pathlib
import sys
import time
import urllib.request

URL = "http://203.0.113.10:8085"  # your cachyos address
DOCS = pathlib.Path("docs")  # any folder of prose .md files
LENGTHS = [8192, 32768, 65536, 131072, 258048]  # 258048 leaves room under 262144 for the question and answer
DEPTHS = [0.1, 0.5, 0.9]
NEEDLE = "The access code for the copper greenhouse is 58213."
DECOYS = ["The access code for the copper warehouse is 91746.", "The access code for the bronze greenhouse is 30482."]
QUESTION = "What is the access code for the copper greenhouse? Reply with only the number."
ANSWER = "58213"


def post(path, body, timeout=900):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ntok(text):
    return len(post("/tokenize", {"content": text})["tokens"])


# Paragraph pool from real docs, in a fixed order
paras = []
for f in sorted(DOCS.rglob("*.md*")):
    for p in f.read_text(encoding="utf-8", errors="ignore").split("\n\n"):
        p = p.strip()
        if len(p) > 80 and not p.startswith(("```", "|", "import ", "<")):
            paras.append(p)
sample = "\n\n".join(paras[:400])
ratio = len(sample) / ntok(sample)  # chars per token
print(f"{len(paras)} paragraphs, {ratio:.2f} chars/token", flush=True)


def haystack(tokens, inserts):
    """Paragraphs up to about `tokens`, with (depth, sentence) inserts placed at paragraph boundaries."""
    want_chars = int(tokens * ratio)
    out, size, i = [], 0, 0
    while size < want_chars:
        p = paras[i % len(paras)]
        out.append(p)
        size += len(p) + 2
        i += 1
    for depth, sentence in sorted(inserts, reverse=True):
        out.insert(int(len(out) * depth), sentence)
    return "\n\n".join(out)


def fit(tokens, inserts):
    """Shrink the haystack until the whole prompt fits the target."""
    target = tokens
    for _ in range(6):
        h = haystack(target, inserts)
        n = ntok(h)
        if n <= tokens:
            return h, n
        target = int(target * tokens / n * 0.995)
    return h, n


def ask(context, question, max_tokens):
    body = {"messages": [{"role": "system", "content": "Answer questions about the document the user provides."},
                         {"role": "user", "content": f"{context}\n\n---\n\n{question}"}],
            "temperature": 0, "max_tokens": max_tokens, "cache_prompt": False,
            "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.perf_counter()
    d = post("/v1/chat/completions", body)
    wall = time.perf_counter() - t0
    return d["choices"][0]["message"].get("content") or "", d.get("timings", {}), wall


def recheck(cases, max_tokens=48):
    """Re-run specific (length, depth) decoy cases with a longer answer budget, five times each."""
    for L, depth in cases:
        inserts = [(depth, NEEDLE), ((depth + 0.33) % 1.0, DECOYS[0]), ((depth + 0.66) % 1.0, DECOYS[1])]
        ctx, n = fit(L, inserts)
        ans, t, wall = ask(ctx, QUESTION, max_tokens)
        ok = ANSWER in ans and not any(x in ans for x in ("91746", "30482"))
        print(f"{L:>7} decoy depth={depth:.1f} ok={ok} answer={ans.strip()!r}", flush=True)


if len(sys.argv) > 1 and sys.argv[1] == "recheck":
    recheck([(8192, 0.5), (32768, 0.5), (32768, 0.9), (131072, 0.1), (131072, 0.5)])
    sys.exit()

results = []
for L in LENGTHS:
    row = {"len": L, "single": [], "decoy": [], "pp": [], "tg": None}
    for depth in DEPTHS:
        for kind in ("single", "decoy"):
            inserts = [(depth, NEEDLE)]
            if kind == "decoy":
                inserts += [((depth + 0.33) % 1.0, DECOYS[0]), ((depth + 0.66) % 1.0, DECOYS[1])]
            ctx, n = fit(L, inserts)
            ans, t, wall = ask(ctx, QUESTION, 16)
            ok = ANSWER in ans and not any(x in ans for x in ("91746", "30482"))
            row[kind].append(ok)
            row["pp"].append(t.get("prompt_per_second", 0))
            print(f"{L:>7} {kind:6} depth={depth:.1f} tokens={n} ok={ok} answer={ans.strip()[:30]!r} "
                  f"pp={t.get('prompt_per_second', 0):.0f} t/s wall={wall:.1f}s", flush=True)
    ctx, n = fit(L, [])
    _, t, wall = ask(ctx, "Summarize the document above in about 200 words.", 300)
    row["tg"] = t.get("predicted_per_second", 0)
    row["tg_n"] = t.get("predicted_n", 0)
    print(f"{L:>7} decode: {row['tg']:.1f} t/s over {row['tg_n']} tokens (wall {wall:.1f}s)", flush=True)
    results.append(row)

print("\nlength  single  decoy   prompt t/s  decode t/s")
for r in results:
    pp = sum(r["pp"]) / len(r["pp"])
    print(f"{r['len']:>7}  {sum(r['single'])}/3     {sum(r['decoy'])}/3     {pp:>8.0f}    {r['tg']:>7.1f}")
json.dump(results, open(pathlib.Path(__file__).with_name("bench_needle_results.json"), "w"), indent=1)
