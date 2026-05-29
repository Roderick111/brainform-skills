#!/usr/bin/env python3
"""
Sync GetSales API → Neon DB for direct brand contacts.
Fetches leads via API, matches to DB contacts, updates pipeline_stage
(which triggers outreach_status via DB trigger).

Usage:
  uv run dev/scripts/sync_getsales.py
  uv run dev/scripts/sync_getsales.py --dry-run
  uv run dev/scripts/sync_getsales.py --all        # all lists, not just direct
"""

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

import psycopg2

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DB_URL = os.environ["DATABASE_URL"]

GS_API = "https://amazing.getsales.io/leads/api/leads/"
DIRECT_UUID = "a5211798-3c96-439d-88ad-3f2bc51a5bac"
AGENCY_UUID = "218982b5-0bf4-4da4-bba9-9b4d7268f4b9"


def normalize_linkedin(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip().rstrip("/").lower()
    url = re.sub(r"[?#].*$", "", url)
    m = re.search(r"linkedin\.com(/in/[a-z0-9_-]+)", url)
    return m.group(1) if m else None


def to_str(val) -> str | None:
    if val is None:
        return None
    v = str(val).strip()
    return v if v else None


def fetch_all_leads(token: str) -> list[dict]:
    """Fetch all leads from GetSales API, paginated."""
    all_items = []
    offset = 0
    limit = 100

    while True:
        url = f"{GS_API}?limit={limit}&offset={offset}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0",
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())

        items = data.get("data", [])
        if not items:
            break
        all_items.extend(items)
        offset += limit
        if len(items) < limit:
            break

    return all_items


def derive_pipeline_stage(markers: list[dict]) -> str | None:
    """Derive pipeline stage from GetSales markers."""
    for m in markers:
        inbox = m.get("linkedin_messages_inbox_count", 0) or 0
        if inbox > 0:
            return "Replied"
        accepted = m.get("linkedin_last_connection_accepted_at")
        if accepted:
            return "Engaging"
        sent = m.get("linkedin_last_connection_sent_at")
        if sent:
            return "Approaching"
    return "New"


def build_contact_indexes(cur):
    """Pre-load contact lookup indexes (same logic as import_getsales.py)."""
    cur.execute("SELECT id, linkedin FROM contacts WHERE linkedin IS NOT NULL")
    linkedin_to_id = {}
    for row in cur.fetchall():
        norm = normalize_linkedin(row[1])
        if norm:
            linkedin_to_id[norm] = row[0]

    cur.execute("SELECT id, LOWER(email) FROM contacts WHERE email IS NOT NULL")
    email_to_id = {row[1]: row[0] for row in cur.fetchall()}

    cur.execute("""
        SELECT c.id, comp.domain, LOWER(c.last_name)
        FROM contacts c
        JOIN companies comp ON comp.id = c.company_id
        WHERE c.last_name IS NOT NULL AND comp.domain IS NOT NULL
    """)
    domain_name_to_id = {}
    for row in cur.fetchall():
        key = f"{row[1]}|{row[2]}"
        domain_name_to_id[key] = row[0]

    cur.execute("""
        SELECT c.id, LOWER(CONCAT(c.first_name, ' ', c.last_name)), LOWER(comp.country)
        FROM contacts c
        JOIN companies comp ON comp.id = c.company_id
        WHERE c.first_name IS NOT NULL AND c.last_name IS NOT NULL AND comp.country IS NOT NULL
    """)
    fullname_country_to_id = {}
    dupes = set()
    for row in cur.fetchall():
        key = f"{row[1]}|{row[2]}"
        if key in fullname_country_to_id:
            dupes.add(key)
        else:
            fullname_country_to_id[key] = row[0]
    for k in dupes:
        fullname_country_to_id.pop(k, None)

    return linkedin_to_id, email_to_id, domain_name_to_id, fullname_country_to_id


def match_lead(lead, markers, linkedin_to_id, email_to_id, domain_name_to_id, fullname_country_to_id):
    """Match a GetSales lead to a DB contact. Returns (contact_id, method) or (None, None)."""
    # LinkedIn
    linkedin_url = to_str(lead.get("linkedin"))
    if linkedin_url:
        norm = normalize_linkedin(linkedin_url)
        if norm and norm in linkedin_to_id:
            return linkedin_to_id[norm], "linkedin"

    # Email
    email = to_str(lead.get("work_email"))
    if email:
        if email.lower() in email_to_id:
            return email_to_id[email.lower()], "email"

    # Domain + last name (split name from API)
    company_name = to_str(lead.get("company_name"))
    name = to_str(lead.get("name")) or ""
    parts = name.split()
    last_name = parts[-1] if len(parts) > 1 else None
    first_name = parts[0] if parts else None

    # We don't have domain from API directly — skip domain+name for API sync
    # (import_getsales.py has it from CSV, API doesn't expose company_domain)

    # Full name + country
    country = to_str(lead.get("raw_address"))
    if first_name and last_name and country:
        # raw_address might be "Paris, France" — try extracting country
        country_part = country.split(",")[-1].strip().lower()
        key = f"{first_name.lower()} {last_name.lower()}|{country_part}"
        if key in fullname_country_to_id:
            return fullname_country_to_id[key], "name+country"

    return None, None


def main():
    parser = argparse.ArgumentParser(description="Sync GetSales API → Neon DB")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true", help="Sync all lists, not just direct")
    args = parser.parse_args()

    token = os.environ.get("GETSALES_API_KEY")
    if not token:
        print("ERROR: GETSALES_API_KEY not found in .env")
        return

    print("Fetching leads from GetSales API...")
    all_items = fetch_all_leads(token)
    print(f"  Fetched {len(all_items)} total leads")

    # Filter by list
    if not args.all:
        items = [i for i in all_items if i["lead"].get("list_uuid") == DIRECT_UUID]
        print(f"  Filtered to {len(items)} direct brand leads")
    else:
        items = all_items
        print(f"  Processing all {len(items)} leads")

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    print("Building contact indexes...")
    linkedin_to_id, email_to_id, domain_name_to_id, fullname_country_to_id = build_contact_indexes(cur)

    stats = {
        "total": 0,
        "matched_linkedin": 0,
        "matched_email": 0,
        "matched_name_country": 0,
        "unmatched": 0,
        "updated": 0,
        "skipped_no_change": 0,
        "errors": 0,
    }

    for item in items:
        lead = item["lead"]
        markers = item.get("markers", [])
        stats["total"] += 1

        contact_id, method = match_lead(
            lead, markers, linkedin_to_id, email_to_id, domain_name_to_id, fullname_country_to_id
        )

        if contact_id is None:
            stats["unmatched"] += 1
            name = to_str(lead.get("name")) or "Unknown"
            if stats["unmatched"] <= 10:
                print(f"  [UNMATCHED] {name} — {to_str(lead.get('linkedin')) or to_str(lead.get('work_email')) or 'no id'}")
            continue

        if method == "linkedin":
            stats["matched_linkedin"] += 1
        elif method == "email":
            stats["matched_email"] += 1
        else:
            stats["matched_name_country"] += 1

        # Derive pipeline stage from markers
        derived_stage = derive_pipeline_stage(markers)

        # Collect fields to update
        getsales_id = to_str(lead.get("id"))
        about = to_str(lead.get("about"))
        linkedin_id = to_str(lead.get("linkedin_id"))
        work_phone = to_str(lead.get("work_phone"))
        mobile_phone = to_str(lead.get("mobile_phone"))

        sets = []
        vals = []

        # pipeline_stage: always update (not COALESCE) — want latest from GS
        if derived_stage:
            sets.append("pipeline_stage = %s")
            vals.append(derived_stage)

        # Other fields: only fill NULLs
        null_fields = [
            ("getsales_id", getsales_id),
            ("about", about),
            ("linkedin_id", linkedin_id),
            ("work_phone", work_phone),
            ("mobile_phone", mobile_phone),
        ]
        for col, val in null_fields:
            if val:
                sets.append(f"{col} = COALESCE({col}, %s)")
                vals.append(val)

        if not sets:
            stats["skipped_no_change"] += 1
            continue

        sets.append("updated_at = NOW()")
        vals.append(contact_id)

        sql = f"UPDATE contacts SET {', '.join(sets)} WHERE id = %s"

        try:
            if not args.dry_run:
                cur.execute(sql, vals)
            stats["updated"] += 1
            name = to_str(lead.get("name")) or "Unknown"
            if stats["total"] <= 20:
                print(f"  {name} → {method}, stage={derived_stage}")
        except Exception as e:
            stats["errors"] += 1
            print(f"  [ERROR] {to_str(lead.get('name'))}: {e}")
            conn.rollback()

    if not args.dry_run:
        conn.commit()

    cur.close()
    conn.close()

    print(f"\n{'=' * 50}")
    print(f"Total leads      : {stats['total']}")
    print(f"Matched LinkedIn : {stats['matched_linkedin']}")
    print(f"Matched email    : {stats['matched_email']}")
    print(f"Matched name+co  : {stats['matched_name_country']}")
    print(f"Unmatched        : {stats['unmatched']}")
    print(f"Updated          : {stats['updated']}")
    print(f"No change        : {stats['skipped_no_change']}")
    print(f"Errors           : {stats['errors']}")
    print(f"{'=' * 50}")
    if args.dry_run:
        print("[DRY RUN] No data written to DB.")


if __name__ == "__main__":
    main()
