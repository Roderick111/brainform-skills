---
name: outreach-db
description: >
  Design and build production-ready cold outreach CRM databases in PostgreSQL (Neon or any Postgres).
  Use this skill whenever the user wants to set up a database for cold outreach, lead tracking, sales
  prospecting, job search pipelines, or any contact/company management system. Triggers on phrases like
  "outreach database", "CRM in Postgres", "contact pipeline", "lead tracking DB", "cold email database",
  or any request to build a SQL-backed prospecting system. Also trigger when the user has an existing
  outreach DB and needs deduplication, enrichment, email reply parsing, or n8n workflow integration.
  This skill covers: schema design, 4-level upsert deduplication functions, LLM-powered data cleanup
  via pgrag, n8n import workflows, and Gmail reply parsing pipelines.
---

# Outreach DB Skill

Battle-tested system for cold outreach CRM databases in PostgreSQL. Built and refined at scale
(~5000 companies, ~3000 contacts, full Gmail reply parsing loop).

## Quick Decision Tree
```
User wants to...
├── Start from scratch        → Section 1 (Schema) + Section 2 (Functions)
├── Fix deduplication         → Section 3 (Cleanup)
├── Build n8n workflows       → Section 4 (n8n)
├── Parse email replies       → Section 5 (Gmail)
└── Clean dirty data          → Section 3 (Cleanup)
```

Full SQL in reference files:
- `references/functions.sql` — all Postgres functions (copy-paste ready)
- `references/views.sql` — contacts_with_status + companies_with_stats views
- `references/n8n-code-nodes.js` — domain normalization + Gmail classifier

---

## Section 1: Schema

### Extensions (run first)
```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SET neon.allow_unstable_extensions = 'true'; -- Neon only
CREATE EXTENSION IF NOT EXISTS pgrag CASCADE; -- Neon only
SELECT rag.openai_set_api_key('sk-...');
```

### Table Order
Create: `companies` → `contacts` → `outreach` → `upsert_log`
```sql
CREATE TABLE companies (
  id              SERIAL PRIMARY KEY,
  name            VARCHAR(255) NOT NULL,
  domain          VARCHAR UNIQUE,        -- normalized, primary dedup key
  org_id          VARCHAR UNIQUE,        -- external API ID, secondary dedup key
  industry        VARCHAR(100),
  country         VARCHAR(100),
  city            VARCHAR(100),
  employee_count  INTEGER,
  linkedin_url    TEXT,
  founded_year    INTEGER,
  research        TEXT,                  -- personalization notes
  needs_name_cleanup BOOLEAN DEFAULT FALSE,
  created_at      TIMESTAMP DEFAULT NOW(),
  updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE contacts (
  id                VARCHAR PRIMARY KEY, -- external ID or gmail_id
  company_id        INTEGER REFERENCES companies(id),
  org_id            VARCHAR,             -- for linking when company_id is null
  first_name        VARCHAR,
  last_name         VARCHAR,
  title             VARCHAR,
  email             VARCHAR,
  linkedin          VARCHAR,             -- URLs only, never job titles
  industry          VARCHAR,
  is_empty          BOOLEAN DEFAULT FALSE,
  enrichment_status VARCHAR DEFAULT 'pending',
  -- enum: email_found | risky_email | unavailable | pending
  created_at        TIMESTAMP DEFAULT NOW(),
  updated_at        TIMESTAMP DEFAULT NOW()
);

CREATE TABLE outreach (
  id               SERIAL PRIMARY KEY,
  contact_id       VARCHAR REFERENCES contacts(id),
  company_id       INTEGER REFERENCES companies(id),
  snippet1         TEXT,
  snippet2         TEXT,
  snippet3         TEXT,
  snippet4         TEXT,
  status           VARCHAR DEFAULT 'not_sent',
  -- enum: not_sent | sent_1 | sent_2 | sent_3 | auto_reply | wrong_contact | bounced | replied | rejected
  reply_sentiment  VARCHAR,             -- null | negative | positive
  sent_at          TIMESTAMP,
  replied_at       TIMESTAMP,
  notes            TEXT,
  template_version VARCHAR DEFAULT 'v1',
  needs_snippet_cleanup BOOLEAN DEFAULT FALSE,
  created_at       TIMESTAMP DEFAULT NOW(),
  updated_at       TIMESTAMP DEFAULT NOW(),
  CONSTRAINT unique_contact_template UNIQUE (contact_id, template_version)
);

CREATE TABLE upsert_log (
  id           SERIAL PRIMARY KEY,
  operation    VARCHAR(50),
  input_name   TEXT,
  input_domain TEXT,
  input_org_id TEXT,
  matched_by   VARCHAR(50), -- domain|org_id|exact_name|fuzzy_name|new_insert|no_match
  result_id    INTEGER,
  was_insert   BOOLEAN,
  created_at   TIMESTAMP DEFAULT NOW()
);
```

---

## Section 2: Functions Overview

Read `references/functions.sql` for full SQL. Summary:

| Function | Returns | Purpose |
|---|---|---|
| `normalize_domain(text)` | TEXT | Strip http/www/paths — create first |
| `upsert_company(10 params)` | INTEGER | 4-level dedup, logs to upsert_log |
| `upsert_contact(11 params)` | VARCHAR | Contact upsert, keyed on external ID |
| `upsert_company_dryrun(10 params)` | TABLE | Zero-write validation before bulk import |
| `prepare_company_names()` | TABLE | Post-import batch cleanup |

**4-level matching in upsert_company:**
1. Normalized domain
2. org_id
3. Exact name (case-insensitive)
4. Fuzzy name, pg_trgm similarity > 0.8 (only when no domain/org_id)

**COALESCE rules:**
- `COALESCE(existing, incoming)` → fill empty only (stable fields: domain, org_id, linkedin)
- `COALESCE(incoming, existing)` → incoming wins if not null
- `= p_value` → always overwrite (refreshable fields: country, city, research)

**After any function update, check for old versions:**
```sql
SELECT proname, pg_get_function_identity_arguments(oid) as args
FROM pg_proc WHERE proname = 'upsert_company';
-- If more than 1 row, drop old signatures explicitly
```

---

## Section 3: Dedup & Cleanup
```sql
-- Domain health check
SELECT CASE
  WHEN domain IS NULL THEN 'null'
  WHEN domain ~ '^https?://' THEN 'has http/https'
  WHEN domain ~ '^www\.' THEN 'has www'
  WHEN domain ~ '[A-Z]' THEN 'has uppercase'
  WHEN domain ~ '\/' THEN 'has path'
  ELSE 'clean'
END as issue, COUNT(*)
FROM companies GROUP BY 1 ORDER BY count DESC;

-- Fix dirty domains
UPDATE companies SET domain = normalize_domain(domain)
WHERE domain ~ '^https?://' OR domain ~ '^www\.';

-- Find duplicate domains
SELECT normalize_domain(domain) as clean, COUNT(*), array_agg(id)
FROM companies WHERE domain IS NOT NULL
GROUP BY 1 HAVING COUNT(*) > 1;

-- Fix orphaned contacts
UPDATE contacts ct SET company_id = c.id
FROM companies c WHERE ct.org_id = c.org_id AND ct.company_id IS NULL;
```

**Standard post-import sequence:**
```sql
UPDATE contacts ct SET company_id = c.id FROM companies c
  WHERE ct.org_id = c.org_id AND ct.company_id IS NULL;
UPDATE companies SET domain = normalize_domain(domain)
  WHERE domain ~ '^https?://' OR domain ~ '^www\.';
SELECT * FROM prepare_company_names();
UPDATE companies SET country = 'France', city = 'Lyon'
  WHERE (country IS NULL OR TRIM(country) = '') AND (city IS NULL OR TRIM(city) = '');
DELETE FROM companies WHERE name IS NULL OR TRIM(name) = '';
DELETE FROM contacts WHERE (first_name IS NULL OR TRIM(first_name) = '')
  AND (last_name IS NULL OR TRIM(last_name) = '') AND (email IS NULL OR TRIM(email) = '');
DELETE FROM companies WHERE domain IS NULL AND org_id IS NULL;
```

**LLM name cleanup via pgrag:**
```sql
UPDATE companies SET name = (
  SELECT rag.openai_chat_completion(json_build_object(
    'model', 'gpt-4o-mini', 'max_tokens', 20,
    'messages', json_build_array(
      json_build_object('role', 'system', 'content',
        'Return ONLY the clean brand name. No explanation. Remove legal suffixes (SAS, SARL, SA, LLC, Ltd, Inc, GmbH). Remove descriptions after -, |, (, [. Keep & and +. Title Case unless acronym under 6 chars.'),
      json_build_object('role', 'user', 'content',
        'Company: ' || name || E'\nDomain: ' || COALESCE(domain, 'unknown'))
    ))::json) -> 'choices' -> 0 -> 'message' ->> 'content'
), needs_name_cleanup = FALSE
WHERE needs_name_cleanup = TRUE;
-- Use LIMIT N to control costs — each row = one API call
```

---

## Section 4: n8n Integration

**Import pipeline:**
```
CSV / Google Sheets / Apollo
  → Code node (normalize domain + map fields)
  → Execute Query: upsert_company() → postgres_company_id
  → Execute Query: upsert_contact()
```

**Code node domain normalization (always include):**
```javascript
const domain = (item.json.company_domain || '')
  .trim().toLowerCase()
  .replace(/^https?:\/\//, '')
  .replace(/^www\./, '')
  .replace(/\/$/, '')
  .replace(/\/.*$/, '') || null;
```

**Node type rule:** Use Execute Query for JOINs, custom functions, ON CONFLICT. Use built-in Insert/Update only for simple single-table ops with known IDs.

**upsert_company — SQL:**
```sql
SELECT upsert_company($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) AS id
```
**Parameters:** `[company_name, clean_domain, org_id, industry, country, city, employee_count, linkedin_url, founded_year, research]`

**upsert_contact — SQL:**
```sql
SELECT upsert_contact($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) AS id
```
**Parameters:** `[contact_id, postgres_company_id, org_id, first_name, last_name, title, email, linkedin, industry, is_empty, enrichment_status]`

---

## Section 5: Gmail Reply Parser

**Gmail node Search filter:**
```
subject:"your subject" in:inbox -from:me
```

**Pipeline:**
```
Gmail Get Many → Code node → Upsert contact → Update outreach status
```

**Classification rules:**

| Pattern | Status |
|---|---|
| `postmaster@`, `Undeliverable` | `bounced` |
| Mailinblack, `antispam` | `sent_1` (keep in pipeline) |
| `Réponse automatique`, OOO, sabbatical | `auto_reply` |
| Left company, redirected | `wrong_contact` |
| Human reply | `replied` + sentiment `negative` |

Read `references/n8n-code-nodes.js` for the full classifier with name/email/domain extraction.

**Upsert contact from reply:**
```sql
INSERT INTO contacts (id, company_id, first_name, last_name, email, enrichment_status)
SELECT $1, c.id, $4, $5, $2, 'email_found'
FROM companies c WHERE c.domain = $3
AND NOT EXISTS (SELECT 1 FROM contacts WHERE LOWER(email) = LOWER($2))
LIMIT 1 ON CONFLICT (id) DO NOTHING;
```

**Update outreach status:**
```sql
UPDATE outreach o
SET status=$1, reply_sentiment=$2, replied_at=$3::TIMESTAMP, notes=$4, updated_at=NOW()
FROM contacts ct WHERE ct.id = o.contact_id
AND LOWER(ct.email) = LOWER($5) AND o.status = 'sent_1'
RETURNING o.id, o.contact_id, o.status;
```

> Match is email-only. Domain fallback excluded by design — one person's reply must not affect other contacts at the same company.

---

## Section 6: Gotchas

1. **Multiple function versions** — check `pg_proc`, drop old signatures explicitly
2. **View dependency errors** — `DROP VIEW` → `ALTER TABLE` → `CREATE VIEW`, never blindly CASCADE
3. **ON CONFLICT** requires a UNIQUE constraint in schema first
4. **Empty string ≠ NULL** — always `NULLIF(TRIM(value), '')`
5. **pgrag costs** — each row = one API call, always use LIMIT
6. **Antispam (Mailinblack)** — treat as `sent_1`, not rejection
7. **Per-contact status** — rejection from one contact never blocks others at same company
8. **Dry run first** — always run `upsert_company_dryrun` before bulk imports
