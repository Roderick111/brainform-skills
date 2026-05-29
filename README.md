# Brainform Skills

Claude Code skills and pipeline scripts for Brainform sales operations — from lead sourcing to outreach automation.

## What is Brainform?

Brainform is an AI layer for ecommerce — it helps online stores improve product discovery through AI-powered search and recommendations. The sales team targets two segments:

- **Direct brands** — Online stores selling physical products (sportswear, skincare, supplements, etc.)
- **Ecom agencies** — Agencies that build/manage online stores on Shopify, Magento, PrestaShop, etc.

## Setup

```bash
# Clone
git clone https://github.com/Roderick111/brainform-skills.git
cd brainform-skills

# Python environment
uv sync

# Environment variables
cp .env.example .env
# Fill in your keys — ask Daniel for DATABASE_URL
```

### Required environment variables

| Variable | Source | Required for |
|---|---|---|
| `DATABASE_URL` | Ask Daniel (Neon PostgreSQL) | All scripts |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | Segmentation, categorization |
| `MILLION_VERIFIER_API_KEY` | [millionverifier.com](https://app.millionverifier.com/api) | Email verification |
| `GETSALES_API_KEY` | GetSales settings → API | GetSales sync |

## Quick start

Open this repo in Claude Code and type:

```
/help-me
```

This prints the full guide — what's possible, which skills to use, all available scripts.

## The pipeline

```
Apollo.io → Import → Segment → Enrich → Verify → Export → GetSales
```

| Step | Script | What happens |
|---|---|---|
| Import companies | `import_companies.py` | Apollo CSV → database |
| Import contacts | `import_contacts.py` | Contacts → database, matched to companies |
| Segment | `segment_companies.py` | LLM classifies: ecom-product, agency, etc. |
| Sub-segment agencies | `segment_agencies.py` | Refines agency type + detects platforms |
| Generate categories | `generate_product_categories.py` | "sports nutrition", "skincare" for templates |
| Verify emails | `verify_emails_mv.py` | MillionVerifier API (1 credit/email) |
| Export | `export_contacts.py` | CSV to ~/Downloads, filterable |
| Sync GetSales | `sync_getsales.py` | Pull engagement data back to DB |

All LLM scripts use `google/gemma-4-31b-it` via OpenRouter.

Run any script with:
```bash
uv run dev/scripts/<script>.py --help
```

## Skills

| Skill | Trigger | What it does |
|---|---|---|
| `/lead-pipeline` | "new leads", "import contacts" | Step-by-step pipeline guide |
| `/outreach` | "cold email", "draft emails" | Generate personalized emails → Gmail drafts |
| `/reply-handler` | "someone replied" | Classify reply, draft response |
| `/follow-up` | "write follow-up" | Follow-up messages by stage |
| `/getsales-audit-send` | "send audits" | Generate report → deploy → send via LinkedIn |
| `/outreach-db` | "database", "schema" | DB schema, functions, n8n integration |
| `/help-me` | "what can you do" | Full onboarding guide |

## Project structure

```
.claude/
  skills/           ← Claude Code skills (workflows + reference docs)
  commands/         ← Slash commands (/help-me, /personalize-email)
dev/
  scripts/          ← Python pipeline scripts (all use UV)
.env.example        ← Required environment variables
pyproject.toml      ← Python dependencies
```
