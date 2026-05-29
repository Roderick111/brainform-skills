---
description: Quick onboarding — what this workspace does and what you can ask for
---

Print the following guide to the user exactly as written. Do not read any files. Do not run any commands.

---

# Brainform Sales Workspace

## What is Brainform?

Brainform is an AI layer for ecommerce — it helps online stores improve product discovery through AI-powered search and recommendations. Think: when a customer asks an AI assistant "what running shoes are good for flat feet?" — Brainform makes sure the right products show up.

## Who do we sell to?

Two segments, two separate pipelines:

**1. Direct brands (ecom-product)** — Online stores that sell physical products (sportswear, skincare, pet food, supplements, etc.). We show them how AI currently recommends their products vs competitors. The hook is a free audit report showing gaps in their AI visibility.

**2. Ecom agencies** — Agencies that build and manage online stores for clients (Shopify, Magento, PrestaShop, etc.). We partner with them so they can offer AI optimization as a service to their clients. The hook is showing them the opportunity in AI-driven commerce.

## How does the sales pipeline work?

```
Apollo (lead source) → Neon PostgreSQL (CRM) → GetSales (outreach automation)
```

1. **Find leads** on Apollo.io — filter by segment, country, persona
2. **Import** company + contact CSVs into our Neon database
3. **Segment** companies via LLM (classify type, detect platforms)
4. **Enrich** — clean names, generate category phrases for personalization
5. **Verify emails** via MillionVerifier API
6. **Export** CSVs split by country/region
7. **Upload to GetSales** for automated LinkedIn + email sequences
8. **Sync back** — pull engagement data from GetSales into DB

For direct brands, there's also an **audit track**: after someone connects on LinkedIn, we generate a personalized AI visibility report and send it as a conversation starter.

## What can you ask me to do?

### "I have new leads from Apollo"
→ I'll walk you through the full import pipeline. Say **`/lead-pipeline`** for step-by-step guidance, or just drop the CSV paths and tell me the segment.

### "Write outreach for these contacts"
→ **`/outreach`** generates personalized cold emails and saves them as Gmail drafts. Give me email addresses or company domains.

### "Someone replied to my message"
→ **`/reply-handler`** classifies the reply (interested, objection, not now, etc.) and drafts a response that drives toward a meeting.

### "Send audit reports to connected leads"
→ **`/getsales-audit-send`** runs the full pipeline: generate AI visibility report → deploy to web → send personalized LinkedIn message via GetSales API.

### "Write a follow-up"
→ **`/follow-up`** crafts follow-up messages based on the conversation stage.

### "Write a LinkedIn post"
→ **`/post-writer`** guides you from idea to published post (5-step process with anti-AI cleanup).

### "Help me with the database"
→ **`/outreach-db`** covers schema, dedup functions, data cleanup, n8n workflows, Gmail reply parsing.

### "I need full strategic context"
→ **`/start`** loads 16 context files (product, strategy, research, frameworks). Use for strategy sessions, not daily ops.

## Key scripts (all in `dev/scripts/`, run with `uv run`)

| Script | Purpose |
|---|---|
| `import_companies.py` | Apollo companies CSV → DB |
| `import_contacts.py` | Apollo contacts CSV → DB |
| `segment_companies.py` | LLM classification (ecom-product, agency, etc.) |
| `segment_agencies.py` | Agency sub-type + platform detection |
| `generate_product_categories.py` | "sports nutrition", "skincare" — for outreach templates |
| `generate_agency_categories.py` | Same but for agencies |
| `verify_emails_mv.py` | MillionVerifier email verification |
| `export_contacts.py` | Export filtered CSV to ~/Downloads |
| `sync_getsales.py` | Pull pipeline stages from GetSales API |
| `import_getsales.py` | Import from GetSales CSV (phones, IDs, LinkedIn) |

## Tech stack

- **Database:** Neon PostgreSQL (cloud Postgres)
- **LLM enrichment:** Google Gemma 4 31B via OpenRouter (all scripts)
- **Email verification:** MillionVerifier API
- **Outreach automation:** GetSales (LinkedIn + email sequences)
- **Lead sourcing:** Apollo.io
- **Audit reports:** ARS pipeline (TypeScript, Firebase Genkit) → served at `brainform.beautiful-apps.com/{slug}`
- **Python tooling:** UV for package management, all scripts in `dev/scripts/`

## Rules I follow

- I never execute SQL directly — I provide the query, you run it
- I never push to git without asking
- I never send messages or emails without explicit approval
- All LLM scripts use `google/gemma-4-31b-it` via OpenRouter
- Email verification is MillionVerifier (not Findymail — that's deprecated)
