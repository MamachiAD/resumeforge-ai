"""Writes one web page per post and keeps docs/feed.json up to date.
Called by engine.py exactly like this:
    publish_web(title, body, short_link, tag_list, product_id, brand="Mamachi") -> live URL, or None on failure
The home page (docs/index.html) reads docs/feed.json, so no HTML has to be edited by hand.
"""
import datetime
import html
import json
import logging
import os
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)
DOCS = Path(os.environ.get("DOCS_DIR", "docs"))
SITE = os.environ.get("SITE_URL", "https://mamachiad.github.io/mamachi-ad-engine").rstrip("/")
E = lambda s: html.escape(str(s if s is not None else ""), quote=True)

PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} | {brand}</title><meta name="description" content="{desc}"><link rel="canonical" href="{url}">
<meta property="og:type" content="article"><meta property="og:title" content="{title}"><meta property="og:description" content="{desc}"><meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary"><meta name="twitter:title" content="{title}"><meta name="twitter:description" content="{desc}">
<script type="application/ld+json">{ld}</script>
<style>:root{{--bg:#020617;--card:#0f172a;--line:#1e293b;--mut:#94a3b8}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:#e2e8f0;font-family:Inter,system-ui,sans-serif;line-height:1.6}}
header{{border-bottom:1px solid var(--line);padding:14px 20px;display:flex;align-items:center;gap:10px;font-weight:800;font-size:1.15rem}}
header a{{color:#fff;text-decoration:none;display:flex;align-items:center;gap:10px}}.m{{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#0ea5e9,#6366f1,#ec4899);display:grid;place-items:center;color:#fff;font-weight:900}}
main{{max-width:680px;margin:0 auto;padding:28px 20px}}.back{{color:#38bdf8;font-size:.8rem;text-decoration:none;font-weight:700}}
h1{{font-size:1.9rem;line-height:1.2;margin:.6em 0 .3em;font-weight:900}}.date{{color:var(--mut);font-size:.8rem}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:24px;margin-top:20px}}.card p{{margin:0 0 18px;font-size:1.05rem}}
.btn{{display:inline-block;background:linear-gradient(90deg,#0ea5e9,#6366f1);color:#fff;text-decoration:none;font-weight:800;font-size:.8rem;letter-spacing:.06em;padding:13px 28px;border-radius:14px}}
.tags{{margin-top:16px;color:var(--mut);font-size:.8rem}}.tags span{{margin-right:8px}}</style></head><body>
<header><a href="../index.html"><span class="m">M</span>{brand}<span style="color:#0ea5e9">.</span></a></header>
<main><a class="back" href="../index.html">&larr; Back to feed</a><h1>{title}</h1><div class="date">{date}</div>
<div class="card"><p>{body}</p><a class="btn" href="{link}" rel="noopener">GET IT HERE &rarr;</a><div class="tags">{tags}</div></div></main></body></html>"""


def _read_feed(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def publish_web(title: str, body: str, link: str, tags: Optional[List[str]] = None,
                product_id=None, brand: str = "Mamachi") -> Optional[str]:
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        pid = now.strftime("%Y%m%d-%H%M%S")
        tags = [t.lstrip("#") for t in (tags or []) if t]
        url = f"{SITE}/posts/{pid}.html"
        desc = (body or "")[:200]
        ld = json.dumps({"@context": "https://schema.org", "@type": "Book", "name": title, "description": desc, "url": link})
        page = PAGE.format(title=E(title), brand=E(brand), desc=E(desc), url=E(url), ld=ld.replace("</", "<\\/"),
                           date=now.strftime("%b %d, %Y"), body=E(body), link=E(link),
                           tags="".join(f"<span>#{E(t)}</span>" for t in tags))
        (DOCS / "posts").mkdir(parents=True, exist_ok=True)
        (DOCS / "posts" / f"{pid}.html").write_text(page, encoding="utf-8")
        feed_path = DOCS / "feed.json"
        feed = _read_feed(feed_path)
        feed.insert(0, {"id": pid, "title": title, "body": body, "link": link, "tags": tags,
                        "product_id": product_id, "date": now.isoformat(timespec="seconds"), "url": f"posts/{pid}.html"})
        tmp = feed_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(feed[:300], indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(feed_path)
        logger.info("Web post written: %s", url)
        return url
    except Exception:
        logger.exception("Web publish failed")
        return None
