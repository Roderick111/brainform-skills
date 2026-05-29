---
name: follow-up
description: Write follow-up emails for unanswered outreach. Finds sent emails with no reply via Gmail MCP, drafts follow-ups using a different angle from the original, and saves as Gmail drafts. Works for direct prospects (Cluster 1 ecoms) and partners (Cluster 3 agencies). Triggers on "follow-up", "follow up", "write follow-ups", "draft follow-ups", "check unanswered emails".
---

# Follow-Up Email Generator

Write follow-up emails for sent outreach that got no reply. Find candidates via Gmail, draft per principles, save as Gmail drafts.

## Modes

### Mode 1: Auto-find unanswered emails

When user says "follow up" or "write follow-ups" without specifying contacts:

1. Search Gmail for sent outreach with no reply
2. Show candidates grouped by segment
3. User picks which ones to follow up
4. Draft and create Gmail drafts

### Mode 2: Specific contact

When user provides a name, email, or thread:

1. Find the thread in Gmail
2. Read the original email
3. Draft follow-up
4. Create Gmail draft

---

## Step 1: Find candidates

User provides a subject keyword or search query (e.g. "audit discussion", "partnership call"). Search Gmail:

```
subject:{keyword} from:me
```

Use pageSize 50. For each thread, classify:

- **Bounced**: thread contains message from `postmaster@` or `mailer-daemon@` → skip
- **Has reply**: thread contains message from someone other than `daniel@brainform.ai` who is not a bounce daemon → skip
- **Maxed out**: 4+ emails from daniel in the thread with no reply → skip (show in summary as "maxed out, no further follow-up")
- **Eligible**: no reply, no bounce, under 4 sent emails, last message from daniel sent 5-30 days ago → candidate

The follow-up must account for ALL previous messages in the thread (read them all, use a different angle from every one).

### Detect segment from subject/content

- Subject contains "audit discussion" → **Cluster 1 (direct prospect)**
- Subject contains "Partnership" or "partnership" → **Cluster 3 (partner/agency)**
- Otherwise → ask user

### Show candidates

```
Eligible for follow-up (no reply, delivered, 5-30 days):

PROSPECTS (Cluster 1):
  1. Kelsey (kelsey@johnnie-o.com) — sent Apr 13, Apr 23 (2 emails) — johnnie-o.com audit
  2. Jesse (jleng@rudis.com) — sent Apr 13, Apr 23 (2 emails) — rudis.com audit
  ...

PARTNERS (Cluster 3):
  1. Robert (robert@easproject.com) — sent Apr 14, Apr 22 (2 emails) — partnership follow-up
  ...

Which ones? (numbers, "all", or "all prospects" / "all partners")
```

Wait for user selection before drafting.

## Step 2: Read full thread

For each selected thread, fetch full content:
```
get_thread(threadId, messageFormat: FULL_CONTENT)
```

Extract:
- Recipient name, email
- Original subject
- Full body of ALL sent emails in the thread (read every one)
- How many emails already sent (1st, 2nd, 3rd touch)
- Which segment (prospect vs partner)
- What each email said (observation, angle, ask, attachments mentioned)
- What angles have already been used (so you don't repeat any)

## Step 3: Read context files

Before writing ANY follow-up:

1. `references/follow_up_principles.md` — writing rules for follow-ups
2. `references/segment_briefings.md` — what matters to each segment
3. `references/anti_ai_patterns.md` — anti-AI checklist, banned words, structural patterns

## Step 4: Diagnose

For each thread, answer internally (do not output):

1. **How many emails have I already sent?** List each one's angle and CTA.
2. **What value types have been used?** (product benefit, market stat, concrete picture, audit/demo, question about their world)
3. **What value type hasn't been tried yet?** Pick one NOT used in any previous email.
4. **What's the most likely reason for no reply?** (busy, unclear value, ask too big, wrong person, lost in inbox)
5. **What role does this person have?** Read `.claude/skills/outreach/references/role_briefings.md`. What's their personal job? Use it to pick which value type and framing will feel most relevant to them.
6. **How direct should this email be?** More previous emails = shorter and more direct. 3rd touch should be very short. 4th+ should be a clean close or redirect question.
7. **What's the smallest thing I can ask?** Always include a CTA question, even a tiny one ("on your radar?", "relevant for you?").

### Escalation by touch number

- **2nd touch**: different value type, same length. Can include audit/demo link if not sent before, or lead with product benefit or market stat instead.
- **3rd touch**: shorter, more direct. One value statement or one question. Under 40 words.
- **4th touch**: breakup. Leave value on the table (audit link, offer to send to someone else) + clean close.

## Step 5: Write the follow-up

### Four principles

**1. Give frame, not problem frame.**
The email exists to deliver something useful, not to diagnose their site. The recipient should feel "this person gave me something" not "this person found my flaw." If the email contains a problem, it must be wrapped in value: a stat they can use, a product benefit that solves it, or an audit they can learn from.

**2. No outside diagnosis.**
You're a stranger. You haven't earned the right to tell them what's wrong. Customer scenarios are fine (empathy with the shopper). Telling the brand "your site fails here" or "you don't show up in AI" is not. Let the audit or demo reveal gaps — not the email body.

**3. Value before ask.**
Every email must give something before it opens a door. If you strip out the CTA, the email should still be worth reading. If it's not, it's not ready.

**4. Autonomy, not pressure.**
"Worth a look if relevant" > "when can we chat." "If that's on your roadmap" > "you're missing out." The recipient decides if this applies to them. No manufactured urgency, no fear-poking.

### Value entry types

Pick ONE per email. Use a different type from all previous emails in the thread.

**A. Product benefit.** What our product does, framed so the reader sees their personal job getting done. Not "reduces tickets" (business job alone) but "your team stops absorbing a problem they didn't create" (personal job through business job).

**B. Market stat.** A sourced, verifiable number that's genuinely useful for them to know, connected to what we do about it AND to their personal job. Not just "57% of shoppers used AI" but "most ecom teams don't track this channel yet, which means whoever reports on it first owns the narrative" (Head of eCommerce's personal job: have a win for QBR).

**C. Concrete picture.** Paint what their business looks like with the product. The reader should see themselves in the picture, not just the business outcome. A CMO should see "this is the experience I can own." A Head of Support should see "this proves the problem isn't mine."

**D. Audit/demo.** Share a deliverable made for them. Frame as a gift: "Ran an AI readiness check on your catalog" or "Built a demo on one of your client categories." The audit reveals gaps — the email doesn't need to.

**E. Social proof / context.** What other companies or agencies in their space are doing. "A few Shopify Plus agencies are adding an AI assistant as a bolt-on for their client builds." Activates the personal job by showing what peers are doing — the reader self-selects.

**Regardless of which type you lead with, the three layers should be implicit (see below).**

### Structure (under 80 words body, 3rd+ touch under 40 words)

1. **Value** (2-4 lines): the reason this email is worth reading. Product benefit, stat, concrete picture, audit, or context. Connected to the recipient's personal job.
2. **Soft CTA** (1 line): low-barrier, autonomy-preserving. "Worth a look if relevant?" / "On your radar?" / "Happy to walk you through it if useful."

That's it. Two parts. No observation-bridge-link-close choreography. Lead with value, close with a door.

### Coherence rule

The value and CTA must be about the same thing. If the value is a product benefit about on-site guidance, the CTA can't pivot to AI visibility. If the value is a market stat about AI shopping, the CTA connects to that, not to something else.

### The three-layer pattern

Every email has three layers, all implicit. The reader never sees the words "personal job" but they feel the personal payoff through how the business outcome is framed.

**Consumer reality → Business outcome → Personal payoff**

The product solves the consumer job (shopper gets guidance). That produces a business outcome (conversion, fewer returns, fewer tickets). That business outcome serves the stakeholder's personal job (looks competent at QBR, stops being the dumping ground, wins the pitch).

Business value alone is insufficient. "Reduces tickets" is a business job — the Head of Support thinks "okay, and?" The email must make them see their personal job getting done THROUGH the business outcome. Not by saying it directly ("this will help you get promoted") — by framing the outcome so the personal payoff is implied.

Read `.claude/skills/outreach/references/role_briefings.md` for specific personal jobs per role.

| Role | Consumer reality | Business outcome | Personal payoff (implicit) |
|---|---|---|---|
| Head of eCommerce | Shoppers search in AI, find competitors | New channel with trackable data | "Whoever reports on this first owns the narrative" — QBR win |
| COO | Wrong-product purchases from guessing | Measurable return rate reduction | Clean ops, no surprises on the P&L |
| Head of Support | "Which one should I choose?" questions | Tickets the site should answer, not the team | "Your team stops absorbing a problem they didn't create" |
| CMO | Online can't replicate in-store guidance | AI assistant that guides product choice | "A few brands your size are doing this" — she's the one who brought it in |
| CEO/Founder | Shoppers leave to research elsewhere | Revenue from a fixable, specific leak | Not wasting time — proven with Tefal, De'Longhi |
| Agency Founder | Clients asking about AI, no good answer | Deployable AI assistant for client builds | "Next time a client asks what your AI story is" — wins the pitch |

**Fear reduction** works the same way. Don't poke fears ("are your competitors doing X?"). Reduce fears by giving proof: live brand names, deployment speed, zero data prep. "Live with Tefal and De'Longhi, takes 4 weeks" reduces the fear of recommending something unproven — the personal job of "not getting blamed" is served by the social proof, not by addressing the fear directly.

### Rules

**MUST:**
- Use a different value type from all previous emails in the thread
- Be under 80 words body (3rd+ touch: under 40 words, excluding signature)
- Give something valuable before asking for anything
- Have exactly one job (give value OR ask a question OR propose a step)
- Reply to the original thread (same subject line with Re:)
- Sound like the same person who wrote the original
- Implicitly serve the recipient's personal job through the business outcome (three-layer pattern)

**MUST NOT:**
- Diagnose the brand's site, strategy, or visibility from outside ("your site fails", "you don't show up", "your data isn't structured")
- Point out problems to provoke a reaction
- Summarize or reference the previous email ("as I mentioned", "in my last email", "following up on")
- Use any filler opener (see banned openers below)
- Manufacture fake urgency or scarcity
- Ask "have you had a chance to review"
- Use personal job fears as pressure ("are your competitors doing X?", "your analytics can't see this")
- Stop at the business job without implying the personal payoff ("reduces tickets" alone, "improves conversion" alone)

### Banned openers and filler (in addition to context/writing.md bans)

These are NEVER allowed anywhere in a follow-up:

- "Quick question"
- "Quick thought"
- "Curious,"
- "Just checking in"
- "Just following up"
- "Bumping this"
- "Wanted to circle back"
- "Hope you're doing well"
- "Hope this finds you well"
- "I wanted to reach out"
- "Thought I'd reach out"
- "Any thoughts on this?"
- "Have you had a chance to..."
- "Did you get a chance to..."
- "Looping back on this"
- "Touching base"
- "Friendly reminder"
- "As I mentioned"
- "Per my last email"
- "Excited to"
- "Looking forward to"

If you catch yourself writing any of these, delete and rewrite.

### Segment-specific guidance

**Cluster 1 (direct prospects / ecoms):**
- Original was an audit email with a site observation
- Follow-up should deliver a DIFFERENT type of value: product benefit, market stat, concrete picture, or re-framed audit
- The audit link can be included again, but framed as a gift ("ran a readiness check on your catalog"), not as evidence of a problem
- CTA stays low: "worth a look?" or "15 min if relevant?" or "on your radar?"

**Cluster 3 (partners / agencies):**
- Original was a partnership email (post-call docs, intro, or proposal)
- Follow-up should give them something useful: context on how other agencies use it, a demo built on their client category, or a question that helps them take their next step
- Do NOT re-pitch the partnership or repeat what was in the docs

## Step 6: Self-check

Run every check from `references/anti_ai_patterns.md`, plus:
1. No em dashes (`—` or `–`)
2. No rule-of-three lists
3. No contrast framing ("not X, but Y")
4. No rhetorical transitions
5. No self-narration
6. No banned words from writing.md
7. No banned openers from this skill
8. Under 80 words body (3rd+ touch: under 40 words)
9. One job only
10. Different value type from ALL previous emails in the thread
11. Has a CTA question (even a small one)
12. No apologies for writing again
13. **Give frame check**: does the email give something valuable before asking? If you strip out the CTA, is it still worth reading?
14. **No outside diagnosis**: does the email tell the brand what's wrong with their site/visibility/strategy? If yes, rewrite. Customer empathy is fine. Brand diagnosis is not.
15. **Autonomy check**: does the CTA preserve the recipient's choice? No pressure, no manufactured urgency, no fear-poking.
16. **Three-layer check**: does the email stop at the business job ("reduces tickets," "improves conversion") or does it implicitly show the personal payoff? The reader should see their personal job getting done through the business outcome.
17. Read aloud: person or brochure?

Fix ALL violations before proceeding.

## Step 7: Create Gmail draft

**Create draft immediately after self-check. Do NOT ask for confirmation or show draft for review.**

Use `gmail_create_draft`:
- **To**: original recipient email
- **Subject**: `Re: {original subject}` (Gmail threads by subject + recipient)
- **Body**: the follow-up text

Note: `gmail_create_draft` does NOT support threadId. Threading relies on matching subject and recipient.

## Step 8: Show summary

```
Follow-up drafts created:
  Kelsey (johnnie-o.com) — different angle: AI visibility for corporate buyers
  Jesse (rudis.com) — different angle: ChatGPT search test result

Skipped:
  Ben (thenothingelse.com) — bounced
  Matthew (tyr.com) — bounced

Already has reply:
  Chris (heiders@web.de) — replied Mar 27

Maxed out (4+ emails, no reply):
  Alex (alex@example.com) — 4 emails sent, last Apr 20
```

---

## Examples

Each example annotates the three layers: consumer reality → business outcome → personal payoff. The annotation is for skill reference only — it never appears in the email.

### Cluster 1 — Product benefit (Head of Support)

Original email: audit observation about product choice complexity.
Three layers: shoppers can't choose (consumer) → tickets the site should answer (business) → "your team stops absorbing a problem they didn't create" (personal: stop being the dumping ground).

```
Hi Sarah,

Half the "which one should I choose?" tickets your
team handles are questions the site should answer
before they reach support.

We put an AI assistant on the site that handles
those conversations. Knows the full catalog,
reads every review, guides the choice. Your team
stops absorbing a problem they didn't create.

Live on a few stores your size. Happy to show
you how it works if relevant.

Daniel
```

### Cluster 1 — Market stat + audit (Head of eCommerce)

Original email: audit observation about on-site search gaps.
Three layers: shoppers using AI to find products (consumer) → new channel with trackable data (business) → "whoever reports on this first owns the narrative" (personal: QBR win).

```
Hi Marcus,

57% of shoppers used AI to find products in the
past 9 months (CapGemini). Most ecom teams don't
track this channel yet, which means whoever
reports on it first owns the narrative.

We make catalogs readable for ChatGPT, Perplexity,
and Google AI. Takes under 4 weeks, no migration.

Ran a visibility check on Hanwag if you want to
see the current state.

https://brainform.beautiful-apps.com/hanwag

Daniel
```

### Cluster 1 — Social proof + concrete picture (CMO)

Original email: audit observation about product compatibility.
Three layers: shoppers need routine guidance (consumer) → AI assistant that guides choice (business) → "a few brands your size are doing this" + live names (personal: be the one who brought it in, conference-worthy story).

```
Hi Laura,

A few brands your size are putting AI assistants
on their product pages that actually guide shoppers
through choices. Not chatbots, real conversations
that know the catalog and every review.

We built the one running on Tefal and De'Longhi.
Takes under 4 weeks to go live, no data prep.

Put together an audit on Medik8 if you want to
see what it would look like on your catalog.

https://brainform.beautiful-apps.com/medik8

Daniel from Brainform
```

### Cluster 1 — Stat + product benefit (CEO/Founder)

Original email: audit observation. Follow-up leads with revenue framing.
Three layers: shoppers leave after failed search (consumer) → fixable revenue leak (business) → proven solution, not a time-waster (personal: financial security, not wasting time on unproven things).

```
Hi James,

75% of shoppers avoid sites where search failed
them once (CapGemini). For a catalog your size,
that's repeat visitors not coming back over
a product-choice problem that's fixable.

We put an AI assistant on the site that handles
the "which one do I need?" conversations. Live
with Tefal and De'Longhi, takes under 4 weeks.

Ran a readiness check on your catalog if useful.

https://brainform.beautiful-apps.com/example

Daniel
```

### Cluster 1 — 4th touch (breakup)

Three previous emails, no reply. Leave value, offer redirect, close clean.

```
Hi Kelsey,

I'll leave the audit here in case it's useful
down the road.

https://brainform.beautiful-apps.com/johnnie-o

If someone else on your team owns this area,
happy to send it their way.

Daniel
```

### Cluster 3 — Social proof + product benefit (Agency Founder, cold intro 2nd touch)

Original: cold partnership intro, no reply.
Three layers: clients asking about AI (consumer/client reality) → deployable AI for client builds (business) → "next time a client asks what your AI story is" (personal: win the pitch, be the expert).

```
Hi Dimitri,

Next time a client asks what your AI story is,
it helps to have a live demo on their own catalog
instead of slides.

We work with a few Shopify Plus agencies who
deploy our assistant as part of their stack.
Plugs into the existing store, live in under
4 weeks, they own the client relationship.

If that's relevant for your next pitch, happy
to walk you through how they set it up.

Daniel
```

### Cluster 3 — Concrete deliverable (Agency Founder, post-call 2nd touch)

Original: sent partnership docs + ICP after call.
Three layers: client catalog is complex (consumer) → working demo, not slides (business) → "test it in a pitch" (personal: win with something real).

```
Hi Sofia,

Built a demo assistant on one of your client
categories so you can see how it works on a
real catalog, not just slides.

Happy to do the same on a specific client
if you want to test it in a pitch.

Daniel
```

### Follow-up after attempted call

If user mentions they tried calling, prepend one line:

```
Hi Sofia,

Tried you just now, will try again later.

Built a demo assistant on one of your client
categories so you can see how it works on a
real catalog, not just slides.

Happy to do the same on a specific client
if you want to test it in a pitch.

Daniel
```
