# Sales agents, free-tier plan and revenue plan

Free tiers change, so check each provider's current limits. Everything below is designed to stay inside free limits.

## 1. Who does what (all free)
| Job | Tool | How often |
|---|---|---|
| Ad copy, per-platform versions, lead scoring | Gemini free API, then Groq, OpenRouter, Mistral as automatic overflow (`ai_chain.py`) | every run |
| Find people who need advertising | `scout.py` on Bluesky search and public Mastodon hashtag timelines | once a day |
| Draft the reply and the offer | same free chain, inside `scout.py` | once a day |
| Trend check for what to post about | Grok app (free, by hand) | 10 minutes a day |
| Turn your books into 20 insight posts | Kimi app (free, by hand): paste a chapter, ask for 20 short, honest, standalone insights, add each as a row in `mamachi_products` | once a week |
| Weekly strategy and objection handling | Claude chat (free plan limits): paste last week's orders, clicks and leads, ask what to change | once a week |
| Approve ads, send replies, close deals | you, from Telegram | 15 minutes a day |

## 2. The daily rhythm (inside free limits)
- 00:00 UTC: your own products and services post (always free, unlimited items).
- 06:00, 12:00, 18:00 UTC: every paid ad due at that hour posts. Cost: 1 AI call for the text and 1 more if the buyer chose different text per platform.
- 09:00 UTC: the scout runs once, using 1 or 2 AI calls.
- Capacity estimate: roughly 60 to 100 free AI calls a day across providers means about 30 to 50 ad posts a day, so roughly 15 to 25 ads running at once at 2 posts a day. If demand grows, switch buyers to identical text (1 call), add provider keys, or move to a paid model. Watch the engine log to see the real numbers.

## 3. Finding, approaching and closing (without spamming)
1. **Detect:** the scout looks for public posts such as "how do I promote my book" or "opening my shop, no idea how to get customers" and scores them 0 to 100. Only 60 and above are kept, at most 8 a day, one per person.
2. **Draft:** it writes a short, useful public reply in the person's language: one concrete tip first, then one clause saying you are from Mamachi Ads. No promises of results.
3. **Approve:** you get the post link, the draft and a ready checkout link on Telegram. You edit and send it yourself. **Nothing is sent to strangers automatically, and there are no DMs.**
4. **Close:** if they reply, send the offer link that opens the checkout already filled in (for example `advertise.html?unit=day&qty=1&geo=local&slot=feed`). The $2 hour or $12 day is the easy first yes.
5. **Follow up:** one polite follow-up after three days, then stop. Mark the lead `sent`, `won` or `skipped` in `mamachi_leads`.
Rules: reply publicly and once per person, say who you are, accept a no, never scrape private data or emails, never claim results, follow each platform's rules on automated accounts.

## 4. Revenue: what I can and cannot promise
**I cannot promise any minimum. Revenue is $0 until someone pays.** Here is the arithmetic, so you can see what has to be true. Conversion rates below are my assumptions, not measured data. Replace them with your real numbers after two weeks.

Typical order sizes from your price table: week + local + feed card = $60; week + country + feed+social with different text = about $214; month + local + feed card = $200.

| Daily target | Per month | Orders needed per month |
|---|---|---|
| $10 | $300 | 5 of $60, or about 1.4 of $214 |
| $50 | $1,500 | 7 of $214 |
| $200 | $6,000 | 28 of $214 |

Scout funnel (assumptions): 8 leads a day, you reply to all 8, 10% answer, 15% of those buy = 0.12 orders a day. At $60 that is about **$7 a day**; at $214 about **$26 a day**. To reach $50 a day you need several sources at once: more platforms for the scout, community partnerships (one authors' group can send many orders), renewals (the 10% off renewal link brings buyers back), and referrals.

## 5. New ideas, all free or nearly free
1. **$2 test hour:** the cheapest ad is the front door; track who comes back for a week.
2. **Ad of the Week:** pick one real advertiser each week for a free bonus post; it becomes your best case study.
3. **Real case studies only:** after a campaign, with permission, post "X got N link clicks in 7 days" using the tracking page numbers.
4. **Seasonal calendars:** Ramadan, Enkutatash, Timkat, back to school, Black Friday, Valentine's Day. Post "book your slot" 3 weeks ahead.
5. **Community partners:** offer writers' groups, book clubs and small-business associations a group price you set by hand.
6. **Referral discount:** 10% off for the buyer and the friend, tracked by order number.
7. **Weekly Mamachi Insight:** value posts from your books (Kimi weekly batch) so followers see more than ads.
8. **Multilingual first:** Amharic, Swahili, Arabic and French ads are a niche most ad tools skip.
9. **Behind-the-scenes videos:** short clips of the engine building an ad, posted on YouTube and TikTok.
10. **Free "ad idea" for anyone who replies:** one AI-written ad concept for their offer, then the checkout link.
11. **Partner swap:** advertise a complementary service (printer, editor, cover designer) and share leads.
12. **Renewal rhythm:** every campaign ends with the renewal email, which is the cheapest sale you will ever make.

## 6. Mamachi advertises itself
`SEED.sql` adds five rotating Mamachi Ads rows to your free rotation, so the engine promotes the service on its own at 00:00 UTC. Add more rows any time: new angles, case studies, seasonal offers.

## 7. Recurring payments
Today: when a campaign ends, the buyer gets a renewal link with 10% off. This is reliable and needs nothing extra. Fully automatic billing needs PayPal Subscriptions (a separate integration); I recommend adding it after your first paying customers.
