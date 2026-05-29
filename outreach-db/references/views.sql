-- ============================================================
-- VIEWS
-- ============================================================

-- Drop order matters due to dependencies
-- DROP VIEW IF EXISTS companies_with_stats;
-- DROP VIEW IF EXISTS contacts_with_status;

-- ------------------------------------------------------------
-- contacts_with_status
-- Adds current outreach status to every contact row
-- Use instead of contacts table whenever outreach state needed
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW contacts_with_status AS
SELECT
  ct.*,
  COALESCE(
    (SELECT status
     FROM outreach o
     WHERE o.contact_id = ct.id
     ORDER BY created_at DESC
     LIMIT 1),
    'not_sent'
  ) as current_outreach_status
FROM contacts ct;


-- ------------------------------------------------------------
-- companies_with_stats
-- Main dashboard view — companies + contact counts + outreach progress
-- Use this as primary query for prospecting decisions
-- ------------------------------------------------------------
CREATE OR REPLACE VIEW companies_with_stats AS
SELECT
  c.*,

  -- Research status derived from whether research column has content
  CASE
    WHEN c.research IS NULL OR TRIM(c.research) = '' THEN 'not_researched'
    ELSE 'researched'
  END as research_status,

  -- Contact counts by enrichment status
  COUNT(ct.id)                                                        as total_contacts,
  COUNT(ct.id) FILTER (WHERE ct.enrichment_status = 'email_found')   as verified_contacts,
  COUNT(ct.id) FILTER (WHERE ct.enrichment_status = 'risky_email')   as risky_contacts,
  COUNT(ct.id) FILTER (WHERE ct.enrichment_status = 'unavailable')   as unavailable_contacts,

  -- Human-readable contact status
  CASE
    WHEN COUNT(ct.id) = 0
      THEN 'no_contacts'
    WHEN COUNT(ct.id) FILTER (WHERE ct.enrichment_status = 'email_found') > 0
      THEN COUNT(ct.id) FILTER (WHERE ct.enrichment_status = 'email_found')::TEXT || ' verified'
    WHEN COUNT(ct.id) FILTER (WHERE ct.enrichment_status = 'risky_email') > 0
      THEN COUNT(ct.id) FILTER (WHERE ct.enrichment_status = 'risky_email')::TEXT || ' risky'
    WHEN COUNT(ct.id) FILTER (WHERE ct.enrichment_status = 'unavailable') > 0
      THEN COUNT(ct.id)::TEXT || ' people_found'
    ELSE 'people_found'
  END as contact_status,

  -- Outreach sequence counts
  COUNT(o.id) FILTER (WHERE o.status = 'sent_1')   as sent_1_count,
  COUNT(o.id) FILTER (WHERE o.status = 'sent_2')   as sent_2_count,
  COUNT(o.id) FILTER (WHERE o.status = 'sent_3')   as sent_3_count,
  COUNT(o.id) FILTER (WHERE o.status = 'replied')  as replied_count,
  COUNT(o.id) FILTER (WHERE o.status = 'rejected') as rejected_count,
  COUNT(o.id) FILTER (WHERE o.status = 'bounced')  as bounced_count,

  -- Company-level outreach status derived from all contacts
  CASE
    WHEN COUNT(o.id) FILTER (WHERE o.status = 'replied') > 0
      THEN 'has_reply'
    WHEN COUNT(o.id) > 0
     AND COUNT(o.id) FILTER (WHERE o.status NOT IN ('bounced', 'rejected', 'wrong_contact')) = 0
      THEN 'fully_exhausted'
    WHEN COUNT(o.id) FILTER (WHERE o.status LIKE 'sent_%') > 0
      THEN 'in_progress'
    ELSE 'not_sent'
  END as company_outreach_status

FROM companies c
LEFT JOIN contacts ct ON ct.company_id = c.id
LEFT JOIN outreach o  ON o.company_id  = c.id
GROUP BY c.id;
