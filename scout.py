"""Lead scout. Finds PUBLIC posts from people who seem to need advertising, scores them with the free AI chain, drafts a helpful
reply, saves them to mamachi_leads and sends the best few to you on Telegram. YOU send the reply by hand: no automated replies to
strangers, no DMs, no scraping of private data. Run it from its own GitHub Action (see SALES-AGENTS.md), at most once or twice a day."""
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

import requests

log = logging.getLogger(__name__)
SITE = (os.environ.get("SITE_URL") or "https://mamachiad.github.io/mamachi-ad-engine").rstrip("/")
QUERIES = ["how do I promote my book", "need marketing help", "how to advertise my small business", "launching my product soon", "need more customers", "self published author marketing"]
TAGS = ["selfpublishing", "authors", "writingcommunity", "smallbusiness", "indieauthor", "startups"]
MIN_SCORE = int(os.environ.get("LEAD_MIN_SCORE", "60"))
MAX_LEADS = int(os.environ.get("MAX_LEADS_PER_RUN", "8"))


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def bluesky_posts(handle: str, password: str, pds: str = "https://bsky.social") -> List[Dict[str, str]]:
    s = requests.post(f"{pds}/xrpc/com.atproto.server.createSession", json={"identifier": handle, "password": password}, timeout=20)
    if s.status_code != 200:
        log.warning("Bluesky login failed for lead search (%s)", s.status_code)
        return []
    jwt, out = s.json()["accessJwt"], []
    for q in QUERIES:
        r = requests.get(f"{pds}/xrpc/app.bsky.feed.searchPosts", params={"q": q, "limit": 15, "sort": "latest"}, headers={"Authorization": f"Bearer {jwt}"}, timeout=20)
        for p in (r.json().get("posts", []) if r.status_code == 200 else []):
            h, rkey = p["author"]["handle"], p["uri"].rsplit("/", 1)[-1]
            out.append({"source": "bluesky", "url": f"https://bsky.app/profile/{h}/post/{rkey}", "author": h, "text": p["record"].get("text", "")})
    return out


def mastodon_posts(instance: str) -> List[Dict[str, str]]:
    out = []
    for t in TAGS:
        r = requests.get(f"{instance.rstrip('/')}/api/v1/timelines/tag/{t}", params={"limit": 15}, timeout=20)      # public hashtag timeline
        for p in (r.json() if r.status_code == 200 else []):
            out.append({"source": "mastodon", "url": p.get("url", ""), "author": p["account"]["acct"], "text": _strip(p.get("content", ""))})
    return out


def score(posts: List[Dict[str, str]], ask: Callable[[str], Optional[str]]) -> List[Dict[str, Any]]:
    batch = [{"i": i, "text": p["text"][:400]} for i, p in enumerate(posts[:40])]
    prompt = ("You help a small advertising service find people who are genuinely asking for help promoting a book, product or service. For each post give score 0-100 "
              "(100 = clearly asking how to get customers/promotion; 0 = unrelated, a joke, an ad, spam or an ad-agency). need = one short phrase. reply = a short, warm, USEFUL public reply "
              "in the SAME language as the post: give one concrete tip first, say you are from Mamachi Ads in one clause, never promise results, no pressure, under 260 characters. "
              f"Posts: {json.dumps(batch)}\nReturn ONLY JSON: {{\"results\":[{{\"i\":0,\"score\":0,\"need\":\"\",\"reply\":\"\"}}]}}")
    try:
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", (ask(prompt) or "").strip(), flags=re.M).strip())
    except Exception as e:
        log.warning("Scoring unavailable: %s", e)
        return []
    out = []
    for r in data.get("results", []):
        try:
            p = posts[int(r["i"])]
            if int(r["score"]) >= MIN_SCORE and r.get("reply"):
                out.append({**p, "score": int(r["score"]), "need": str(r.get("need", ""))[:80], "reply": " ".join(str(r["reply"]).split())[:300]})
        except (KeyError, ValueError, IndexError, TypeError):
            continue
    return sorted(out, key=lambda x: -x["score"])


def run(sb, ask: Callable[[str], Optional[str]], notify: Callable[[str], None], posts: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    known = {r["post_url"] for r in (sb.table("mamachi_leads").select("post_url").execute().data or [])}
    fresh = [p for p in posts if p["url"] and p["url"] not in known and len(p["text"]) > 25]
    seen_authors, uniq = set(), []
    for p in fresh:                                              # one lead per person per run
        if p["author"] not in seen_authors:
            seen_authors.add(p["author"]); uniq.append(p)
    top = score(uniq, ask)[:MAX_LEADS]
    for l in top:
        sb.table("mamachi_leads").insert({"source": l["source"], "post_url": l["url"], "author": l["author"], "text": l["text"][:500], "score": l["score"], "need": l["need"], "draft_reply": l["reply"]}).execute()
    if top:
        notify("Lead scout: %d people may need advertising. Open each post, reply yourself if it fits (edit the draft), then mark the lead 'sent' in Supabase.\n\n" % len(top) +
               "\n\n".join(f"{i}. [{l['score']}] {l['need']}\n{l['url']}\nDraft: {l['reply']}\nOffer link: {SITE}/advertise.html?unit=day&qty=1&geo=local&slot=feed" for i, l in enumerate(top, 1)))
    return top


if __name__ == "__main__":
    from supabase import create_client
    from ai_chain import ask_text
    logging.basicConfig(level=logging.INFO)
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    gem = os.environ.get("GEMINI_API_KEY")
    if gem:
        from google import genai
        client = genai.Client(api_key=gem)
        gcall, models = (lambda m, p: client.models.generate_content(model=m, contents=p).text), ["gemini-3.5-flash-lite", "gemini-2.5-flash"]
    else:
        gcall, models = (lambda m, p: ""), []
    ask = lambda prompt: ask_text(prompt, gcall, models, 90)[0]
    def tell(text: str) -> None:
        t, c = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        if t and c:
            requests.post(f"https://api.telegram.org/bot{t}/sendMessage", data={"chat_id": c, "text": text[:4000]}, timeout=20)
        else:
            print(text)
    posts = []
    if os.environ.get("BSKY_HANDLE") and os.environ.get("BSKY_APP_PASSWORD"):
        posts += bluesky_posts(os.environ["BSKY_HANDLE"], os.environ["BSKY_APP_PASSWORD"])
    if os.environ.get("MASTODON_INSTANCE"):
        posts += mastodon_posts(os.environ["MASTODON_INSTANCE"])
    print("leads:", len(run(sb, ask, tell, posts)))
