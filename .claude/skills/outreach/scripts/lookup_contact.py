#!/usr/bin/env python3
"""
Lookup contact/company data from Neon DB for outreach.
Input: email, domain, or domain with manual info.
Output: JSON to stdout.

Usage:
  uv run dev/scripts/lookup_contact.py john@suave.com
  uv run dev/scripts/lookup_contact.py suave.com
"""

import json
import os
import re
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

DB_URL = "postgresql://neondb_owner:npg_oa6NlAvr2PyL@ep-divine-tree-abtam3ue-pooler.eu-west-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Audits live in dev/audits/ at project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
AUDITS_DIR = _PROJECT_ROOT / "dev" / "audits"
AUDIT_BASE_URL = "https://brainform.beautiful-apps.com"

SENT_STATUSES = {"sent_1", "sent_2", "sent_3", "replied"}

# Fields to strip from output (used internally but not needed by LLM)
_CONTACT_INTERNAL = {"id", "outreach_status"}
_COMPANY_INTERNAL = {"id", "employee_count"}


def _clean_contact(c: dict) -> dict:
    return {k: v for k, v in c.items() if k not in _CONTACT_INTERNAL}


def _clean_company(c: dict | None) -> dict | None:
    if not c:
        return None
    return {k: v for k, v in c.items() if k not in _COMPANY_INTERNAL}


def is_email(s: str) -> bool:
    return "@" in s and "." in s.split("@")[-1]


def domain_from_email(email: str) -> str:
    return email.split("@")[-1].lower()


def _extract_domain_from_title(filepath: Path) -> str | None:
    """Read first 10 lines of audit HTML, extract domain from <title> tag."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            head = "".join(f.readline() for _ in range(10))
    except (OSError, UnicodeDecodeError):
        return None

    m = re.search(r"<title>.*?—\s*(.+?)\s*</title>", head, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower().strip()


def _normalize_domain(d: str) -> str:
    """Strip protocol, www, trailing slash. Return bare domain lowercase."""
    d = d.lower().strip().rstrip("/")
    if d.startswith(("http://", "https://")):
        d = d.split("//", 1)[1]
    if d.startswith("www."):
        d = d[4:]
    return d


def _slug_from_filename(filepath: Path) -> str:
    """Derive URL slug from filename: strip _com_ars_report and .html."""
    name = filepath.stem
    name = re.sub(r"_com_ars_report$", "", name)
    name = re.sub(r"_ars_report$", "", name)
    return name


def find_audit(domain: str) -> dict:
    """Find audit file by matching domain against <title> in each HTML file."""
    if not AUDITS_DIR.exists():
        return {"audit_exists": False, "audit_file": None, "audit_url": None}

    target = _normalize_domain(domain)

    for f in AUDITS_DIR.iterdir():
        if not f.name.endswith(".html"):
            continue
        title_domain = _extract_domain_from_title(f)
        if not title_domain:
            continue
        if _normalize_domain(title_domain) == target:
            slug = _slug_from_filename(f)
            return {
                "audit_exists": True,
                "audit_file": str(f),
                "audit_url": f"{AUDIT_BASE_URL}/{slug}",
            }

    return {"audit_exists": False, "audit_file": None, "audit_url": None}


def lookup_by_email(cur, email: str) -> dict:
    """Find contact by email, then get company."""
    cur.execute(
        """
        SELECT c.id, c.first_name, c.last_name, c.title, c.email,
               c.country,
               COALESCE(
                 (SELECT o.status FROM outreach o
                  WHERE o.contact_id = c.id
                  ORDER BY o.created_at DESC LIMIT 1),
                 'not_sent'
               ) as outreach_status
        FROM contacts c
        WHERE c.email = %s OR c.secondary_email = %s
        LIMIT 1
        """,
        (email, email),
    )
    contact_row = cur.fetchone()

    if not contact_row:
        # Try domain lookup as fallback
        domain = domain_from_email(email)
        return lookup_by_domain(cur, domain)

    contact = dict(contact_row)
    company_id = None

    # Get company_id from contact
    cur.execute(
        "SELECT company_id FROM contacts WHERE id = %s", (contact["id"],)
    )
    cid_row = cur.fetchone()
    if cid_row:
        company_id = cid_row["company_id"]

    company = get_company(cur, company_id)
    contacts = [contact]

    # Check outreach status
    already_contacted = []
    eligible = []
    for c in contacts:
        if c["outreach_status"] in SENT_STATUSES:
            already_contacted.append(c)
        else:
            eligible.append(c)

    domain = company["domain"] if company else domain_from_email(email)
    audit = find_audit(domain) if domain else {"audit_exists": False, "audit_url": None}

    return {
        "found": True,
        "input": email,
        "contacts": [_clean_contact(c) for c in eligible],
        "already_contacted": [_clean_contact(c) for c in already_contacted],
        "company": _clean_company(company),
        **audit,
    }


def lookup_by_domain(cur, domain: str) -> dict:
    """Find company by domain, then get eligible contacts."""
    cur.execute(
        "SELECT id FROM companies WHERE domain = normalize_domain(%s) LIMIT 1",
        (domain,),
    )
    row = cur.fetchone()

    if not row:
        audit = find_audit(domain)
        return {
            "found": False,
            "input": domain,
            "contacts": [],
            "already_contacted": [],
            "company": None,
            **audit,
        }

    company_id = row["id"]
    company = get_company(cur, company_id)

    # Get contacts with outreach status
    cur.execute(
        """
        SELECT c.id, c.first_name, c.last_name, c.title, c.email,
               c.country,
               COALESCE(
                 (SELECT o.status FROM outreach o
                  WHERE o.contact_id = c.id
                  ORDER BY o.created_at DESC LIMIT 1),
                 'not_sent'
               ) as outreach_status
        FROM contacts c
        WHERE c.company_id = %s
          AND c.email IS NOT NULL
          AND c.is_empty = FALSE
        ORDER BY RANDOM()
        """,
        (company_id,),
    )
    all_contacts = [dict(r) for r in cur.fetchall()]

    already_contacted = [c for c in all_contacts if c["outreach_status"] in SENT_STATUSES]
    eligible = [c for c in all_contacts if c["outreach_status"] not in SENT_STATUSES]

    # Max 3 eligible contacts
    eligible = eligible[:3]

    audit = find_audit(domain)

    return {
        "found": True,
        "input": domain,
        "contacts": [_clean_contact(c) for c in eligible],
        "already_contacted": [_clean_contact(c) for c in already_contacted],
        "company": _clean_company(company),
        **audit,
    }


def get_company(cur, company_id: int | None) -> dict | None:
    if not company_id:
        return None
    cur.execute(
        """
        SELECT id, name, domain, short_description, industry,
               country, employee_count
        FROM companies
        WHERE id = %s
        """,
        (company_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: lookup_contact.py <email_or_domain>"}))
        sys.exit(1)

    query = sys.argv[1].strip().lower()

    conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()

    try:
        if is_email(query):
            result = lookup_by_email(cur, query)
        else:
            result = lookup_by_domain(cur, query)

        print(json.dumps(result, default=str))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
