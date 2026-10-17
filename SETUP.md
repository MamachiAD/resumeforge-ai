# Mamachi final version: setup (in this order)

## 0. What is in this folder
- `docs/` the website: `index.html` (landing), `advertise.html` (checkout), `track.html` (vendor tracking), `pricing.json` (the one price table), `site.json` (your channels), `feed.json`, `sitemap.xml`, `robots.txt`
- Python files for the repo root: `engine.py`, `platforms.py`, `ads.py`, `ai_chain.py`, `web_publish.py`, `scout.py` (replace the old ones with the same names)
- `worker/worker.js` the Cloudflare Worker (payments, orders, tracking, email, contact form, own-account vault)
- `supabase.sql`, `SEED.sql` database setup, `email-gateway.gs` free email sender, `.github/workflows/scout.yml`, `tests/`
- `SALES-AGENTS.md` the AI sales assignments and the revenue plan

## 1. Database (Supabase, 5 minutes)
SQL Editor > paste `supabase.sql` > Run. Then paste `SEED.sql` > Run (this adds Mamachi Ads itself to your free rotation).
Your own products and services: Table Editor > `mamachi_products` > Insert row (set `is_active` true, `kind` book/service/product). No limit, always free.

## 2. PayPal (this is the part that was wrong before)
Your old page used `client-id=sb`, PayPal's TEST mode, so no real money would have arrived. Create a REST app at developer.paypal.com (Live), copy its Client ID and Secret.
- Put the **Client ID** in `docs/advertise.html`, replacing `YOUR_PAYPAL_CLIENT_ID`.
- Put the **Secret** only in the Worker. Never in a web page. Test first in Sandbox: use sandbox keys and set `PAYPAL_ENV=sandbox`.

## 3. Worker (Cloudflare, free)
Workers & Pages > Create > paste `worker/worker.js` > Deploy. Add a KV namespace and bind it as `CONTACTS`. Add these secrets:
`PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`, `PAYPAL_ENV`, `SUPABASE_URL`, `SUPABASE_KEY` (service_role), `SITE_ORIGIN` (https://mamachiad.github.io), `PRICING` (paste the contents of `docs/pricing.json`), `CURRENCY` (USD), `NOTIFY_SECRET` (long random text), `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_CHAT_ID`, `EMAIL_WEBHOOK`, `EMAIL_SECRET`, `SHORTIO_API_KEY`, `VAULT_KEY` (`openssl rand -base64 32`), `OUR_LINK_HOSTS` (`mamachi-engine.s.gy`), `MEDIA_HOSTS` (`raw.githubusercontent.com`).
Then put the Worker address in three places: `WORKER` in `docs/advertise.html`, `WORKER` in `docs/track.html`, and `worker` in `docs/site.json`. Whenever you change a price, change `docs/pricing.json` AND the `PRICING` secret so the page and the server agree.

## 4. Vendor emails (free)
Follow the comments in `email-gateway.gs` (2 minutes), and set its web address as `EMAIL_WEBHOOK`.

## 5. GitHub
Upload the Python files to the repo root and `docs/` over your `docs/`. Add repository secrets: `WORKER_BASE_URL`, `NOTIFY_SECRET` (same text as the Worker), `SITE_URL`. Your run-engine workflow must run at 00:00, 06:00, 12:00 and 18:00 UTC (`cron: "0 */6 * * *"`), because the posting times shown to buyers are built on those hours. Optional: `OWN_SLOT_HOURS` (default 0 = the 00:00 run is always yours), `MAX_ADS_PER_RUN` (default 8), `PLATFORM_REGIONS` (see below), `DISABLE_PLATFORMS`.
Add `.github/workflows/scout.yml` for the daily lead scout (see `SALES-AGENTS.md`).

`PLATFORM_REGIONS` example: `{"telegram":["global"],"bluesky":["global"],"youtube":["global"],"facebook":["africa"]}`. Platforms not listed carry every ad. A worldwide ad goes everywhere; an Africa ad goes only to channels tagged africa or global.

## 6. Approving ads
When someone pays, you get a Telegram message. Supabase > `mamachi_orders` > set `status` to `approved` (it starts at the next posting time) or `rejected` (the engine refunds it automatically). Buyers get an email after each post and a private tracking page.

## 7. YouTube and TikTok (your channels)
Your links are already in `docs/site.json` (YouTube @Mamachi_ADs, TikTok @mamachiads), so the page shows Follow buttons. Automatic public uploads are limited by the platforms: videos posted through the YouTube API from an unaudited app stay private, and TikTok's posting API also needs an app audit. Until you pass those audits, set `VIDEO_ENABLED=true`; the engine builds each video and, for TikTok, a ready-to-upload package, and you upload them in one click. Apply for the audits from each platform's developer portal.

## 8. Search engines
Submit `https://mamachiad.github.io/mamachi-ad-engine/sitemap.xml` in Google Search Console and Bing Webmaster Tools. Put the site link in your YouTube, TikTok, Bluesky and Mastodon bios.

## 9. Check everything before going live
`python3 tests/test_engine.py`, `python3 tests/test_scout.py`, `node tests/worker.test.mjs` (all use fakes, nothing is sent). Then do one full order in PayPal Sandbox.
