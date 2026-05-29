-- ============================================================
-- FUNCTIONS
-- Create in this order: normalize_domain → upsert_company
--                       → upsert_company_dryrun → upsert_contact
--                       → prepare_company_names
-- ============================================================


-- ------------------------------------------------------------
-- normalize_domain
-- Always create this first — used by all other functions
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION normalize_domain(p_domain TEXT)
RETURNS TEXT AS $$
DECLARE
  v_result TEXT;
BEGIN
  IF p_domain IS NULL OR TRIM(p_domain) = '' THEN
    RETURN NULL;
  END IF;
  v_result := LOWER(TRIM(p_domain));
  v_result := REGEXP_REPLACE(v_result, '^https?://', '');
  v_result := REGEXP_REPLACE(v_result, '^www\.', '');
  v_result := REGEXP_REPLACE(v_result, '/.*$', '');
  v_result := REGEXP_REPLACE(v_result, '\?.*$', '');
  v_result := TRIM(v_result);
  RETURN NULLIF(v_result, '');
END;
$$ LANGUAGE plpgsql;


-- ------------------------------------------------------------
-- upsert_company
-- 4-level dedup: domain → org_id → exact name → fuzzy name
-- Logs every operation to upsert_log
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION upsert_company(
  p_name          VARCHAR,
  p_domain        VARCHAR,
  p_org_id        VARCHAR,
  p_industry      VARCHAR,
  p_country       VARCHAR,
  p_city          VARCHAR,
  p_employee_count INTEGER,
  p_linkedin_url  TEXT,
  p_founded_year  INTEGER,
  p_research      TEXT
) RETURNS INTEGER AS $$
DECLARE
  v_id         INTEGER;
  v_domain     TEXT;
  v_org_id     VARCHAR;
  v_matched_by VARCHAR;
  v_was_insert BOOLEAN := FALSE;
BEGIN
  v_domain  := normalize_domain(p_domain);
  v_org_id  := NULLIF(TRIM(COALESCE(p_org_id, '')), '');

  -- LEVEL 1: domain
  IF v_domain IS NOT NULL THEN
    SELECT id INTO v_id FROM companies WHERE domain = v_domain LIMIT 1;
    IF v_id IS NOT NULL THEN v_matched_by := 'domain'; END IF;
  END IF;

  -- LEVEL 2: org_id
  IF v_id IS NULL AND v_org_id IS NOT NULL THEN
    SELECT id INTO v_id FROM companies WHERE org_id = v_org_id LIMIT 1;
    IF v_id IS NOT NULL THEN v_matched_by := 'org_id'; END IF;
  END IF;

  -- LEVEL 3: exact name
  IF v_id IS NULL AND p_name IS NOT NULL THEN
    SELECT id INTO v_id FROM companies
    WHERE LOWER(TRIM(name)) = LOWER(TRIM(p_name)) LIMIT 1;
    IF v_id IS NOT NULL THEN v_matched_by := 'exact_name'; END IF;
  END IF;

  -- LEVEL 4: fuzzy name (only when no domain and no org_id)
  IF v_id IS NULL AND p_name IS NOT NULL
     AND v_domain IS NULL AND v_org_id IS NULL THEN
    SELECT id INTO v_id FROM companies
    WHERE similarity(LOWER(name), LOWER(p_name)) > 0.8
    ORDER BY similarity(LOWER(name), LOWER(p_name)) DESC
    LIMIT 1;
    IF v_id IS NOT NULL THEN v_matched_by := 'fuzzy_name'; END IF;
  END IF;

  -- FOUND: update
  IF v_id IS NOT NULL THEN
    UPDATE companies SET
      -- fill empty only (stable identifiers)
      domain         = COALESCE(domain, v_domain),
      org_id         = COALESCE(org_id, v_org_id),
      industry       = COALESCE(industry, NULLIF(TRIM(p_industry), '')),
      employee_count = COALESCE(employee_count, p_employee_count),
      linkedin_url   = COALESCE(linkedin_url, NULLIF(TRIM(p_linkedin_url), '')),
      founded_year   = COALESCE(founded_year, p_founded_year),
      -- overwrite if incoming not null (refreshable fields)
      country        = CASE WHEN NULLIF(TRIM(p_country), '') IS NOT NULL
                         THEN TRIM(p_country) ELSE country END,
      city           = CASE WHEN NULLIF(TRIM(p_city), '') IS NOT NULL
                         THEN TRIM(p_city) ELSE city END,
      research       = CASE WHEN NULLIF(TRIM(p_research), '') IS NOT NULL
                         THEN TRIM(p_research) ELSE research END,
      updated_at     = NOW()
    WHERE id = v_id;

  -- NOT FOUND: insert
  ELSE
    INSERT INTO companies (
      name, domain, org_id, industry,
      country, city, employee_count,
      linkedin_url, founded_year, research
    ) VALUES (
      LEFT(TRIM(p_name), 255),
      v_domain,
      v_org_id,
      NULLIF(LEFT(TRIM(COALESCE(p_industry,    '')), 100), ''),
      NULLIF(TRIM(COALESCE(p_country,  '')), ''),
      NULLIF(TRIM(COALESCE(p_city,     '')), ''),
      p_employee_count,
      NULLIF(TRIM(COALESCE(p_linkedin_url, '')), ''),
      p_founded_year,
      NULLIF(TRIM(COALESCE(p_research, '')), '')
    )
    RETURNING id INTO v_id;
    v_matched_by := 'new_insert';
    v_was_insert := TRUE;
  END IF;

  INSERT INTO upsert_log (
    operation, input_name, input_domain,
    input_org_id, matched_by, result_id, was_insert
  ) VALUES (
    'upsert_company', p_name, p_domain,
    p_org_id, v_matched_by, v_id, v_was_insert
  );

  RETURN v_id;
END;
$$ LANGUAGE plpgsql;


-- ------------------------------------------------------------
-- upsert_company_dryrun
-- Identical matching logic, zero writes
-- Returns normalized_domain so you can verify normalization
-- Run before every bulk import
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION upsert_company_dryrun(
  p_name          VARCHAR,
  p_domain        VARCHAR,
  p_org_id        VARCHAR,
  p_industry      VARCHAR,
  p_country       VARCHAR,
  p_city          VARCHAR,
  p_employee_count INTEGER,
  p_linkedin_url  TEXT,
  p_founded_year  INTEGER,
  p_research      TEXT
) RETURNS TABLE (
  would_match_id   INTEGER,
  would_match_by   VARCHAR,
  would_be_insert  BOOLEAN,
  input_name       VARCHAR,
  input_domain     VARCHAR,
  normalized_domain TEXT,
  input_org_id     VARCHAR
) AS $$
DECLARE
  v_id         INTEGER;
  v_domain     TEXT;
  v_org_id     VARCHAR;
  v_matched_by VARCHAR;
  v_was_insert BOOLEAN := FALSE;
BEGIN
  v_domain := normalize_domain(p_domain);
  v_org_id := NULLIF(TRIM(COALESCE(p_org_id, '')), '');

  IF v_domain IS NOT NULL THEN
    SELECT id INTO v_id FROM companies WHERE domain = v_domain LIMIT 1;
    IF v_id IS NOT NULL THEN v_matched_by := 'domain'; END IF;
  END IF;

  IF v_id IS NULL AND v_org_id IS NOT NULL THEN
    SELECT id INTO v_id FROM companies WHERE org_id = v_org_id LIMIT 1;
    IF v_id IS NOT NULL THEN v_matched_by := 'org_id'; END IF;
  END IF;

  IF v_id IS NULL AND p_name IS NOT NULL THEN
    SELECT id INTO v_id FROM companies
    WHERE LOWER(TRIM(name)) = LOWER(TRIM(p_name)) LIMIT 1;
    IF v_id IS NOT NULL THEN v_matched_by := 'exact_name'; END IF;
  END IF;

  IF v_id IS NULL AND p_name IS NOT NULL
     AND v_domain IS NULL AND v_org_id IS NULL THEN
    SELECT id INTO v_id FROM companies
    WHERE similarity(LOWER(name), LOWER(p_name)) > 0.8
    ORDER BY similarity(LOWER(name), LOWER(p_name)) DESC
    LIMIT 1;
    IF v_id IS NOT NULL THEN v_matched_by := 'fuzzy_name'; END IF;
  END IF;

  IF v_id IS NULL THEN
    v_matched_by := 'no_match_will_insert';
    v_was_insert := TRUE;
  END IF;

  RETURN QUERY SELECT
    v_id, v_matched_by, v_was_insert,
    p_name, p_domain, v_domain, p_org_id;
END;
$$ LANGUAGE plpgsql;


-- ------------------------------------------------------------
-- upsert_contact
-- Keyed on external contact ID (Apollo or generated)
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION upsert_contact(
  p_id               VARCHAR,
  p_company_id       INTEGER,
  p_org_id           VARCHAR,
  p_first_name       VARCHAR,
  p_last_name        VARCHAR,
  p_title            VARCHAR,
  p_email            VARCHAR,
  p_linkedin         VARCHAR,
  p_industry         VARCHAR,
  p_is_empty         BOOLEAN,
  p_enrichment_status VARCHAR
) RETURNS VARCHAR AS $$
BEGIN
  INSERT INTO contacts (
    id, company_id, org_id,
    first_name, last_name, title,
    email, linkedin, industry,
    is_empty, enrichment_status
  ) VALUES (
    p_id, p_company_id, p_org_id,
    p_first_name, p_last_name, p_title,
    p_email, p_linkedin, p_industry,
    p_is_empty, p_enrichment_status
  )
  ON CONFLICT (id) DO UPDATE SET
    email             = COALESCE(EXCLUDED.email, contacts.email),
    title             = COALESCE(EXCLUDED.title, contacts.title),
    linkedin          = COALESCE(EXCLUDED.linkedin, contacts.linkedin),
    enrichment_status = EXCLUDED.enrichment_status,
    updated_at        = NOW();

  RETURN p_id;
END;
$$ LANGUAGE plpgsql;


-- ------------------------------------------------------------
-- prepare_company_names
-- Run after every bulk import before LLM cleanup
-- Steps: dots→space, slashes→space, remove emojis,
--        clean double spaces, flag complex cases, apply INITCAP
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION prepare_company_names()
RETURNS TABLE(
  total_marked   INTEGER,
  dot_cleaned    INTEGER,
  emoji_cleaned  INTEGER,
  slash_cleaned  INTEGER
) AS $$
DECLARE
  v_dot_cleaned   INTEGER;
  v_emoji_cleaned INTEGER;
  v_slash_cleaned INTEGER;
  v_total_marked  INTEGER;
BEGIN
  -- Replace dots with space
  UPDATE companies
  SET name = TRIM(REGEXP_REPLACE(
    REGEXP_REPLACE(name, '\.', ' ', 'g'), '\s+', ' ', 'g'))
  WHERE name ~ '\.';
  GET DIAGNOSTICS v_dot_cleaned = ROW_COUNT;

  -- Replace slashes with space
  UPDATE companies
  SET name = TRIM(REGEXP_REPLACE(
    REGEXP_REPLACE(name, '\/', ' ', 'g'), '\s+', ' ', 'g'))
  WHERE name ~ '\/';
  GET DIAGNOSTICS v_slash_cleaned = ROW_COUNT;

  -- Remove emojis and non-latin characters
  UPDATE companies
  SET name = TRIM(REGEXP_REPLACE(
    name, '[^\u0000-\u007F\u00C0-\u024F\u1E00-\u1EFF]', '', 'g'))
  WHERE name ~ '[^\u0000-\u007F\u00C0-\u024F\u1E00-\u1EFF]';
  GET DIAGNOSTICS v_emoji_cleaned = ROW_COUNT;

  -- Clean up double spaces
  UPDATE companies
  SET name = TRIM(REGEXP_REPLACE(name, '\s+', ' ', 'g'))
  WHERE name ~ '\s{2,}';

  -- Flag complex cases for LLM cleanup
  UPDATE companies SET needs_name_cleanup = TRUE
  WHERE name LIKE '%STRIP LEGAL%'
    OR name LIKE '%Clean Brand Name%'
    OR name LIKE '%step by step%'
    OR name LIKE '%To clean%'
    OR name LIKE '%To determine%'
    OR name ~ ' - [A-Za-z]'
    OR name ~ ' \| '
    OR name ~ ' – '
    OR name ~ ' — '
    OR name ~ '\(.*\)'
    OR name ~ '\[.*\]'
    OR name ~ '\,'
    OR name ~* '\m(SAS|SARL|SA|SNC|LLC|Ltd|Inc|Corp|GmbH|AG|PLC|BV|NV|SL|AB)\M'
    OR LENGTH(name) > 60
    OR name ~ '[\!\?\;\:\"\`\~\^\*\[\]\{\}\<\>]';
  GET DIAGNOSTICS v_total_marked = ROW_COUNT;

  -- Apply Title Case to clean names only
  UPDATE companies
  SET name = INITCAP(LOWER(name))
  WHERE LENGTH(name) > 4
  AND needs_name_cleanup = FALSE;

  RETURN QUERY SELECT
    v_total_marked, v_dot_cleaned, v_emoji_cleaned, v_slash_cleaned;
END;
$$ LANGUAGE plpgsql;
