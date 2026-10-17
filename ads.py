"""Paid advertiser orders for the live engine: what is due now, posting rules, vendor emails, tracking rows, refunds, renewals.
The engine calls this next to its own product rotation. Orders live in Supabase table mamachi_orders (see supabase.sql)."""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

log = logging.getLogger(__name__)


def _env(k: str) -> str:
    return os.environ.get(k, "").strip().strip('"\'')


def now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


SITE = (_env("SITE_URL") or "https://mamachiad.github.io/mamachi-ad-engine").rstrip("/")
MAX_ADS_PER_RUN = int(_env("MAX_ADS_PER_RUN") or 8)


def own_slot_hours() -> set:
    return {int(x) for x in (_env("OWN_SLOT_HOURS") or "0").split(",") if x.strip().isdigit()}


def worker(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    base = _env("WORKER_BASE_URL")
    if not base:
        return {}
    try:
        r = requests.post(base.rstrip("/") + path, json=body, headers={"Authorization": "Bearer " + _env("NOTIFY_SECRET")}, timeout=25)
        return r.json()
    except Exception as e:
        log.warning("Worker %s failed: %s", path, e)
        return {}


def track_link(a: Dict[str, Any]) -> str:
    return f"{SITE}/track.html?id={a['id']}&token={a.get('manage_token', '')}"


def email(a: Dict[str, Any], subject: str, text: str) -> None:
    worker("/notify-vendor", {"orderId": a["id"], "subject": subject, "text": text})


# ----------------------------------------------------------------------------- which ads are due right now
def _update(sb, a: Dict[str, Any], **fields) -> None:
    a.update(fields)
    sb.table("mamachi_orders").update(fields).eq("id", a["id"]).execute()


def finish(sb, a: Dict[str, Any], reason: str = "finished") -> None:
    _update(sb, a, status="completed")
    worker("/social/revoke", {"campaignId": a["id"]})            # delete the buyer's stored accounts
    lines = [f"Your campaign \"{a['product_title']}\" has {reason}.", f"Posts published: {a['posts_total'] - max(a.get('posts_remaining') or 0, 0)} of {a['posts_total']}.",
             f"See every post and your link clicks: {track_link(a)}"]
    if a.get("renew_reminder") and not a.get("renewal_sent"):
        lines.append(f"Run it again with 10% off: {SITE}/advertise.html?unit={a['unit']}&qty={a['qty']}&geo={a['geo_level']}&slot={a['placement']}&renew={a['id']}")
        _update(sb, a, renewal_sent=True)
    email(a, f"Your Mamachi campaign has {reason}", "\n\n".join(lines))


def ads_due(sb, when: Optional[datetime] = None) -> List[Dict[str, Any]]:
    when = when or now()
    rows = sb.table("mamachi_orders").select("*").eq("status", "approved").execute().data or []
    due = []
    for a in rows:
        if not a.get("starts_at"):                                  # the paid period starts when the ad goes live, not when it was paid
            _update(sb, a, starts_at=when.isoformat(), ends_at=(when + timedelta(hours=float(a["hours"]))).isoformat())
        if when >= _parse(a["ends_at"]) or (a.get("posts_remaining") or 0) <= 0:
            finish(sb, a)
            continue
        if a.get("own_social") and not a.get("social_activated"):
            worker("/social/activate", {"campaignId": a["id"], "endsAt": a["ends_at"], "maxPosts": a["posts_remaining"]})
            _update(sb, a, social_activated=True)
        hours = {int(x) for x in str(a.get("ad_hours") or "12").split(",") if x.strip().isdigit()}
        if _env("ADS_IGNORE_HOURS") != "1" and when.hour not in hours:
            continue
        today = when.strftime("%Y-%m-%d")
        if a.get("day_key") == today and (a.get("day_count") or 0) >= a["posts_per_day"]:
            continue
        if a.get("last_posted_at") and _parse(a["last_posted_at"]).strftime("%Y%m%d%H") == when.strftime("%Y%m%d%H"):
            continue                                                # already posted in this hour (manual re-run)
        due.append(a)
    due.sort(key=lambda a: a.get("last_posted_at") or "")
    return due[:MAX_ADS_PER_RUN]


def is_own_slot(when: Optional[datetime] = None) -> bool:
    return (when or now()).hour in own_slot_hours()


# ----------------------------------------------------------------------------- turning an order into a post
def ad_to_product(a: Dict[str, Any]) -> Dict[str, Any]:
    dest = a["destination_url"]
    dest += ("&" if "?" in dest else "?") + f"utm_source=mamachi&utm_medium=social&utm_campaign={a['id'][:8]}"   # one short link per order = clean click counts
    return {"product_title": a["product_title"], "destination_url": dest, "manuscript_text": a.get("summary") or "", "hashtags": a.get("hashtags") or "",
            "product_id": None, "_ad": a}


def sponsored(body: str) -> str:
    return body if body.lower().startswith("sponsored") else f"Sponsored: {body}"


def ad_tags(tags: List[str]) -> List[str]:
    return tags if "ad" in [t.lower() for t in tags] else tags + ["ad"]


def generate_variants(ask: Callable[[str], Optional[str]], title: str, body: str, platforms: List[str]) -> Dict[str, str]:
    """One AI call -> a genuinely different version per platform. Falls back to {} (same text everywhere) on any problem."""
    prompt = ("Rewrite this promotional post so each platform gets a genuinely different version (different opening, angle and length). Keep the same facts, add no new claims, "
              "promise no income or results, plain text, no links, no hashtags, no Markdown.\n"
              f"Title: {title}\nPost: {body}\nPlatforms: {', '.join(platforms)}\n"
              'Return ONLY JSON like {"telegram": "...", "bluesky": "..."}. Length limits: x 200 characters, bluesky 220, everything else 400.')
    try:
        text = ask(prompt)
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip())
        out = {k: " ".join(v.replace("*", "").split()) for k, v in data.items() if k in platforms and isinstance(v, str) and v.strip()}
        return {k: (sponsored(v)) for k, v in out.items()}
    except Exception as e:
        log.warning("Variants unavailable (%s). Using the same text everywhere.", e)
        return {}


# ----------------------------------------------------------------------------- after a post
def record_post(sb, a: Dict[str, Any], short_data: Dict[str, Any], posted: List[str], text: str, media_url: Optional[str]) -> None:
    when = now()
    sb.table("mamachi_ad_posts").insert({"order_id": a["id"], "platforms": ",".join(posted), "short_url": short_data.get("short_url"), "shortio_id": short_data.get("shortio_id")}).execute()
    today = when.strftime("%Y-%m-%d")
    count = (a.get("day_count") or 0) + 1 if a.get("day_key") == today else 1
    remaining = max((a.get("posts_remaining") or 1) - 1, 0)
    _update(sb, a, posts_remaining=remaining, day_key=today, day_count=count, last_posted_at=when.isoformat())
    own = {}
    if a.get("own_social"):
        own = worker("/social/publish", {"campaignId": a["id"], "text": text, "link": short_data.get("short_url"), "mediaUrl": media_url or ""})
    mine = ", ".join(r["platform"] for r in own.get("results", []) if r.get("ok"))
    email(a, f"Your ad was just posted: {a['product_title']}",
          f"Your ad went live on: {', '.join(posted) or 'our site'}.\n" + (f"Also posted on your own accounts: {mine}.\n" if mine else "") +
          f"Posts left: {remaining} of {a['posts_total']}.\nTrack posts and link clicks: {track_link(a)}")
    if remaining == 0:
        finish(sb, a, "used all its posts")


def process_rejections(sb) -> None:
    """Orders you set to 'rejected' are refunded automatically, once."""
    for a in sb.table("mamachi_orders").select("*").eq("status", "rejected").execute().data or []:
        if a.get("refunded_at") or not a.get("paypal_capture_id"):
            continue
        if worker("/refund", {"captureId": a["paypal_capture_id"]}).get("ok"):
            _update(sb, a, refunded_at=now().isoformat())
            email(a, "Your Mamachi ad was not approved", f"We could not approve \"{a['product_title']}\", so your payment has been refunded in full.")
        else:
            log.error("Refund failed for %s. Refund it by hand in PayPal.", a["id"])
