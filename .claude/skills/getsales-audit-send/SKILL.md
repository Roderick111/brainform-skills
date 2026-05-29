---
name: getsales-audit-send
description: Full pipeline for direct brand outreach — sync GetSales contacts, generate ARS audits, deploy reports, and send personalized LinkedIn messages via GetSales API. Use when asked to "run audit pipeline", "send audit messages", "audit and send", or "getsales audit". Requires explicit approval before sending any message.
---

# GetSales Audit → Send Pipeline

Sync GetSales contacts, generate ARS audit reports, deploy to server, draft personalized LinkedIn messages, and send via GetSales API after explicit approval.

## Prerequisites

- `.env` at project root with `GETSALES_API_KEY`
- `ai-search-server/node_modules` installed (`cd ai-search-server && npm install`)
- SSH key access to `188.34.196.228`

## Pipeline Steps

### Step 1: Sync GetSales → DB

```bash
uv run dev/scripts/sync_getsales.py
```

Optional flags: `--dry-run`, `--all` (all lists, not just direct brands)

This fetches leads from GetSales API, filters to direct brand list (`a5211798-3c96-439d-88ad-3f2bc51a5bac`), matches to DB contacts, and updates `pipeline_stage`. The DB trigger auto-maps `pipeline_stage` → `outreach_status`.

### Step 2: Generate audits + deploy

```bash
npx tsx dev/scripts/audit_pipeline.ts
```

Optional flags: `--dry-run`, `--limit N`

This queries DB for contacts with `outreach_status = 'connected'` + `segment[1] = 'ecom-product'` + domain, calls the ARS API, generates HTML reports, SCPs to server, and updates `outreach_status` to `audit_sent`.

- Runs 5 audits in parallel per batch
- One audit per domain (dedup), marks all contacts at that company
- Reports deploy to `https://brainform.beautiful-apps.com/{slug}`
- Slug format: `www.example.com` → `example` (strip www + TLD)
- Each audit takes 60-120s (cached results return instantly)

### Step 3: Draft personalized messages

For each audited company, draft a LinkedIn message using this template:

```
Hey {first_name},

Ran a comparison of how AI agents recommend {category}. {company_name} vs. a few competitors.

Full breakdown here: {audit_link}

A few of the gaps there are actually quick to close. Happy to walk you through it if useful.
```

#### Category extraction

**Primary source: database.** Query the company's `product_category` field from the `companies` table in Neon DB. This is LLM-classified and human-verified, and more specific than ARS prompt text.

**Fallback (if DB field is empty):** Read the audit JSON from `dev/scripts/reports/pipeline/{slug}.json`. Extract the category from `geoResults[].prompt` where `promptCategory` is `brand` (most specific) or `merchant_discovery`. Clean up the raw prompt into a natural category phrase:
- "best online stores for sports nutrition supplements" → "sports nutrition"
- "beste webshops voor elektrische fietsen" → "e-bikes and cycling"
- Remove "best online stores for", "best online retailers for", etc.
- Translate non-English categories to English

#### Category quality check

The category must be specific enough that the recipient thinks "that's exactly what we do." Test: could this category apply to 1,000+ unrelated companies? If yes, it's too broad.

- "beauty and cosmetics" → too broad. Use the DB value (e.g. "brow and lip products", "skincare", "nail care")
- "consumer electronics" → too broad. Use specific (e.g. "wireless audio", "smart home devices")
- "high-end AR-15 parts and accessories" → "tactical firearms"
- "menopause relief supplements" → "women's health supplements"
- Marketplace companies: use "how AI agents surface online marketplaces" framing instead of "recommend brands"
- B2B/industrial: use "suppliers in the X space" instead of "brands"

#### Present ALL drafts to user for review

Show each draft with: contact name, company, message text. **NEVER send without explicit user approval.** Wait for user to confirm which ones to send.

### Step 4: Send via GetSales API

Only after explicit user approval per message.

#### Find lead UUID

```python
# Search GetSales API for the contact
GET https://amazing.getsales.io/leads/api/leads/?limit=100&offset={offset}
Headers: Authorization: Bearer {token}, User-Agent: Mozilla/5.0

# Match by name in lead["name"]
# Extract lead["uuid"]
```

#### Send LinkedIn message

```python
POST https://amazing.getsales.io/flows/api/linkedin-messages
Headers: Authorization: Bearer {token}, User-Agent: Mozilla/5.0, Content-Type: application/json
Body: {
    "sender_profile_uuid": "0008fa46-19f4-474b-bdb7-acd782529458",  # Nikita
    "lead_uuid": "{lead_uuid}",
    "text": "{message}"
}
```

Status `201` = message queued in GetSales outbox. Delivered when Nikita's LinkedIn session is active.

#### After sending, update outreach status

```bash
uv run dev/scripts/outreach.py log "{contact_identifier}" engaged "LinkedIn message sent with audit link"
```

### Step 5: Summary

After all sends, show:
```
Sent:
  Lis Sierra (Vertical Supply Group) — sent via GetSales
  Jeff Morris (Vertical Supply Group) — sent via GetSales

Pending approval:
  Sean McGimpsey (Applied Nutrition) — draft ready

Failed:
  Huckberry — site unreachable, no audit
```

## Writing Rules

Read `context/writing.md` before drafting. Key rules:
- No em dashes
- No filler openers
- No outside diagnosis ("you're not showing up", "your competitors are ahead")
- No pitch language ("we can help", "happy to discuss")
- No tease language ("something interesting came up")
- The message delivers value (audit link) and offers help ("happy to walk you through it")
- CTA is help-oriented, not curiosity-oriented

## Key Files

| File | Purpose |
|------|---------|
| `dev/scripts/sync_getsales.py` | GetSales API → Neon DB sync |
| `dev/scripts/audit_pipeline.ts` | Audit generation + HTML deploy |
| `dev/scripts/outreach.py` | Outreach status tracking CLI |
| `dev/scripts/reports/pipeline/*.json` | Saved audit JSON results |
| `context/writing.md` | Writing rules |

## Config

| Item | Value |
|------|-------|
| ARS API | `https://ars-ytnhr4e6lq-ew.a.run.app` |
| ARS API key | `a600754048d025d63ada769148e5cde5edac13ea38ff8a46f95633c0c4c8f806` |
| Server | `root@188.34.196.228:/opt/brainform/audits/` |
| Audit base URL | `https://brainform.beautiful-apps.com/{slug}` |
| GetSales sender (Nikita) | `0008fa46-19f4-474b-bdb7-acd782529458` |
| Direct brand list UUID | `a5211798-3c96-439d-88ad-3f2bc51a5bac` |
