"""
Platform switchboard. A platform turns ON by itself when all of its secrets exist.
Missing secrets => status 'pending' (nothing breaks). Add a secret later and the next run uses it.
New: per-platform text variants, and paid-region filtering (an Africa-only ad is not posted on channels you tagged for other regions).
"""
import json
import os
import time
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


def env(key: str) -> str:
    return os.environ.get(key, "").strip().strip('"\'')


def dry_run() -> bool:
    return env("DRY_RUN").lower() in ("1", "true", "yes")


@dataclass
class Post:
    title: str
    body: str                    # plain text, no link
    link: str                    # tracked short link
    tags: List[str] = field(default_factory=list)
    video_path: Optional[str] = None
    video_url: Optional[str] = None   # public URL (needed by Instagram)
    product_id: object = None
    variants: Dict[str, str] = field(default_factory=dict)   # platform -> its own version of the text (paid ads with "unique" style)
    geo_level: str = "world"                                  # local | country | region | world
    geo_region: str = "Worldwide"

    @property
    def disclaimer_body(self) -> str:
        d = env("DISCLAIMER")
        return f"{self.body}\n\n{d}" if d else self.body

    @property
    def hashtags(self) -> str:
        return " ".join(f"#{t.lstrip('#')}" for t in self.tags[:5])


def region_allows(platform: str, geo_level: str, geo_region: str) -> bool:
    """PLATFORM_REGIONS example: {"telegram":["global"],"facebook":["africa"],"instagram":["africa","europe"]}.
    A platform that is not listed carries every ad. Worldwide ads go everywhere."""
    if geo_level == "world" or (geo_region or "").lower() == "worldwide":
        return True
    try:
        mapping = json.loads(env("PLATFORM_REGIONS") or "{}")
    except Exception:
        return True
    regions = [r.lower() for r in mapping.get(platform, [])]
    return not regions or "global" in regions or (geo_region or "").lower() in regions


URL_LEN = 23


def fit(body: str, link: str, limit: int) -> str:
    """body + link that fits a character limit where any link counts as 23 characters."""
    room = limit - URL_LEN - 1
    body = " ".join(body.split())
    if len(body) > room:
        body = body[: room - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return f"{body} {link}"


def _ok(r: requests.Response, name: str, good=(200, 201)) -> bool:
    if r.status_code in good:
        logger.info("Posted to %s", name)
        return True
    logger.error("%s error (%s): %s", name, r.status_code, r.text[:400])
    return False


# ----------------------------------------------------------------------------- platforms
def facebook(p: Post) -> bool:
    ver = env("FB_API_VERSION") or "v23.0"
    r = requests.post(f"https://graph.facebook.com/{ver}/{env('FB_PAGE_ID')}/feed",
                      data={"message": p.disclaimer_body, "link": p.link, "access_token": env("FB_PAGE_ACCESS_TOKEN")}, timeout=20)
    return _ok(r, "Facebook", (200,))


def linkedin(p: Post) -> bool:
    payload = {
        "author": env("LINKEDIN_AUTHOR_URN"), "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": {
            "shareCommentary": {"text": p.disclaimer_body}, "shareMediaCategory": "ARTICLE",
            "media": [{"status": "READY", "originalUrl": p.link}]}},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    r = requests.post("https://api.linkedin.com/v2/ugcPosts", json=payload, timeout=20, headers={
        "Authorization": f"Bearer {env('LINKEDIN_ACCESS_TOKEN')}", "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"})
    return _ok(r, "LinkedIn")


def x_twitter(p: Post) -> bool:
    # Needs an OAuth 2.0 USER token with tweet.write. An app-only bearer token cannot post.
    r = requests.post("https://api.twitter.com/2/tweets", json={"text": fit(p.body, p.link, 280)}, timeout=20,
                      headers={"Authorization": f"Bearer {env('X_BEARER_TOKEN')}", "Content-Type": "application/json"})
    return _ok(r, "X")


def telegram(p: Post) -> bool:
    tok, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    text = f"{p.disclaimer_body}\n\n{p.link}"
    if p.video_path and Path(p.video_path).exists() and Path(p.video_path).stat().st_size < 45_000_000:
        with open(p.video_path, "rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendVideo", timeout=120,
                              data={"chat_id": chat, "caption": text[:1024], "supports_streaming": "true"}, files={"video": f})
    else:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=20,
                          data={"chat_id": chat, "text": text[:4000]})
    return _ok(r, "Telegram", (200,))


def bluesky(p: Post) -> bool:
    pds = env("BSKY_PDS") or "https://bsky.social"
    s = requests.post(f"{pds}/xrpc/com.atproto.server.createSession", timeout=20,
                      json={"identifier": env("BSKY_HANDLE"), "password": env("BSKY_APP_PASSWORD")})
    if s.status_code != 200:
        logger.error("Bluesky login failed (%s): %s", s.status_code, s.text[:300])
        return False
    sess = s.json()
    body = " ".join(p.body.split())
    room = 300 - len(p.link) - 1
    if len(body) > room:
        body = body[: room - 1].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    text = f"{body} {p.link}"
    start = len(body.encode("utf-8")) + 1                       # facet offsets are in UTF-8 BYTES
    record = {
        "$type": "app.bsky.feed.post", "text": text, "langs": ["en"],
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "facets": [{"index": {"byteStart": start, "byteEnd": start + len(p.link.encode("utf-8"))},
                    "features": [{"$type": "app.bsky.richtext.facet#link", "uri": p.link}]}],
    }
    r = requests.post(f"{pds}/xrpc/com.atproto.repo.createRecord", timeout=20,
                      headers={"Authorization": f"Bearer {sess['accessJwt']}"},
                      json={"repo": sess["did"], "collection": "app.bsky.feed.post", "record": record})
    return _ok(r, "Bluesky")


def mastodon(p: Post) -> bool:
    r = requests.post(f"{env('MASTODON_INSTANCE').rstrip('/')}/api/v1/statuses", timeout=20,
                      headers={"Authorization": f"Bearer {env('MASTODON_TOKEN')}"},
                      data={"status": fit(p.body, p.link, 500) + (f"\n\n{p.hashtags}" if p.hashtags else ""), "visibility": "public"})
    return _ok(r, "Mastodon", (200,))


def discord(p: Post) -> bool:
    r = requests.post(env("DISCORD_WEBHOOK_URL"), timeout=20, json={"content": f"{p.body}\n{p.link}"[:1900]})
    return _ok(r, "Discord", (200, 204))


def instagram(p: Post) -> bool:
    """Reels via the Instagram Graph API. Needs a professional account linked to a Facebook Page and a PUBLIC video URL."""
    if not p.video_url:
        logger.warning("Instagram: no public video URL (create a public Supabase bucket, see ADD-PLATFORMS.md)")
        return False
    ver, uid, tok = env("FB_API_VERSION") or "v23.0", env("IG_USER_ID"), env("IG_ACCESS_TOKEN")
    base = f"https://graph.facebook.com/{ver}"
    c = requests.post(f"{base}/{uid}/media", timeout=30, data={
        "media_type": "REELS", "video_url": p.video_url, "share_to_feed": "true",
        "caption": f"{p.body}\n\n{p.link}\n\n{p.hashtags}".strip(), "access_token": tok})
    if c.status_code != 200:
        logger.error("Instagram container error (%s): %s", c.status_code, c.text[:400])
        return False
    cid = c.json()["id"]
    for _ in range(40):                                          # wait up to ~6 minutes for processing
        st = requests.get(f"{base}/{cid}", params={"fields": "status_code", "access_token": tok}, timeout=20).json()
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            logger.error("Instagram processing failed: %s", st)
            return False
        time.sleep(9)
    else:
        logger.error("Instagram processing timed out")
        return False
    r = requests.post(f"{base}/{uid}/media_publish", data={"creation_id": cid, "access_token": tok}, timeout=30)
    return _ok(r, "Instagram", (200,))


def youtube(p: Post) -> bool:
    if not p.video_path:
        return False
    import video_engine
    video_engine.YOUTUBE_ENABLED = True
    return bool(video_engine.post_to_youtube_shorts(p.video_path, p.title, f"{p.body}\n\n{p.link}", tags=p.tags))


@dataclass
class Platform:
    name: str
    needs: List[str]
    fn: Callable[[Post], bool]
    needs_video: bool = False

    def missing(self) -> List[str]:
        return [k for k in self.needs if not env(k)]


REGISTRY: List[Platform] = [
    Platform("telegram", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"], telegram),
    Platform("bluesky", ["BSKY_HANDLE", "BSKY_APP_PASSWORD"], bluesky),
    Platform("mastodon", ["MASTODON_INSTANCE", "MASTODON_TOKEN"], mastodon),
    Platform("discord", ["DISCORD_WEBHOOK_URL"], discord),
    Platform("facebook", ["FB_PAGE_ID", "FB_PAGE_ACCESS_TOKEN"], facebook),
    Platform("instagram", ["IG_USER_ID", "IG_ACCESS_TOKEN"], instagram, needs_video=True),
    Platform("youtube", ["YOUTUBE_TOKEN_JSON"], youtube, needs_video=True),
    Platform("linkedin", ["LINKEDIN_ACCESS_TOKEN", "LINKEDIN_AUTHOR_URN"], linkedin),
    Platform("x", ["X_BEARER_TOKEN"], x_twitter),
]
# TikTok has no automatic posting here (its posting API needs app review): a ready-to-upload package is made instead.


def is_active(name: str) -> bool:
    return any(p.name == name and not p.missing() for p in REGISTRY)


def publish_all(post: Post) -> Dict[str, Tuple[str, str]]:
    """Returns {platform: (status, detail)}. status: posted | failed | pending | skipped | disabled | dry-run"""
    disabled = {x.strip().lower() for x in env("DISABLE_PLATFORMS").split(",") if x.strip()}
    out: Dict[str, Tuple[str, str]] = {}
    for pl in REGISTRY:
        miss = pl.missing()
        if pl.name in disabled:
            out[pl.name] = ("disabled", "DISABLE_PLATFORMS")
        elif miss:
            out[pl.name] = ("pending", "add secrets: " + ", ".join(miss))
        elif not region_allows(pl.name, post.geo_level, post.geo_region):
            out[pl.name] = ("skipped", f"outside paid region ({post.geo_region})")
        elif pl.needs_video and not (post.video_path or post.video_url):
            out[pl.name] = ("skipped", "no video this run")
        elif dry_run():
            out[pl.name] = ("dry-run", "would post")
        else:
            try:
                version = replace(post, body=post.variants[pl.name]) if post.variants.get(pl.name) else post
                out[pl.name] = ("posted", "") if pl.fn(version) else ("failed", "see log above")
            except Exception as e:
                logger.exception("%s crashed: %s", pl.name, e)
                out[pl.name] = ("failed", str(e)[:120])
    return out


def write_summary(statuses: Dict[str, Tuple[str, str]], extra: Optional[Dict[str, str]] = None) -> None:
    rows = {**statuses, **(extra or {})}
    icon = {"posted": "✅", "failed": "❌", "pending": "⏳", "skipped": "➖", "disabled": "🚫", "dry-run": "🧪", "manual": "✋"}
    lines = ["## Platform status", "", "| Platform | Status | Detail |", "|---|---|---|"]
    lines += [f"| {k} | {icon.get(v[0], '')} {v[0]} | {v[1]} |" for k, v in rows.items()]
    text = "\n".join(lines)
    logger.info("\n%s", text)
    path = env("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
