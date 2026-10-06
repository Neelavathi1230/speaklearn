"""Modular local NLP pipeline (no external services). Each function is replaceable."""
import re, random, math
from collections import Counter
STOP = set("a an the and or but if of to in on at for with by from as is are was were be been being it its this that these those i we you they he she them our your their there here so than then not no do does did have has had will would can could should may might about into over also just very more most some such what which who how when where why one two three".split())
DEF = re.compile(r"^(.{3,60}?)\s+(is|are|refers to|means|is defined as|can be defined as)\s+(an?|the)?\s*(.{15,})$", re.I)

def clean(t): return re.sub(r"\s+", " ", re.sub(r"\b(um+|uh+|you know)\b[,]?", "", t, flags=re.I)).strip()
def sentences(t): return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", t) if len(s.split()) >= 4]
def tokens(t): return [w for w in re.findall(r"[a-zA-Z][a-zA-Z'-]+", t.lower()) if w not in STOP and len(w) > 2]

def keywords(t, n=20):
    toks = tokens(t); out = dict(Counter(toks))
    for b, v in Counter(f"{a} {b}" for a, b in zip(toks, toks[1:])).items():
        if v >= 2: out[b] = v * 1.8
    return [(w, round(s, 1)) for w, s in sorted(out.items(), key=lambda x: -x[1])[:n]]

def score_sentences(t):
    ss = sentences(t); kw = dict(keywords(t, 40))
    return ss, [(sum(kw.get(w, 0) for w in tokens(s)) / math.sqrt(len(s.split())), i, s) for i, s in enumerate(ss)]

def _pick(sc, k): return [s for _, _, s in sorted(sorted(sc, reverse=True)[:k], key=lambda x: x[1])]
def summarize(t):
    _, sc = score_sentences(t); return {"short": " ".join(_pick(sc, 2)), "medium": " ".join(_pick(sc, 5)), "detailed": " ".join(_pick(sc, 9))}
def key_points(t, n=8): return _pick(score_sentences(t)[1], n)

def definitions(t):
    out = []
    for s in sentences(t):
        m = DEF.match(s.rstrip(".!?"))
        if m and m.group(1).lower().split()[0] not in STOP: out.append((m.group(1).strip(), s))
    return out

def topics(t, n=8):
    kw = keywords(t, n); tot = sum(s for _, s in kw) or 1
    return [(w.title(), round(s / tot, 3)) for w, s in kw]

def questions(t, n=12):
    out = [{"question": f"What is {d}?", "answer": s, "type": "short"} for d, s in definitions(t)]
    kws = [w for w, _ in keywords(t, 30) if " " not in w]
    for s in key_points(t, 12):
        words = [w for w in re.findall(r"[A-Za-z]+", s) if w.lower() in kws]
        if not words or len(kws) < 4: continue
        a = words[0]; opts = [a] + random.sample([k for k in kws if k.lower() != a.lower()], 3); random.shuffle(opts)
        out.append({"question": re.sub(a, "_____", s, count=1, flags=re.I), "answer": a, "type": "mcq", "options": opts, "explanation": s})
    return out[:n]

def flashcards(t):
    ss = sentences(t); cards = [(f"What is {d}?", s) for d, s in definitions(t)]
    cards += [(f"Explain: {w}", next((s for s in ss if w.split()[0] in s.lower()), "")) for w, _ in keywords(t, 6)]
    return [c for c in cards if c[1]][:12]

def notes(t):
    out = []; ss = sentences(t)
    for name, _ in topics(t, 5):
        rel = [s for s in ss if name.lower().split()[0] in s.lower()][:4]
        if not rel: continue
        d = next((s for s in rel if DEF.match(s.rstrip('.'))), None)
        out.append(f"TOPIC: {name}\n" + (f"Definition: {d}\n" if d else "") + "Key points:\n" + "\n".join("• " + s for s in rel))
    return "\n\n".join(out)

def stats(t, duration):
    w = len(t.split()); return {"words": w, "wpm": round(w / (duration / 60), 1) if duration else None, "sentences": len(sentences(t)), "keywords": len(keywords(t, 60))}
