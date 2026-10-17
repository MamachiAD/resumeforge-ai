import json, os, sys, types
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import scout
class Q:
    def __init__(s, t, n): s.t, s.n, s.op, s.v = t, n, "select", None
    def select(s, *_): return s
    def insert(s, d): s.op, s.v = "insert", d; return s
    def execute(s):
        rows = s.t.setdefault(s.n, [])
        if s.op == "insert": rows.append(s.v); return types.SimpleNamespace(data=[s.v])
        return types.SimpleNamespace(data=list(rows))
class SB:
    def __init__(s): s.t = {"mamachi_leads": [{"post_url": "https://old"}]}
    def table(s, n): return Q(s.t, n)
posts = [
 {"source": "bluesky", "url": "https://bsky.app/a", "author": "ann", "text": "I just finished my first novel. How do I promote my book without a big budget?"},
 {"source": "bluesky", "url": "https://bsky.app/a2", "author": "ann", "text": "Second post from the same person asking about marketing help for novels."},
 {"source": "mastodon", "url": "https://m/b", "author": "bob", "text": "Lol my cat just knocked over my coffee again, what a morning to be alive"},
 {"source": "mastodon", "url": "https://old", "author": "cy", "text": "Already contacted this one earlier about advertising my small shop."},
 {"source": "bluesky", "url": "https://bsky.app/d", "author": "dee", "text": "Opening a bakery next month and I have no idea how to get customers through the door."}]
def ask(prompt):
    ids = {json.loads(prompt.split("Posts: ")[1].split("\nReturn")[0])[k]["i"]: json.loads(prompt.split("Posts: ")[1].split("\nReturn")[0])[k]["text"] for k in range(len(json.loads(prompt.split("Posts: ")[1].split("\nReturn")[0])))}
    res = [{"i": i, "score": 90 if ("promote" in t or "customers" in t) else 5, "need": "promotion", "reply": "Try a short video of the book. I'm from Mamachi Ads if you want help."} for i, t in ids.items()]
    return json.dumps({"results": res})
sb, sent = SB(), []
top = scout.run(sb, ask, sent.append, posts)
def ok(c, m): print(("PASS  " if c else "FAIL  ") + m); (c or sys.exit(1))
ok([l["author"] for l in top] == ["ann", "dee"], "1. Only genuine needs kept (ann, dee); the joke, the duplicate link and the second post by the same person are dropped")
ok(len(sb.t["mamachi_leads"]) == 3, "2. New leads saved for you; already-known posts are not saved twice")
ok(sent and "Draft:" in sent[0] and "https://bsky.app/a" in sent[0] and "advertise.html?unit=day" in sent[0], "3. You get the post link, a draft reply and a ready checkout link on Telegram")
ok(scout.score(posts, lambda p: "not json") == [], "4. If the AI is unavailable nothing is invented")
print("ALL PASSED")
