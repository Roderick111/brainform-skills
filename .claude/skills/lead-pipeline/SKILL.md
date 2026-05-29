---
name: lead-pipeline
description: >
  Step-by-step guide for processing new leads from Apollo CSV to GetSales import.
  The PRIMARY skill for lead management. Use when: user says "new leads", "import contacts",
  "process apollo", "segment companies", "verify emails", "export for getsales",
  "lead pipeline", "add leads", or any request involving the Apollo → DB → GetSales flow.
  Covers: sourcing, importing, segmenting, enriching, verifying, exporting, and GetSales upload.
---

# Lead Pipeline

End-to-end guide for processing new leads into the outreach pipeline.
Apollo CSV → Neon DB → LLM segmentation → enrichment → email verification → GetSales.

All scripts live in `dev/scripts/`. All LLM scripts use `google/gemma-4-31b-it` via OpenRouter.

## Pipeline Overview

```
Step 1  [USER]    Export from Apollo (companies + contacts CSVs)
Step 2  [SCRIPT]  Import companies → DB
Step 3  [SCRIPT]  Import contacts → DB (matches to companies)
Step 4  [SCRIPT]  Segment companies (LLM classification)
Step 5  [USER]    Run clean_company_names() in SQL
Step 6  [SCRIPT]  Enrich (product categories or agency categories)
Step 7  [SCRIPT]  Verify emails (MillionVerifier)
Step 8  [SCRIPT]  Export to CSV
Step 9  [USER]    Upload CSV to GetSales
```

---

## Step 1: Source from Apollo

**Who:** User (manual)

Export two separate CSVs from Apollo:
1. **Companies CSV** — company data (name, domain, industry, etc.)
2. **Contacts CSV** — people data (name, title, email, LinkedIn, etc.)

Apollo persona filters handle junk title removal — no manual review needed after export.

**Ask the user:**
- Where are the CSV files? (usually `~/Downloads/`)
- What segment? (ecom brands, agencies, etc.)
- Which country/region?

**Before proceeding:** Check CSV headers and row counts to confirm valid Apollo exports.

```bash
head -1 "<csv_path>"
wc -l "<csv_path>"
```

---

## Step 2: Import Companies

**Who:** Claude runs script, user approves

**MUST run before contacts.** Contacts match to companies by domain/org_id — companies must exist first.

```bash
uv run dev/scripts/import_companies.py "<companies_csv_path>"
```

**Script:** `dev/scripts/import_companies.py`
- Uses `upsert_company()` DB function for deduplication
- Matches by: normalized domain → org_id → exact name → fuzzy name
- Safe to re-run (idempotent)

**Check result:** Look at matched/inserted/skipped counts. High skip count = mostly existing companies (normal for repeat imports).

**If no separate companies CSV:** Sometimes Apollo contacts export includes company data. The contacts import script matches by domain/org_id to existing companies. If companies aren't in DB yet, contacts will show as "unmatched."

---

## Step 3: Import Contacts

**Who:** Claude runs script, user approves

```bash
uv run dev/scripts/import_contacts.py "<contacts_csv_path>"
```

**Script:** `dev/scripts/import_contacts.py`
- Matches contacts to companies by domain first, then org_id
- Sets `enrichment_status = 'email_found'` when email present
- Upserts on Apollo Contact Id (safe to re-run)

**Check result:**
- **Matched** — linked to a company, ready for pipeline
- **Unmatched** — company not in DB. Either import their companies first, or these are out of scope
- **Errors** — usually schema issues, investigate

**Multiple CSVs:** Run once per file. Order doesn't matter within contacts.

---

## Step 4: Segment Companies

**Who:** Claude runs script, user approves

Two segmentation tracks depending on what was imported:

### 4a. General segmentation (first-time companies)

For companies with `segment IS NULL`:

```bash
uv run dev/scripts/segment_companies.py --limit 500
```

**Script:** `dev/scripts/segment_companies.py`
- Classifies into: ecom-product, agency, b2b-manufacturer, marketplace, etc.
- Also assigns verticals (beauty-skincare, sporting-goods, etc.)
- Uses instructor + JSON mode via OpenRouter
- Concurrency 50, batch 50, 3s delay between batches

**Dry run by default.** Add `--write` to persist to DB. Always preview first.

### 4b. Agency sub-segmentation

For companies with `segment = ['agency']` (base tag only):

```bash
# Check count first
uv run dev/scripts/segment_agencies.py --count-only

# Run classification
uv run dev/scripts/segment_agencies.py --limit 200
```

**Script:** `dev/scripts/segment_agencies.py`
- Refines agencies into: ecom-agency, marketing-agency, dev-shop, bpo-outsourcing, not-agency
- Detects platforms: shopify, magento, prestashop, sfcc, woocommerce, bigcommerce, shopware
- Writes immediately (no --write flag needed, use --dry-run to preview)

**Skips:** Companies with no description or keywords get skipped — can't classify without data.

---

## Step 5: Clean Company Names

**Who:** User runs SQL manually

Claude provides the SQL, user executes it. Never execute SQL directly.

```sql
SELECT clean_company_names();
```

This SQL function strips:
- Legal suffixes (GmbH, S.r.l., LLC, Ltd, Inc, SAS, SARL, etc.)
- Taglines after separators (` - `, ` | `, ` // `)
- Special characters (®, ™, etc.)
- Domain suffixes (.com, .net, etc.)
- Parenthetical noise

**Ask user:** "Ready to run `clean_company_names()`?" and provide the SQL.

---

## Step 6: Enrich

**Who:** Claude runs script, user approves

Two tracks depending on segment:

### 6a. Product categories (ecom-product only)

Generates 2-4 word category phrases for outreach templates (e.g. "sports nutrition", "skincare").

```bash
# Preview
uv run dev/scripts/generate_product_categories.py --limit 50

# Write to DB
uv run dev/scripts/generate_product_categories.py --limit 500 --write
```

**Script:** `dev/scripts/generate_product_categories.py`
- Targets: `segment[1] = 'ecom-product'` AND `product_category IS NULL`
- Category must work in: "how AI agents recommend [PHRASE] brands"
- Concurrency 50, batch 50

### 6b. Agency categories

```bash
uv run dev/scripts/generate_agency_categories.py --limit 500 --write
```

**Script:** `dev/scripts/generate_agency_categories.py`

**Quality check:** After generating, spot-check by reading some results. Categories that are too narrow (single product) or too vague ("consumer goods") need prompt adjustment.

---

## Step 7: Verify Emails

**Who:** Claude runs script, user approves

Uses MillionVerifier API. Costs 1 credit per email.

```bash
# Check credits first
uv run dev/scripts/verify_emails_mv.py credits

# Verify (limit to available credits)
uv run dev/scripts/verify_emails_mv.py verify --limit 100
```

**Script:** `dev/scripts/verify_emails_mv.py`
- Processes: `enrichment_status = 'email_found'` in target segments
- Results: verified, catch_all, risky
- Auto-stops if credits run out
- API key: `MILLION_VERIFIER_API_KEY` in `.env`

**Ask user:** "How many MV credits do you have?" before running. Set --limit accordingly.

**Dry run:** `--dry-run` flag available to preview without writing.

---

## Step 8: Export to CSV

**Who:** Claude runs script, user approves

```bash
# Export by segment
uv run dev/scripts/export_contacts.py --segment agency --today

# Export verified only
uv run dev/scripts/export_contacts.py --segment ecom-product --status verified

# Export all
uv run dev/scripts/export_contacts.py --all
```

**Script:** `dev/scripts/export_contacts.py`
- Outputs to `~/Downloads/` by default
- Flags: `--segment`, `--status`, `--today`, `--limit`, `--output`
- Includes: name, title, email, LinkedIn, company, domain, country, segment, product_category

**Common requests:**
- "Download new contacts" → use `--today` flag
- "Split by country" → export once, then split with a quick Python script
- "Only verified" → `--status verified`

**Send the file** to the user via SendUserFile after export.

---

## Step 9: Upload to GetSales

**Who:** User (manual)

User uploads the CSV to GetSales for LinkedIn + email sequences.

**Separate lists by:**
- Country/region (France vs US vs DACH)
- Segment (agencies vs direct brands)

**After GetSales import, two sync scripts exist:**
- `sync_getsales.py` — pulls pipeline stages back from GetSales API → DB
- `import_getsales.py` — imports from GetSales CSV export, enriches DB with phones, getsales_id, LinkedIn IDs. Handles column mapping.

---

## Quick Reference

| Script | Purpose | Key flags |
|---|---|---|
| `import_companies.py` | Apollo companies → DB | `<csv_path>` |
| `import_contacts.py` | Apollo contacts → DB | `<csv_path>`, `--company-id` |
| `segment_companies.py` | LLM segmentation (general) | `--limit`, `--write` |
| `segment_agencies.py` | Agency sub-classification | `--limit`, `--dry-run`, `--count-only` |
| `generate_product_categories.py` | Category phrases (ecom) | `--limit`, `--write` |
| `generate_agency_categories.py` | Category phrases (agency) | `--limit`, `--write` |
| `normalize_company_names.py` | LLM name cleanup (alt) | `--limit`, `--write` |
| `verify_emails_mv.py` | Email verification | `verify --limit`, `credits` |
| `export_contacts.py` | CSV export | `--segment`, `--status`, `--today` |
| `sync_getsales.py` | Sync stages from GS API | `--dry-run`, `--all` |
| `import_getsales.py` | Import from GS export | `<csv_path>` |

## Error Handling

- **Neon DB connection refused** — DB auto-suspends after idle. Retry in 30s, usually wakes up.
- **OpenRouter 502/503** — transient. All scripts have retry logic (4 attempts, 3s delay).
- **MillionVerifier out of credits** — script auto-stops, partial results saved. Ask user for new API key or credits.
- **High unmatched count on contact import** — companies likely not imported yet. Run Step 2 first.
