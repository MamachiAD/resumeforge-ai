// Offline test of the live worker with a fake PayPal, Supabase, Telegram, email gateway and KV. Run: node tests/worker.test.mjs
import fs from 'fs';
import worker, { priceFor } from '../worker/worker.js';
const PRICING = fs.readFileSync(new URL('../docs/pricing.json', import.meta.url), 'utf8');
const kv = new Map(), db = { mamachi_orders: [], mamachi_ad_posts: [], mamachi_messages: [] }, log = [], mails = [], tg = [];
const env = { PAYPAL_CLIENT_ID: 'id', PAYPAL_SECRET: 's', PAYPAL_ENV: 'sandbox', SUPABASE_URL: 'https://sb.test', SUPABASE_KEY: 'svc', SITE_ORIGIN: 'https://site', PRICING, CURRENCY: 'USD', NOTIFY_SECRET: 'sec',
  TELEGRAM_BOT_TOKEN: 'BOT', OWNER_TELEGRAM_CHAT_ID: '1', EMAIL_WEBHOOK: 'https://mail.test/hook', EMAIL_SECRET: 'es', SHORTIO_API_KEY: 'sk', OUR_LINK_HOSTS: 'mamachi-engine.s.gy',
  VAULT_KEY: Buffer.from(crypto.getRandomValues(new Uint8Array(32))).toString('base64'),
  CONTACTS: { get: async k => kv.get(k) ?? null, put: async (k, v) => void kv.set(k, v), delete: async k => void kv.delete(k), list: async ({ prefix }) => ({ keys: [...kv.keys()].filter(k => k.startsWith(prefix)).map(name => ({ name })) }) } };
let capValue = null, n = 0;
globalThis.fetch = async (url, o = {}) => {
  const R = (j, s = 200) => new Response(JSON.stringify(j), { status: s }), body = () => JSON.parse(o.body || '{}');
  log.push((o.method || 'GET') + ' ' + url.replace(/https:\/\/[^/]+/, ''));
  if (url.includes('/oauth2/token')) return R({ access_token: 'tok' });
  if (url.endsWith('/v2/checkout/orders')) { const p = body().purchase_units[0]; return R({ id: 'PP' + (++n), _p: p }); }
  if (url.includes('/capture')) { const ord = db.mamachi_orders.at(-1); return R({ status: 'COMPLETED', purchase_units: [{ payments: { captures: [{ id: 'CAP' + n + 'XYZ', status: 'COMPLETED', amount: { value: capValue ?? Number(ord.amount).toFixed(2), currency_code: 'USD' } }] } }] }); }
  if (url.includes('/refund')) return R({ status: 'COMPLETED' }, 201);
  if (url.startsWith('https://sb.test/rest/v1/')) {
    const [tbl, q = ''] = url.replace('https://sb.test/rest/v1/', '').split('?'), T = db[tbl], id = /(?:^|&)id=eq\.([^&]+)/.exec(q)?.[1], oid = /order_id=eq\.([^&]+)/.exec(q)?.[1];
    if (o.method === 'POST') { const r = { id: crypto.randomUUID(), ...body() }; T.push(r); return R([r], 201); }
    if (o.method === 'PATCH') { const r = T.find(x => x.id === id); Object.assign(r, body()); return R([r]); }
    return R(T.filter(x => (!id || x.id === id) && (!oid || x.order_id === oid)));
  }
  if (url.includes('statistics.short.io')) return R({ totalClicks: 37 });
  if (url.startsWith('https://mail.test')) { mails.push(body()); return R({}); }
  if (url.includes('api.telegram.org/botBOT/sendMessage')) { tg.push(body().text); return R({}); }
  return R({}, 404);
};
const call = (path, body, h = {}) => worker.fetch(new Request('https://w' + path, { method: 'POST', headers: h, body: JSON.stringify(body) }), env).then(async r => ({ s: r.status, j: await r.json() }));
const eng = { Authorization: 'Bearer sec' };
let fails = 0; const ok = (c, m) => { console.log((c ? 'PASS  ' : 'FAIL  ') + m); if (!c) fails++; };
const brief = { name: 'Sunrise Coffee', email: 'a@b.co', productTitle: 'Sunrise Coffee', link: 'https://sunrise-coffee.com/shop', summary: 'Fresh roasted coffee, weekly.', unit: 'day', qty: 3, geoLevel: 'country', geoRegion: 'Africa', slot: 'social', variation: 'unique', ownSocial: false };

// ---- pricing: every step up in reach or placement costs more, for every duration
const P = JSON.parse(PRICING); let steps = true;
for (const u of Object.keys(P.rates)) {
  for (const g of P.geo.map(x => x.id)) { const a = P.slot.map(s => +priceFor(env, { unit: u, qty: 1, geoLevel: g, slot: s.id }).value); if (!(a[0] < a[1] && a[1] < a[2])) steps = false; }
  for (const s of P.slot.map(x => x.id)) { const a = P.geo.map(g => +priceFor(env, { unit: u, qty: 1, geoLevel: g.id, slot: s }).value); if (!(a[0] < a[1] && a[1] < a[2] && a[2] < a[3])) steps = false; }
}
ok(steps, '1. All 5 durations: feed < feed+social < hero+social, and local < country < region < worldwide (every combination steps up)');
const base = { unit: 'hour', qty: 1, geoLevel: 'local', slot: 'feed' };
ok(priceFor(env, base).value === '2.00' && priceFor(env, { ...base, geoLevel: 'world', slot: 'hero' }).value === '30.00', '2. Cheapest = hourly+local+feed $2.00; dearest hourly = worldwide+hero $30.00');
ok(+priceFor(env, { ...base, ownSocial: true, variation: 'unique' }).value === 2.6 && +priceFor(env, base, .1).value === 1.8, '3. Add-ons raise the price (+20% own accounts, +10% unique posts); renewal takes 10% off');
let r = await call('/order', { ...brief, qty: 100000 }); ok(r.s === 200, '4. Spend is unlimited: 100,000 days accepted (' + r.j.amount + ')');
ok((await call('/order', { ...brief, qty: 0 })).s === 400 && (await call('/order', { ...brief, geoLevel: 'galaxy' })).s === 400, '5. Quantity 0 and unknown reach refused');

db.mamachi_orders.length = 0; r = await call('/order', { ...brief, amount: 0.01, price: 0.01 });
const row = db.mamachi_orders[0];
ok(r.j.amount === '128.30' && row.amount === 128.3, '6. Price chosen by the server: 3 days x $12 x 1.8 x 1.8 x 1.1 = $128.30 even if the browser claims $0.01');
ok(row.ad_hours === '6,18' && row.posts_per_day === 2 && row.posts_total === 6 && row.variation === 'unique', '7. Schedule stored: 2 posts/day at 06:00 and 18:00 UTC, 6 posts in total, unique text per platform');
ok((await call('/order', { ...brief, summary: 'Double your money, guaranteed returns!' })).s === 400, '8. Prohibited ads are refused before they can pay');
capValue = '1.00'; await call('/capture', { orderId: 'PP' + n }).then(x => ok(x.s === 400, '9. A short-paid capture is rejected: status ' + db.mamachi_orders[0].status)); capValue = null;
db.mamachi_orders.length = 0; r = await call('/order', brief); const id = r.j.id, tok = r.j.manageToken;
r = await call('/capture', { orderId: 'PP' + n }); ok(r.j.ok && db.mamachi_orders[0].status === 'paid_review' && tg.some(t => t.includes('waiting for approval')), '10. Correct payment -> paid_review, owner told on Telegram');
ok((await call('/capture', { orderId: 'PP' + n })).s === 400, '11. Same payment cannot be used twice');
ok((await call('/refund', { captureId: 'CAP1XYZ' })).s === 400 && (await call('/refund', { captureId: 'CAP1XYZ' }, eng)).j.ok, '12. Refund needs the engine secret, then works');

db.mamachi_ad_posts.push({ order_id: id, posted_at: '2026-10-15T06:00:00Z', platforms: 'telegram,bluesky', short_url: 'https://mamachi-engine.s.gy/x', shortio_id: 'lnk1' });
r = await call('/track', { id, token: 'bad' }); ok(r.s === 400, '13. Tracking refused with a wrong code');
r = await call('/track', { id, token: tok }); ok(r.j.posts.length === 1 && r.j.clicks === 37 && r.j.order.ad_hours === '6,18' && !('manage_token' in r.j.order) && !('vendor_email' in r.j.order), '14. Buyer sees posts, clicks (37) and schedule, never private fields');
r = await call('/notify-vendor', { orderId: id, subject: 'Posted', text: 'Your ad went out.' }, eng); ok(r.j.ok && mails[0].to === 'a@b.co' && mails[0].secret === 'es', '15. Vendor email sent through the gateway');
ok((await call('/notify-vendor', { orderId: id, subject: 's', text: 't' })).s === 400, '16. Only the engine can send vendor emails');
r = await call('/contact', { name: 'Ann', email: 'ann@x.co', message: 'Do you accept Amharic ads?' }); ok(r.j.ok && db.mamachi_messages.length === 1, '17. Contact form saved and owner pinged');
ok((await call('/contact', { name: 'bot', email: 'b@x.co', message: 'spam', website_url: 'x' })).j.ok && db.mamachi_messages.length === 1, '18. Bot honeypot ignored');
db.mamachi_orders[0].status = 'completed'; r = await call('/order', { ...brief, renewOf: id });
ok(r.j.amount === (128.304 * .9).toFixed(2), '19. Renewal by the same buyer gets 10% off: $' + r.j.amount);
r = await call('/order', { ...brief, email: 'other@x.co', renewOf: id }); ok(r.j.amount === '128.30', '20. Someone else cannot use that buyer\'s renewal discount');

// ---- vault (own-account posting) still locked down
const sent = []; const base_fetch = globalThis.fetch;
globalThis.fetch = async (url, o = {}) => {
  const R = j => new Response(JSON.stringify(j));
  if (url.includes('createSession')) return JSON.parse(o.body).password === 'good' ? R({ accessJwt: 'j', did: 'd', handle: 'shop.bsky.social' }) : new Response('{}', { status: 401 });
  if (url.includes('createRecord')) { sent.push(JSON.parse(o.body).record.text); return R({}); }
  return base_fetch(url, o);
};
const oid = (await call('/order', brief)).j; db.mamachi_orders.at(-1).status = 'approved';
ok((await call('/social/save', { id: oid.id, manageToken: oid.manageToken, platform: 'bluesky', handle: 'shop.bsky.social', appPassword: 'good' })).j.ok, '21. Buyer connects their own Bluesky account');
const pub = b => call('/social/publish', { campaignId: oid.id, ...b }, eng), good = { text: 'Fresh coffee https://sunrise-coffee.com/shop?x=1', link: 'https://sunrise-coffee.com/shop?x=1' };
ok((await pub(good)).s === 400, '22. Publishing is refused until the ad is activated');
await call('/social/activate', { campaignId: oid.id, endsAt: new Date(Date.now() + 864e5).toISOString(), maxPosts: 1 }, eng);
ok((await pub({ text: 'Visit https://evil.example', link: 'https://evil.example' })).s === 400, '23. A link to another site is refused');
ok((await pub(good)).j.ok && sent.length === 1, '24. Their own ad posts to their own account');
ok((await pub(good)).s === 400, '25. Post allowance used up -> refused');
console.log(fails ? fails + ' FAILED' : 'ALL PASSED'); process.exitCode = fails ? 1 : 0;
