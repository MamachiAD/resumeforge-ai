// Cloudflare Worker (free plan) for the LIVE Mamachi system.
// - Price is decided here, never in the browser (see priceFor). PayPal orders are created and captured on the server.
// - Orders live in Supabase (table mamachi_orders). Buyers can track their posts with a private link. Vendor emails go out through EMAIL_WEBHOOK.
// - Advertisers' own social accounts live in an encrypted vault (bottom of this file) and can only ever receive their own ad.
// Secrets: PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_ENV ("live"|"sandbox"), SUPABASE_URL, SUPABASE_KEY (service_role), SITE_ORIGIN,
// PRICING (same JSON as docs/pricing.json), CURRENCY, NOTIFY_SECRET, TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_CHAT_ID, EMAIL_WEBHOOK, EMAIL_SECRET,
// SHORTIO_API_KEY, VAULT_KEY, OUR_LINK_HOSTS, MEDIA_HOSTS. KV namespace: CONTACTS.
const J = (o, s = 200, h = {}) => new Response(JSON.stringify(o), { status: s, headers: { 'Content-Type': 'application/json', ...h } });
const str = (v, min, max, name) => { v = String(v ?? '').trim(); if (v.length < min || v.length > max) throw new Error(`${name} must be ${min}-${max} characters`); return v; };
const httpsUrl = (v, name) => { const u = new URL(str(v, 10, 400, name)); if (u.protocol !== 'https:') throw new Error(name + ' must be https'); return u.toString(); };
const LANGS = ['English', 'Spanish', 'French', 'Portuguese', 'German', 'Arabic', 'Amharic', 'Swahili', 'Hindi', 'Chinese', 'Japanese', 'Russian'];
const REGIONS = ['Worldwide', 'Africa', 'Europe', 'North America', 'Latin America', 'Middle East', 'Asia', 'Oceania'];
const PPD = { feed: 1, social: 2, hero: 3 };                      // posts per day each placement buys
const HARD = [/\b(porn|xxx|escort|nude)\b/i, /\b(firearms?|ammunition|explosives?|silencers?)\b/i, /\b(cocaine|heroin|meth|mdma)\b/i, /\b(counterfeit|fake (id|passport|degree|diploma))\b/i,
  /\bguarantee[d]?\s+(profit|returns?|income)\b/i, /\b(double your money|ponzi|pyramid scheme|get[- ]rich[- ]quick)\b/i];
const pp = env => env.PAYPAL_ENV === 'sandbox' ? 'https://api-m.sandbox.paypal.com' : 'https://api-m.paypal.com';
async function token(env) {
  const r = await fetch(pp(env) + '/v1/oauth2/token', { method: 'POST', headers: { Authorization: 'Basic ' + btoa(env.PAYPAL_CLIENT_ID + ':' + env.PAYPAL_SECRET), 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'grant_type=client_credentials' });
  if (!r.ok) throw new Error('PayPal login failed');
  return (await r.json()).access_token;
}
const ppCall = async (env, path, body) => { const r = await fetch(pp(env) + path, { method: 'POST', headers: { Authorization: 'Bearer ' + await token(env), 'Content-Type': 'application/json', Prefer: 'return=representation' }, body: body ? JSON.stringify(body) : undefined }); return { ok: r.ok, j: await r.json().catch(() => ({})) }; };
const sb = (env, path, method, body) => fetch(env.SUPABASE_URL + '/rest/v1/' + path, { method, headers: { apikey: env.SUPABASE_KEY, Authorization: 'Bearer ' + env.SUPABASE_KEY, 'Content-Type': 'application/json', Prefer: 'return=representation' }, body: body ? JSON.stringify(body) : undefined });
const sbGet = async (env, path) => { const r = await sb(env, path, 'GET'); return r.ok ? r.json() : []; };
const tell = (env, text) => env.TELEGRAM_BOT_TOKEN && env.OWNER_TELEGRAM_CHAT_ID ? fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ chat_id: env.OWNER_TELEGRAM_CHAT_ID, text }) }).catch(() => {}) : null;
const UUID = /^[0-9a-f-]{36}$/i;

// The ONLY place a price is decided. Price = rate x quantity x reach x placement x (1 + add-ons) x (1 - renewal discount).
export function priceFor(env, b, discount = 0) {
  const P = typeof env.PRICING === 'string' ? JSON.parse(env.PRICING) : env.PRICING;
  const unit = String(b.unit), qty = Math.floor(Number(b.qty)), geo = P.geo.find(g => g.id === b.geoLevel), slot = P.slot.find(s => s.id === b.slot);
  if (!(unit in P.rates)) throw new Error('unknown duration');
  if (!(qty >= 1 && qty <= P.max[unit])) throw new Error('quantity out of range');
  if (!geo) throw new Error('unknown reach'); if (!slot) throw new Error('unknown placement');
  const add = (b.ownSocial ? P.addons.ownSocial : 0) + (b.variation === 'unique' ? P.addons.unique : 0);
  const hours = P.hrs[unit] * qty, value = (P.rates[unit] * qty * geo.m * slot.m * (1 + add) * (1 - discount)).toFixed(2);
  return { value, hours, postsPerDay: PPD[slot.id], posts: Math.max(1, Math.ceil(hours / 24 * PPD[slot.id])), adHours: (P.schedule[slot.id] || [12]).join(',') };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const cors = { 'Access-Control-Allow-Origin': env.SITE_ORIGIN, 'Access-Control-Allow-Headers': 'Content-Type,Authorization', 'Access-Control-Allow-Methods': 'POST,OPTIONS' };
    if (req.method === 'OPTIONS') return new Response(null, { headers: cors });
    try {
      if (req.method !== 'POST') throw new Error('POST only');
      const p = url.pathname;
      if (p === '/order') return J(await order(req, env), 200, cors);
      if (p === '/capture') return J(await capture(req, env), 200, cors);
      if (p === '/track') return J(await track(req, env), 200, cors);
      if (p === '/contact') return J(await contact(req, env), 200, cors);
      if (p === '/social/save') return J(await socialSave(req, env), 200, cors);
      if (p === '/social/disconnect') return J(await socialDisconnect(req, env), 200, cors);
      if (p === '/social/activate') return J(await socialActivate(req, env));
      if (p === '/social/publish') return J(await socialPublish(req, env));
      if (p === '/social/revoke') { engineOnly(req, env); await wipe(env, (await req.json()).campaignId); return J({ ok: true }); }
      if (p === '/refund') return J(await refund(req, env));
      if (p === '/notify-vendor') return J(await notifyVendor(req, env));
    } catch (e) { return J({ error: String(e.message || e) }, 400, cors); }
    return J({ error: 'not found' }, 404, cors);
  }
};

async function order(req, env) {
  const raw = await req.text(); if (raw.length > 20000) throw new Error('too large');
  const b = JSON.parse(raw);
  if (b.website_url) return { ok: true };                                    // honeypot
  const email = str(b.email, 5, 120, 'email'); if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) throw new Error('invalid email');
  let discount = 0;
  if (UUID.test(b.renewOf || '')) {                                          // renewal: same buyer, finished or running order -> loyalty discount
    const prev = (await sbGet(env, `mamachi_orders?id=eq.${b.renewOf}&select=vendor_email,status`))[0];
    const P = typeof env.PRICING === 'string' ? JSON.parse(env.PRICING) : env.PRICING;
    if (prev && prev.vendor_email === email && ['approved', 'completed'].includes(prev.status)) discount = P.renewDiscount || 0;
  }
  const price = priceFor(env, b, discount), cur = env.CURRENCY || 'USD';
  const title = str(b.productTitle, 3, 120, 'product title'), summary = str(b.summary, 10, 600, 'summary');
  if (HARD.some(re => re.test(title + ' ' + summary))) throw new Error('this type of ad is not allowed on our channels');
  const manageToken = hex(crypto.getRandomValues(new Uint8Array(24)));            // only the buyer holds this: tracking link and own-account control
  const row = { status: 'pending_payment', vendor_name: str(b.name, 2, 80, 'name'), vendor_email: email, product_title: title, destination_url: httpsUrl(b.link, 'link'), summary,
    language: LANGS.includes(b.language) ? b.language : 'English', hashtags: String(b.hashtags || '').slice(0, 120), unit: b.unit, qty: Math.floor(Number(b.qty)), geo_level: b.geoLevel,
    geo_region: REGIONS.includes(b.geoRegion) ? b.geoRegion : 'Worldwide', placement: b.slot, hours: price.hours, posts_per_day: price.postsPerDay, posts_total: price.posts, posts_remaining: price.posts,
    ad_hours: price.adHours, variation: b.variation === 'same' ? 'same' : 'unique', renew_reminder: !!b.renewReminder, amount: Number(price.value), currency: cur, own_social: !!b.ownSocial, manage_token: manageToken };
  const ins = await sb(env, 'mamachi_orders', 'POST', row); const made = (await ins.json())?.[0];
  if (!ins.ok || !made?.id) throw new Error('could not save your order');
  const o = await ppCall(env, '/v2/checkout/orders', { intent: 'CAPTURE', purchase_units: [{ reference_id: made.id, custom_id: made.id, description: 'Mamachi ads: ' + b.unit + ' x' + row.qty, amount: { currency_code: cur, value: price.value } }] });
  if (!o.ok || !o.j.id) throw new Error('payment could not be started');
  await env.CONTACTS.put('m:' + made.id, await sha(manageToken), { expirationTtl: 90 * 86400 });
  await env.CONTACTS.put('h:' + made.id, new URL(row.destination_url).hostname, { expirationTtl: 90 * 86400 });
  await env.CONTACTS.put('o:' + o.j.id, JSON.stringify({ id: made.id, value: price.value, cur }), { expirationTtl: 86400 });
  return { id: made.id, orderId: o.j.id, manageToken, amount: price.value, currency: cur, postsPerDay: price.postsPerDay, adHours: price.adHours };
}

async function capture(req, env) {
  const { orderId } = await req.json();
  const rec = JSON.parse((await env.CONTACTS.get('o:' + orderId)) || 'null');
  if (!rec) throw new Error('unknown order');
  const c = await ppCall(env, `/v2/checkout/orders/${encodeURIComponent(orderId)}/capture`);       // capture on the server, never trust the browser
  const cap = c.j?.purchase_units?.[0]?.payments?.captures?.[0];
  if (!c.ok || c.j.status !== 'COMPLETED' || cap?.status !== 'COMPLETED') return { ok: false, status: cap?.status || c.j.status };
  await env.CONTACTS.delete('o:' + orderId);                                                      // an order can only be used once
  const good = cap.amount.value === rec.value && cap.amount.currency_code === rec.cur;
  await sb(env, 'mamachi_orders?id=eq.' + rec.id, 'PATCH', { status: good ? 'paid_review' : 'payment_mismatch', paypal_order_id: orderId, paypal_capture_id: cap.id, paid_at: new Date().toISOString() });
  await tell(env, good ? `New PAID ad waiting for approval: order ${rec.id}. In Supabase > mamachi_orders set status to "approved" (go live) or "rejected" (automatic refund).` : `Payment amount mismatch on order ${rec.id}. Check PayPal.`);
  if (!good) throw new Error('amount mismatch');
  return { ok: true, id: rec.id };
}

async function refund(req, env) {
  engineOnly(req, env);
  const { captureId } = await req.json(); if (!/^[A-Z0-9]{6,30}$/.test(captureId || '')) throw new Error('bad capture id');
  const r = await ppCall(env, `/v2/payments/captures/${captureId}/refund`, { note_to_payer: 'Your ad could not be approved, so we have refunded you in full.' });
  return { ok: r.ok };
}

async function track(req, env) {                                          // buyer's private tracking: posts made + link clicks
  const { id, token } = await req.json(); if (!UUID.test(id || '')) throw new Error('not allowed');
  const row = (await sbGet(env, `mamachi_orders?id=eq.${id}&select=*`))[0];
  if (!row || !token || row.manage_token !== token) throw new Error('not allowed');
  const posts = await sbGet(env, `mamachi_ad_posts?order_id=eq.${id}&order=posted_at.desc&limit=300`);
  let clicks = null;
  const sid = posts.find(p => p.shortio_id)?.shortio_id;
  if (sid && env.SHORTIO_API_KEY) {
    try { const s = await (await fetch(`https://statistics.short.io/statistics/link/${encodeURIComponent(sid)}?period=total&tz=UTC`, { headers: { Authorization: env.SHORTIO_API_KEY } })).json(); clicks = s.totalClicks ?? s.humanClicks ?? null; } catch {}
  }
  const o = Object.fromEntries(['product_title', 'status', 'starts_at', 'ends_at', 'posts_total', 'posts_remaining', 'posts_per_day', 'unit', 'qty', 'geo_level', 'geo_region', 'placement', 'variation', 'ad_hours', 'own_social'].map(k => [k, row[k]]));
  return { order: o, posts: posts.map(p => ({ posted_at: p.posted_at, platforms: p.platforms, short_url: p.short_url })), clicks };
}

async function notifyVendor(req, env) {                                    // engine-only: email the buyer
  engineOnly(req, env);
  const b = await req.json(); if (!UUID.test(b.orderId || '')) throw new Error('bad order');
  const row = (await sbGet(env, `mamachi_orders?id=eq.${b.orderId}&select=vendor_email`))[0];
  if (!row || !env.EMAIL_WEBHOOK) return { ok: false };
  const r = await fetch(env.EMAIL_WEBHOOK, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ secret: env.EMAIL_SECRET, to: row.vendor_email, subject: String(b.subject).slice(0, 150), text: String(b.text).slice(0, 4000) }) });
  return { ok: r.ok };
}

async function contact(req, env) {                                        // contact form + support bot hand-off
  const raw = await req.text(); if (raw.length > 6000) throw new Error('too large');
  const b = JSON.parse(raw); if (b.website_url) return { ok: true };
  const email = str(b.email, 5, 120, 'email'); if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) throw new Error('invalid email');
  const row = { name: str(b.name, 2, 80, 'name'), email, message: str(b.message, 5, 2000, 'message') };
  await sb(env, 'mamachi_messages', 'POST', row);
  await tell(env, `New message from ${row.name} <${email}>: ${row.message.slice(0, 300)}`);
  return { ok: true };
}

// ============ Social vault: posting an advertiser's OWN ads to THEIR OWN accounts, nothing else ============
// Safety rules enforced here, not in the engine: (1) credentials are encrypted (AES-GCM, key VAULT_KEY) and stored per campaign;
// (2) only the engine (NOTIFY_SECRET) can publish, and only for an ACTIVE, PAID campaign inside its paid window and post budget;
// (3) the post may only contain links to the advertiser's own site (or our own listed hosts); (4) there is no way to choose a destination:
// posts go only to the accounts that campaign's buyer connected; (5) everything is wiped when the campaign ends or the buyer disconnects.
// Extra secrets: VAULT_KEY (base64 of 32 random bytes), TELEGRAM_BOT_TOKEN (our shared bot), OUR_LINK_HOSTS (e.g. "mamachi-engine.s.gy"), MEDIA_HOSTS ("raw.githubusercontent.com").
const hex = buf => [...new Uint8Array(buf)].map(x => x.toString(16).padStart(2, '0')).join('');
const b64 = u8 => btoa(String.fromCharCode(...u8)), unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const sha = async s => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(s))));
const vkey = env => crypto.subtle.importKey('raw', unb64(env.VAULT_KEY), 'AES-GCM', false, ['encrypt', 'decrypt']);
async function seal(env, o) { const iv = crypto.getRandomValues(new Uint8Array(12)), ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await vkey(env), new TextEncoder().encode(JSON.stringify(o)))); const out = new Uint8Array(12 + ct.length); out.set(iv); out.set(ct, 12); return b64(out); }
async function unseal(env, s) { const u = unb64(s); return JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: u.slice(0, 12) }, await vkey(env), u.slice(12)))); }
const engineOnly = (req, env) => { if (req.headers.get('Authorization') !== 'Bearer ' + env.NOTIFY_SECRET) throw new Error('unauthorized'); };
const owner = async (env, id, token) => { const h = await env.CONTACTS.get('m:' + id); if (!h || h !== await sha(token || '')) throw new Error('not allowed'); };
const FIELDS = { bluesky: ['handle', 'appPassword'], mastodon: ['instance', 'token'], telegram: ['channel'], discord: ['webhook'] };
const safeHost = v => { const h = String(v || '').replace(/^https?:\/\//, '').split('/')[0].toLowerCase(); if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(h) || /^\d+\.\d+\.\d+\.\d+$/.test(h) || h === 'localhost') throw new Error('invalid server address'); return h; };
const jpost = (url, body, headers = {}) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body) });
const must = async (r, what) => { if (!r.ok) throw new Error(what + ' failed (' + r.status + ')'); return r.json().catch(() => ({})); };
async function bsky(a) { const s = await must(await jpost('https://bsky.social/xrpc/com.atproto.server.createSession', { identifier: a.handle, password: a.appPassword }), 'Bluesky login'); return s; }
const PLAT = {
  async bluesky_check(env, a) { return '@' + (await bsky(a)).handle; },
  async bluesky_post(env, a, text) {
    const s = await bsky(a), enc = new TextEncoder(), m = text.match(/https?:\/\/\S+/); let facets;
    if (m) { const st = enc.encode(text.slice(0, m.index)).length; facets = [{ index: { byteStart: st, byteEnd: st + enc.encode(m[0]).length }, features: [{ $type: 'app.bsky.richtext.facet#link', uri: m[0] }] }]; }
    await must(await jpost('https://bsky.social/xrpc/com.atproto.repo.createRecord', { repo: s.did, collection: 'app.bsky.feed.post', record: { $type: 'app.bsky.feed.post', text, facets, createdAt: new Date().toISOString() } }, { Authorization: 'Bearer ' + s.accessJwt }), 'Bluesky post');
  },
  async mastodon_check(env, a) { const h = safeHost(a.instance); const j = await must(await fetch(`https://${h}/api/v1/accounts/verify_credentials`, { headers: { Authorization: 'Bearer ' + a.token } }), 'Mastodon login'); return '@' + j.acct + '@' + h; },
  async mastodon_post(env, a, text) { const h = safeHost(a.instance); await must(await jpost(`https://${h}/api/v1/statuses`, { status: text, visibility: 'public' }, { Authorization: 'Bearer ' + a.token }), 'Mastodon post'); },
  async telegram_check(env, a) {
    const ch = '@' + String(a.channel || '').replace(/^@/, ''); if (!/^@[A-Za-z0-9_]{5,32}$/.test(ch)) throw new Error('invalid channel name');
    const me = await must(await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/getMe`), 'Telegram'), m = await must(await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/getChatMember?chat_id=${encodeURIComponent(ch)}&user_id=${me.result.id}`), 'Telegram');
    if (!['administrator', 'creator'].includes(m.result?.status) || m.result.can_post_messages === false) throw new Error('add our bot as an admin of your channel with permission to post');
    return ch;
  },
  async telegram_post(env, a, text) { await must(await jpost(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, { chat_id: '@' + a.channel.replace(/^@/, ''), text }), 'Telegram post'); },
  async discord_check(env, a) { if (!/^https:\/\/(discord|discordapp)\.com\/api\/webhooks\/\d+\/[\w-]+$/.test(a.webhook || '')) throw new Error('invalid Discord webhook'); const j = await must(await fetch(a.webhook), 'Discord'); return 'Discord: ' + (j.name || 'webhook'); },
  async discord_post(env, a, text) { await must(await jpost(a.webhook, { content: text, username: 'Mamachi Ads' }), 'Discord post'); }
};
async function socialSave(req, env) {
  const b = await req.json(); await owner(env, b.id, b.manageToken);
  const f = FIELDS[b.platform]; if (!f) throw new Error('unsupported platform');
  const creds = Object.fromEntries(f.map(k => [k, String(b[k] || '').trim().slice(0, 300)]));
  const handle = await PLAT[b.platform + '_check'](env, creds);                                   // proves the account exists and the buyer controls it
  await env.CONTACTS.put(`s:${b.id}:${b.platform}`, await seal(env, { ...creds, handle }), { expirationTtl: 7 * 86400 });
  return { ok: true, handle };
}
async function wipe(env, id) { const l = await env.CONTACTS.list({ prefix: `s:${id}:` }); for (const k of l.keys) await env.CONTACTS.delete(k.name); await env.CONTACTS.delete('a:' + id); }
async function socialDisconnect(req, env) { const b = await req.json(); await owner(env, b.id, b.manageToken); await wipe(env, b.id); return { ok: true }; }
async function socialActivate(req, env) {
  engineOnly(req, env); const b = await req.json(), exp = Math.floor(new Date(b.endsAt).getTime() / 1000) + 2 * 86400;
  const host = await env.CONTACTS.get('h:' + b.campaignId); if (!host) throw new Error('unknown campaign');
  const l = await env.CONTACTS.list({ prefix: `s:${b.campaignId}:` });
  for (const k of l.keys) await env.CONTACTS.put(k.name, await env.CONTACTS.get(k.name), { expiration: exp });     // keep credentials only for the paid window
  await env.CONTACTS.put('a:' + b.campaignId, JSON.stringify({ endsAt: b.endsAt, max: Number(b.maxPosts) || 0, used: 0, host, exp }), { expiration: exp });
  return { ok: true, accounts: l.keys.length };
}
async function socialPublish(req, env) {
  engineOnly(req, env); const b = await req.json(), id = b.campaignId, rec = JSON.parse((await env.CONTACTS.get('a:' + id)) || 'null');
  if (!rec) throw new Error('campaign is not active');
  if (Date.now() > new Date(rec.endsAt).getTime()) throw new Error('paid period has ended');
  if (rec.used >= rec.max) throw new Error('paid post allowance used up');
  const text = String(b.text || '').slice(0, 420), allowed = [rec.host, ...String(env.OUR_LINK_HOSTS || '').split(',').map(x => x.trim()).filter(Boolean)];
  const hostOk = u => { try { const h = new URL(u).hostname; return allowed.some(a => h === a || h.endsWith('.' + a)); } catch { return false; } };
  if (!hostOk(b.link)) throw new Error('link is not the advertiser\'s own site');
  for (const u of text.match(/https?:\/\/[^\s]+/g) || []) if (!hostOk(u)) throw new Error('text contains a link to another site');
  const l = await env.CONTACTS.list({ prefix: `s:${id}:` }), results = [];
  for (const k of l.keys) {
    const platform = k.name.split(':')[2];
    try { const a = await unseal(env, await env.CONTACTS.get(k.name)); await PLAT[platform + '_post'](env, a, text + (b.mediaUrl && /^https:\/\//.test(b.mediaUrl) && platform !== 'bluesky' && platform !== 'mastodon' ? '\n' + b.mediaUrl : '')); results.push({ platform, ok: true }); }
    catch (e) { results.push({ platform, ok: false, error: String(e.message).slice(0, 120) }); }
  }
  rec.used++; await env.CONTACTS.put('a:' + id, JSON.stringify(rec), { expiration: rec.exp });
  return { ok: true, results };
}
