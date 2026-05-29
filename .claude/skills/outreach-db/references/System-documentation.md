# Cold Outreach CRM — System Documentation
> For AI agents and new contributors. Last updated: March 2026.

---

## 1. System Overview

A cold outreach pipeline for job search (PM roles) built on:
- **Neon Postgres** — single source of truth for all data
- **n8n** — workflow orchestration (imports, enrichment, email parsing)
- **Apollo API** — contact and company data source
- **Gmail** — outreach sending and reply tracking
- **pgrag** — Postgres extension for calling LLMs directly in SQL (OpenAI)

The system ingests companies and contacts from Apollo/CSV, deduplicates them, tracks outreach status per contact, and parses email replies to update the database automatically.

---

## 2. Database Schema

### `companies`
Primary table for target organizations.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PRIMARY KEY | Auto-incremented |
| name | VARCHAR(255) | Cleaned company name |
| domain | VARCHAR | Normalized (no http/www/paths) — primary dedup key |
| org_id | VARCHAR | Apollo organization ID — secondary dedup key |
| industry | VARCHAR(100) | |
| country | VARCHAR(100) | Default: France |
| city | VARCHAR(100) | Default: Lyon |
| employee_count | INTEGER | |
| linkedin_url | TEXT | |
| founded_year | INTEGER | |
| research | TEXT | Free-text research notes for personalization |
| needs_name_cleanup | BOOLEAN | Flag for LLM name normalization |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

**Dropped columns:** `clean_name`, `stage`, `tier`, `sub_sector`, `research_status`
> `research_status` is now computed from `research IS NULL` in the view.

---

### `contacts`
Individual people at target companies.

| Column | Type | Notes |
|---|---|---|
| id | VARCHAR PRIMARY KEY | Apollo contact ID or generated from gmail_id |
| company_id | INTEGER | FK → companies.id |
| org_id | VARCHAR | Apollo org ID (used for linking when company_id is null) |
| first_name | VARCHAR | |
| last_name | VARCHAR | |
| title | VARCHAR | |
| email | VARCHAR | Primary contact method |
| linkedin | VARCHAR | URL only — job titles are set to NULL |
| industry | VARCHAR | |
| is_empty | BOOLEAN | Apollo flag for empty profiles |
| enrichment_status | VARCHAR | See enum below |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

**enrichment_status values:**
- `email_found` — verified email
- `risky_email` — has email but uncertain validity
- `unavailable` — no email, bounced, or person left company
- `pending` — not yet enriched

---

### `outreach`
One row per contact per campaign/template version.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PRIMARY KEY | |
| contact_id | VARCHAR | FK → contacts.id |
| company_id | INTEGER | FK → companies.id |
| snippet1 | TEXT | Personalization: industry/product angle |
| snippet2 | TEXT | Currently unused |
| snippet3 | TEXT | Personalization: company challenge |
| snippet4 | TEXT | Personalization: specific company detail |
| status | VARCHAR | See enum below |
| reply_sentiment | VARCHAR | null / negative / positive |
| sent_at | TIMESTAMP | When email was sent |
| replied_at | TIMESTAMP | When reply was received |
| notes | TEXT | Classification notes from email parser |
| template_version | VARCHAR | e.g. 'v1' |
| needs_snippet_cleanup | BOOLEAN | Flag for LLM snippet cleanup |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

**Unique constraint:** `(contact_id, template_version)`

**status values:**
- `not_sent` — not yet contacted
- `sent_1` — first email sent (also used for antispam/mailinblack replies)
- `sent_2` / `sent_3` — follow-up emails
- `auto_reply` — out of office
- `wrong_contact` — person left company
- `bounced` — delivery failure
- `replied` — human reply received
- `rejected` — confirmed no

---

### `upsert_log`
Audit trail for all upsert operations and unmatched email replies.

| Column | Type | Notes |
|---|---|---|
| id | SERIAL PRIMARY KEY | |
| operation | VARCHAR | e.g. 'upsert_company', 'email_reply_unmatched' |
| input_name | TEXT | |
| input_domain | TEXT | |
| input_org_id | TEXT | |
| matched_by | VARCHAR | domain / org_id / exact_name / fuzzy_name / new_insert / no_match |
| result_id | INTEGER | Resulting company ID |
| was_insert | BOOLEAN | true = new row, false = update |
| created_at | TIMESTAMP | |

---

## 3. Views

### `contacts_with_status`
Contacts table enriched with latest outreach status.

```sql
SELECT ct.*,
  COALESCE(
    (SELECT status FROM outreach o
     WHERE o.contact_id = ct.id
     ORDER BY created_at DESC LIMIT 1),
    'not_sent'
  ) as current_outreach_status
FROM contacts ct;
```

Use this view instead of `contacts` whenever you need outreach state alongside contact data.

---

### `companies_with_stats`
Companies enriched with contact counts, outreach progress, and research status.

Key computed columns:
- `research_status` — `'researched'` if research is not null, else `'not_researched'`
- `total_contacts` — all linked contacts
- `verified_contacts` — contacts with `email_found`
- `risky_contacts` — contacts with `risky_email`
- `contact_status` — human-readable summary: `no_contacts`, `3 verified`, `2 risky`, `X people_found`
- `sent_1_count`, `replied_count`, `bounced_count`, `rejected_count` — outreach breakdown
- `company_outreach_status` — `has_reply` / `fully_exhausted` / `in_progress` / `not_sent`

Use this view as the main dashboard query for prospecting decisions.

---

## 4. Key Functions

### `normalize_domain(p_domain TEXT) → TEXT`
Strips protocol, www, paths, query strings. Returns clean domain or NULL.

```sql
normalize_domain('http://www.company.fr/about?ref=1') → 'company.fr'
```

Always called before any domain comparison or insert.

---

### `upsert_company(10 params) → INTEGER`
Main deduplication function for companies. Returns company ID.

**Matching cascade (4 levels):**
1. Normalized domain
2. Apollo org_id
3. Exact name match (case-insensitive)
4. Fuzzy name match via pg_trgm (similarity > 0.8, only when no domain/org_id)

**Update behavior:**
- `domain`, `org_id`, `industry`, `employee_count`, `linkedin_url`, `founded_year` → fill empty only (COALESCE)
- `country`, `city`, `research` → overwrite only if incoming value is not null/empty

**Parameters (in order for n8n):**
```
$1  p_name VARCHAR
$2  p_domain VARCHAR
$3  p_org_id VARCHAR
$4  p_industry VARCHAR
$5  p_country VARCHAR
$6  p_city VARCHAR
$7  p_employee_count INTEGER
$8  p_linkedin_url TEXT
$9  p_founded_year INTEGER
$10 p_research TEXT
```

**n8n SQL:**
```sql
SELECT upsert_company($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) AS id
```

---

### `upsert_contact(11 params) → VARCHAR`
Upserts contacts using Apollo contact ID as primary key.

**n8n SQL:**
```sql
SELECT upsert_contact($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) AS id
```

**Parameters:** contact_id, company_id, org_id, first_name, last_name, title, email, linkedin, industry, is_empty, enrichment_status

---

### `upsert_company_dryrun(same params) → TABLE`
Identical matching logic but no writes. Returns what would happen including `normalized_domain` for validation.

```sql
SELECT would_match_by, COUNT(*),
  COUNT(*) FILTER (WHERE would_be_insert) as new_inserts
FROM upsert_log
GROUP BY would_match_by;
```

---

### `prepare_company_names() → TABLE`
Batch cleanup function. Run after any bulk import:
1. Replaces dots with spaces
2. Replaces slashes with spaces
3. Removes emojis and non-latin characters
4. Cleans double spaces
5. Marks complex cases with `needs_name_cleanup = TRUE` for LLM
6. Applies INITCAP title case to names longer than 4 chars

```sql
SELECT * FROM prepare_company_names();
```

---

## 5. Extensions Required

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- fuzzy name matching
SET neon.allow_unstable_extensions = 'true';
CREATE EXTENSION IF NOT EXISTS pgrag CASCADE;  -- LLM calls from SQL
SELECT rag.openai_set_api_key('sk-...');
```

---

## 6. n8n Workflow Architecture

### Import Pipeline
```
Google Sheets / CSV
  → Code node (normalize domain, map fields)
  → Execute Query: upsert_company() → returns postgres_company_id
  → Execute Query: upsert_contact() → links contact to company
```

**Critical:** Domain normalization must happen in the Code node AND inside `normalize_domain()`. The function is the last line of defense.

**Code node domain normalization:**
```javascript
const domain = (item.json.company_domain || '')
  .trim().toLowerCase()
  .replace(/^https?:\/\//, '')
  .replace(/^www\./, '')
  .replace(/\/$/, '')
  .replace(/\/.*$/, '') || null;
```

---

### Email Reply Parser
```
Gmail (Get Many, filter: subject:"candidat PM" in:inbox -from:me)
  → Code node (classify email + extract name/email/domain)
  → Execute Query: upsert new contact if email unknown
  → Execute Query: update outreach status
```

**Email classification categories:**

| Pattern | Status | Action |
|---|---|---|
| postmaster, Undeliverable | bounced | mark contact unavailable |
| Mailinblack, antispam | sent_1 | keep in pipeline |
| Réponse automatique, OOO | auto_reply | no action |
| ne fais plus partie | wrong_contact | mark unavailable |
| Human reply | replied + negative | update outreach |

**Outreach update query:**
```sql
UPDATE outreach o
SET status = $1, reply_sentiment = $2,
    replied_at = $3::TIMESTAMP, notes = $4, updated_at = NOW()
FROM contacts ct
WHERE ct.id = o.contact_id
AND LOWER(ct.email) = LOWER($5)
AND o.status = 'sent_1'
RETURNING o.id, o.contact_id, o.status;
```

Matching is email-only (no domain fallback). If no match is found, the reply is logged to `upsert_log` with `operation = 'email_reply_unmatched'` for manual review.

**New contact from reply query:**
```sql
INSERT INTO contacts (id, company_id, first_name, last_name, email, enrichment_status)
SELECT $1, c.id, $4, $5, $2, 'email_found'
FROM companies c
WHERE c.domain = $3
AND NOT EXISTS (SELECT 1 FROM contacts WHERE LOWER(email) = LOWER($2))
LIMIT 1
ON CONFLICT (id) DO NOTHING;
```

---

## 7. Data Quality Rules

### Domain
- Always normalize before insert
- Check: `SELECT COUNT(*) FROM companies WHERE domain ~ '^https?://'`
- Fix: `UPDATE companies SET domain = normalize_domain(domain) WHERE domain ~ '^https?://'`
- Duplicate check: group by `normalize_domain(domain)` HAVING COUNT > 1

### Company Names
- After bulk import always run `prepare_company_names()`
- LLM cleanup prompt for `needs_name_cleanup = TRUE`:
  > Return ONLY the clean brand name. No explanation. Remove legal suffixes (SAS, SARL, SA, LLC, Ltd, Inc, GmbH). Remove descriptions after -, |, –, (, [. Keep & and + if part of brand. Title Case unless acronym under 6 chars.
- Model: `gpt-4o-mini`, max_tokens: 20

### Contacts
- LinkedIn field: URLs only — job titles must be set to NULL
- Delete rows with empty name AND empty email
- Fix orphaned contacts via org_id: `UPDATE contacts SET company_id = c.id FROM companies c WHERE contacts.org_id = c.org_id AND contacts.company_id IS NULL`

### Outreach Snippets
- Flag dirty: `needs_snippet_cleanup = TRUE` where snippet contains `Voici`, `« `, `### `, `La réponse est`, or LENGTH > 200
- LLM cleanup: extract only the final phrase inside guillemets

---

## 8. Common Diagnostic Queries

```sql
-- Domain health
SELECT
  CASE
    WHEN domain IS NULL THEN 'null'
    WHEN domain ~ '^https?://' THEN 'has http/https'
    WHEN domain ~ '^www\.' THEN 'has www'
    WHEN domain ~ '[A-Z]' THEN 'has uppercase'
    ELSE 'clean'
  END as issue,
  COUNT(*)
FROM companies GROUP BY 1;

-- Duplicate domains
SELECT normalize_domain(domain) as clean_domain, COUNT(*), array_agg(id)
FROM companies WHERE domain IS NOT NULL
GROUP BY 1 HAVING COUNT(*) > 1;

-- Orphaned contacts
SELECT COUNT(*) FROM contacts WHERE company_id IS NULL;

-- Outreach status breakdown
SELECT status, COUNT(*) FROM outreach GROUP BY status ORDER BY count DESC;

-- Companies by contact status
SELECT contact_status, COUNT(*) FROM companies_with_stats GROUP BY 1;

-- Check for multiple function versions (should only be 1)
SELECT proname, pg_get_function_identity_arguments(oid) as args
FROM pg_proc WHERE proname = 'upsert_company';

-- Recent upsert matching breakdown
SELECT matched_by, COUNT(*),
  COUNT(*) FILTER (WHERE was_insert) as inserts,
  COUNT(*) FILTER (WHERE NOT was_insert) as updates
FROM upsert_log
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY matched_by;

-- Unmatched email replies for manual review
SELECT * FROM upsert_log
WHERE operation = 'email_reply_unmatched'
ORDER BY created_at DESC;
```

---

## 9. Known Issues & Gotchas

1. **Multiple function versions** — Postgres keeps old versions if parameter signatures differ. Always check `pg_proc` after updates and drop old versions explicitly before recreating.

2. **View dependencies** — dropping a column that a view depends on requires `DROP VIEW` first, then `ALTER TABLE`, then `CREATE VIEW`. Never use `DROP ... CASCADE` without checking what depends on it first.

3. **COALESCE direction matters:**
   - `COALESCE(existing, incoming)` = fill empty only
   - `COALESCE(incoming, existing)` = overwrite if incoming not null
   - Plain assignment = always overwrite including with NULL

4. **Antispam replies** — Mailinblack sends verification emails that look like replies. Treat as `sent_1` to keep the contact in the outreach pipeline.

5. **Per-contact status, not per-company** — one rejection from a contact does not stop outreach to other contacts at the same company. Company-level status is derived in the view, never stored.

6. **pgrag API calls** — each row = one API call. Always use `WHERE needs_name_cleanup = TRUE LIMIT N` to control costs.

7. **Empty string vs NULL** — always use `NULLIF(TRIM(value), '')` when inserting to avoid storing empty strings instead of NULL. The views and COALESCE logic assume NULL means missing.

---

## 10. Sequence for Fresh Import

```sql
-- 1. Run n8n workflow (upsert_company → upsert_contact)

-- 2. Fix orphaned contacts
UPDATE contacts ct SET company_id = c.id
FROM companies c
WHERE ct.org_id = c.org_id AND ct.company_id IS NULL;

-- 3. Clean dirty domains
UPDATE companies SET domain = normalize_domain(domain)
WHERE domain ~ '^https?://' OR domain ~ '^www\.';

-- 4. Clean company names
SELECT * FROM prepare_company_names();

-- 5. Run LLM on flagged names (via pgrag)
UPDATE companies SET name = (
  SELECT rag.openai_chat_completion(json_build_object(
    'model', 'gpt-4o-mini', 'max_tokens', 20,
    'messages', json_build_array(
      json_build_object('role', 'system', 'content',
        'Return ONLY the clean brand name. No explanation. Remove legal suffixes (SAS, SARL, SA, LLC, Ltd, Inc, GmbH). Remove descriptions after -, |, (, [. Keep & and +. Title Case unless acronym.'),
      json_build_object('role', 'user', 'content',
        'Company: ' || name || E'\nDomain: ' || COALESCE(domain, 'unknown'))
    )
  )::json) -> 'choices' -> 0 -> 'message' ->> 'content'
), needs_name_cleanup = FALSE
WHERE needs_name_cleanup = TRUE;

-- 6. Default country/city
UPDATE companies SET country = 'France', city = 'Lyon'
WHERE (country IS NULL OR TRIM(country) = '')
AND (city IS NULL OR TRIM(city) = '');

-- 7. Delete empty rows
DELETE FROM companies WHERE name IS NULL OR TRIM(name) = '';
DELETE FROM contacts
WHERE (first_name IS NULL OR TRIM(first_name) = '')
AND (last_name IS NULL OR TRIM(last_name) = '')
AND (email IS NULL OR TRIM(email) = '');

-- 8. Delete companies with no identifiers
DELETE FROM companies WHERE domain IS NULL AND org_id IS NULL;
```
