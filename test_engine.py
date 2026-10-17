"""End-to-end test of the live engine with fake Supabase, Gemini, video, Short.io, Telegram and worker. Run: python3 tests/test_engine.py"""
import json, os, sys, types, tempfile
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.update(SUPABASE_URL="https://x", SUPABASE_KEY="k", SHORTIO_API_KEY="s", GEMINI_API_KEY="g", TELEGRAM_BOT_TOKEN="BOT", TELEGRAM_CHAT_ID="1",
                  WORKER_BASE_URL="https://w.test", NOTIFY_SECRET="sec", DOCS_DIR=tempfile.mkdtemp(), SITE_URL="https://site.test")

class Q:
    def __init__(s, db, name): s.db, s.name, s.f, s.op, s.val = db, name, [], "select", None
    def select(s, *_): return s
    def eq(s, c, v): s.f.append((c, v)); return s
    def order(s, *a, **k): return s
    def limit(s, n): return s
    def update(s, d): s.op, s.val = "update", d; return s
    def insert(s, d): s.op, s.val = "insert", d; return s
    def execute(s):
        rows = s.db.t.setdefault(s.name, [])
        hit = [r for r in rows if all(r.get(c) == v for c, v in s.f)]
        if s.op == "insert": rows.append(dict(s.val, id=len(rows) + 1)); return types.SimpleNamespace(data=[rows[-1]])
        if s.op == "update": [r.update(s.val) for r in hit]; return types.SimpleNamespace(data=hit)
        return types.SimpleNamespace(data=[dict(r) for r in hit])
class FakeSB:
    def __init__(s): s.t = {}
    def table(s, n): return Q(s, n)
fake = FakeSB()
sup = types.ModuleType("supabase"); sup.Client = FakeSB; sup.create_client = lambda *a: fake; sys.modules["supabase"] = sup
ai_calls = []
class Models:
    def generate_content(s, model, contents):
        ai_calls.append(contents)
        if "Platforms:" in contents: return types.SimpleNamespace(text='```json\n{"telegram": "A fresh, different take for Telegram readers.", "discord": "Discord version, other angle."}\n```')
        return types.SimpleNamespace(text="Fresh roasted coffee, delivered weekly. Taste the difference.")
g = types.ModuleType("google"); ga = types.ModuleType("google.genai"); gt = types.ModuleType("google.genai.types")
ga.Client = lambda **k: types.SimpleNamespace(models=Models()); gt.HttpOptions = lambda **k: None; ga.types = gt; g.genai = ga
sys.modules.update({"google": g, "google.genai": ga, "google.genai.types": gt})
ve = types.ModuleType("video_engine"); ve.generate_short_video = lambda *a, **k: None; ve.prepare_tiktok_package = ve.prepare_instagram_package = lambda *a, **k: False; sys.modules["video_engine"] = ve

import requests
calls = []
class Resp:
    def __init__(s, j=None, code=200): s._j, s.status_code, s.text, s.headers = j or {}, code, "", {}
    def json(s): return s._j
def fake_post(url, **kw):
    calls.append((url, kw))
    if "api.short.io" in url: return Resp({"secureShortURL": "https://mamachi-engine.s.gy/" + str(len(calls)), "idString": "lnk" + str(len(calls))}, 200)
    if "api.telegram.org" in url: return Resp({}, 200)
    if "w.test" in url: return Resp({"ok": True, "results": [{"platform": "bluesky", "ok": True}]})
    return Resp({}, 200)
requests.post = fake_post
import ads, engine, platforms
def at(h, d=15): ads.now = lambda: datetime(2026, 10, d, h, 0, tzinfo=timezone.utc)
fails = 0
def ok(c, m):
    global fails; print(("PASS  " if c else "FAIL  ") + m); fails += 0 if c else 1
def worker_calls(path): return [kw["json"] for u, kw in calls if u == "https://w.test" + path]

def order(**o):
    base = dict(id="11111111-aaaa-bbbb-cccc-000000000001", status="approved", vendor_email="a@b.co", manage_token="tok123", product_title="Sunrise Coffee", destination_url="https://sunrise-coffee.com/shop",
                summary="Fresh roasted coffee weekly.", language="English", hashtags="#coffee", unit="day", qty=2, geo_level="world", geo_region="Worldwide", placement="social", hours=48, posts_per_day=2,
                posts_total=4, posts_remaining=4, ad_hours="6,18", variation="unique", own_social=False, social_activated=False, starts_at=None, ends_at=None, last_posted_at=None, day_key=None, day_count=0, renew_reminder=True)
    base.update(o); return base
fake.t["mamachi_orders"] = [order()]
fake.t["mamachi_products"] = [dict(product_id=7, product_title="SI, Super Intelligence Super Wealth", destination_url="https://amazon.com/dp/si", manuscript_text="A book", is_active=True, hashtags="#SuperIntelligence")]

at(7); ok(ads.ads_due(fake) == [], "1. Order approved at 07:00 is NOT due (it posts at 06:00 and 18:00 UTC)")
o = fake.t["mamachi_orders"][0]; ok(o["starts_at"] and o["ends_at"], "2. The paid period starts when the ad goes live, not when it was paid")
at(6); ok(len(ads.ads_due(fake)) == 1, "3. At 06:00 UTC the ad is due")

calls.clear(); ai_calls.clear(); ok(engine.run_campaign() is True, "4. A 06:00 run posts the paid ad")
tg = [kw["data"]["text"] for u, kw in calls if "sendMessage" in u]
ok(tg and tg[0].startswith("Sponsored: A fresh, different take for Telegram readers."), "5. Telegram got its OWN version, labelled Sponsored: " + (tg[0][:70] if tg else "none"))
ok(len(ai_calls) == 2, "6. Two AI calls only (one promo, one set of variants): " + str(len(ai_calls)))
o = fake.t["mamachi_orders"][0]; ok(o["posts_remaining"] == 3 and o["day_count"] == 1, "7. Posts left 4 -> 3, day count 1")
ok(len(fake.t["mamachi_ad_posts"]) == 1 and "telegram" in fake.t["mamachi_ad_posts"][0]["platforms"] and "web" in fake.t["mamachi_ad_posts"][0]["platforms"], "8. Post recorded for the vendor's tracking page")
mail = worker_calls("/notify-vendor"); ok(mail and "track.html?id=11111111" in mail[0]["text"] and "tok123" in mail[0]["text"] and "Posts left: 3 of 4" in mail[0]["text"], "9. Vendor emailed with their tracking link and posts left")
ok("campaign_logs" not in str(fake.t.keys()), "10. Your own campaign log is untouched by paid ads")
ok(not any("amazon.com" in str(kw) for u, kw in calls if "short.io" in u), "11. Your own book was not posted in a paid slot")
calls.clear(); ok(len(ads.ads_due(fake)) == 0, "12. Same hour again (manual re-run) does not double-post")
at(18); due = ads.ads_due(fake); ok(len(due) == 1, "13. 18:00 UTC: second post of the day is due")
engine.run_campaign(); at(18); ok(ads.ads_due(fake) == [], "14. Daily allowance (2 posts/day) now used up")

at(0, 16); calls.clear(); fake.t["mamachi_orders"][0]["ad_hours"] = "0,6,18"
engine.run_campaign(); ok(any("api.short.io" in u and "amazon.com" in str(kw) for u, kw in calls) and fake.t.get("mamachi_campaign_logs"), "15. At your own slot (00:00 UTC) YOUR product/service posts and is logged for free")
fake.t["mamachi_orders"][0].update(posts_remaining=0)
at(6, 17); calls.clear(); engine.run_campaign()
ok(fake.t["mamachi_orders"][0]["status"] == "completed" and worker_calls("/social/revoke"), "16. Finished campaign closes and deletes the buyer's stored accounts")
fin = worker_calls("/notify-vendor"); ok(any("renew=11111111" in m["text"] and "10% off" in m["text"] for m in fin), "17. Renewal reminder with a 10% off link sent")

fake.t["mamachi_orders"] = [order(id="22222222-aaaa-bbbb-cccc-000000000002", geo_level="region", geo_region="Africa", own_social=True, ad_hours="6")]
os.environ["PLATFORM_REGIONS"] = json.dumps({"telegram": ["europe"]}); at(6, 18); calls.clear(); engine.run_campaign()
posts = fake.t["mamachi_ad_posts"][-1]["platforms"]
ok("telegram" not in posts and "web" in posts, "18. Africa-only ad skips the Europe-tagged Telegram channel: " + posts)
pub = worker_calls("/social/publish"); act = worker_calls("/social/activate")
ok(act and pub and pub[0]["link"].startswith("https://mamachi-engine.s.gy/") and pub[0]["text"].startswith("Sponsored"), "19. Buyer's own accounts activated, then their same ad posted there")
del os.environ["PLATFORM_REGIONS"]

fake.t["mamachi_orders"] = [order(id="33333333-aaaa-bbbb-cccc-000000000003", status="rejected", paypal_capture_id="CAP999XYZ")]
calls.clear(); ads.process_rejections(fake)
ok(worker_calls("/refund") == [{"captureId": "CAP999XYZ"}] and fake.t["mamachi_orders"][0]["refunded_at"], "20. Rejected order refunded automatically, once")
calls.clear(); ads.process_rejections(fake); ok(not worker_calls("/refund"), "21. Not refunded twice")
print("ALL PASSED" if not fails else f"{fails} FAILED"); sys.exit(1 if fails else 0)
