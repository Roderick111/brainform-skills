#!/usr/bin/env python3
"""
Import GetSales export → update existing contacts in Neon DB.
Matches by LinkedIn URL (normalized), then email fallback.
Never overwrites existing values — only fills NULLs.

Usage:
  uv run dev/scripts/import_getsales.py <csv_path>
  uv run dev/scripts/import_getsales.py <csv_path> --dry-run
"""

import argparse
import csv
import os
import re
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DB_URL = os.environ["DATABASE_URL"]


def to_str(val: str) -> str | None:
    v = val.strip() if val else ""
    return v if v else None


def normalize_linkedin(url: str | None) -> str | None:
    """Extract normalized LinkedIn path: /in/username or /company/name"""
    if not url:
        return None
    url = url.strip().rstrip("/").lower()
    # Remove query params and fragments
    url = re.sub(r"[?#].*$", "", url)
    # Extract /in/username
    m = re.search(r"linkedin\.com(/in/[a-z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None


def main():
    parser = argparse.ArgumentParser(description="Import GetSales export into contacts")
    parser.add_argument("csv_path", help="Path to GetSales CSV export")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # Pre-load contact lookup indexes
    # LinkedIn → contact id
    cur.execute("SELECT id, linkedin FROM contacts WHERE linkedin IS NOT NULL")
    linkedin_to_id = {}
    for row in cur.fetchall():
        norm = normalize_linkedin(row[1])
        if norm:
            linkedin_to_id[norm] = row[0]

    # Email → contact id
    cur.execute("SELECT id, LOWER(email) FROM contacts WHERE email IS NOT NULL")
    email_to_id = {row[1]: row[0] for row in cur.fetchall()}

    # Domain + last_name → contact id
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

    # Full name + country → contact id (only store if unique)
    cur.execute("""
        SELECT c.id, LOWER(CONCAT(c.first_name, ' ', c.last_name)), LOWER(comp.country)
        FROM contacts c
        JOIN companies comp ON comp.id = c.company_id
        WHERE c.first_name IS NOT NULL AND c.last_name IS NOT NULL AND comp.country IS NOT NULL
    """)
    fullname_country_to_id = {}
    fullname_country_dupes = set()
    for row in cur.fetchall():
        key = f"{row[1]}|{row[2]}"
        if key in fullname_country_to_id:
            fullname_country_dupes.add(key)
        else:
            fullname_country_to_id[key] = row[0]
    # Remove ambiguous matches
    for k in fullname_country_dupes:
        fullname_country_to_id.pop(k, None)

    total = 0
    matched_linkedin = 0
    matched_email = 0
    matched_domain_name = 0
    matched_fullname_country = 0
    unmatched = 0
    updated = 0
    skipped_no_update = 0
    errors = 0

    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            total += 1

            gs_linkedin_url = to_str(row.get("LinkedIn URL"))
            gs_email = to_str(row.get("Work Email"))

            # Match: LinkedIn first, email fallback
            contact_id = None
            match_method = None

            if gs_linkedin_url:
                norm = normalize_linkedin(gs_linkedin_url)
                if norm and norm in linkedin_to_id:
                    contact_id = linkedin_to_id[norm]
                    match_method = "linkedin"

            if contact_id is None and gs_email:
                email_lower = gs_email.lower()
                if email_lower in email_to_id:
                    contact_id = email_to_id[email_lower]
                    match_method = "email"

            if contact_id is None:
                gs_domain = to_str(row.get("Company Domain"))
                gs_last = to_str(row.get("Last Name"))
                if gs_domain and gs_last:
                    key = f"{gs_domain.lower().strip()}|{gs_last.lower().strip()}"
                    if key in domain_name_to_id:
                        contact_id = domain_name_to_id[key]
                        match_method = "domain+name"

            if contact_id is None:
                gs_first = to_str(row.get("First Name"))
                gs_last2 = to_str(row.get("Last Name"))
                gs_country = to_str(row.get("Location Country"))
                if gs_first and gs_last2 and gs_country:
                    key = f"{gs_first.lower().strip()} {gs_last2.lower().strip()}|{gs_country.lower().strip()}"
                    if key in fullname_country_to_id:
                        contact_id = fullname_country_to_id[key]
                        match_method = "name+country"

            if contact_id is None:
                unmatched += 1
                name = to_str(row.get("Full Name")) or "Unknown"
                if total <= 20 or unmatched <= 10:
                    print(f"  [UNMATCHED] {name} — {gs_linkedin_url or gs_email or 'no identifier'}")
                continue

            if match_method == "linkedin":
                matched_linkedin += 1
            elif match_method == "email":
                matched_email += 1
            elif match_method == "domain+name":
                matched_domain_name += 1
            else:
                matched_fullname_country += 1

            # Collect updates — only fill NULLs
            getsales_id = to_str(row.get("System UUID"))
            pipeline_stage = to_str(row.get("Pipeline Stage"))
            about = to_str(row.get("About"))
            linkedin_id = to_str(row.get("LinkedIn ID"))
            work_phone = to_str(row.get("Work Phone Number"))
            mobile_phone = to_str(row.get("Personal Phone Number"))
            secondary_email = to_str(row.get("Personal Email"))

            # Build SET clause: only update NULL columns
            sets = []
            vals = []

            fields = [
                ("getsales_id", getsales_id),
                ("pipeline_stage", pipeline_stage),
                ("about", about),
                ("linkedin_id", linkedin_id),
                ("work_phone", work_phone),
                ("mobile_phone", mobile_phone),
                ("secondary_email", secondary_email),
            ]

            for col, val in fields:
                if val:
                    sets.append(f"{col} = COALESCE({col}, %s)")
                    vals.append(val)

            if not sets:
                skipped_no_update += 1
                continue

            sets.append("updated_at = NOW()")
            vals.append(contact_id)

            sql = f"UPDATE contacts SET {', '.join(sets)} WHERE id = %s"

            try:
                if not args.dry_run:
                    cur.execute(sql, vals)
                updated += 1
                name = to_str(row.get("Full Name")) or "Unknown"
                if total <= 20:
                    print(f"  {name} → {match_method} match, {len(sets)-1} fields")
            except Exception as e:
                errors += 1
                print(f"  [ERROR] {to_str(row.get('Full Name'))}: {e}")
                conn.rollback()
                continue

            if total % 500 == 0:
                if not args.dry_run:
                    conn.commit()
                print(f"  --- committed ({total} rows processed) ---")

    if not args.dry_run:
        conn.commit()

    cur.close()
    conn.close()

    print(f"\n{'=' * 50}")
    print(f"Total rows       : {total}")
    print(f"Matched LinkedIn : {matched_linkedin}")
    print(f"Matched email    : {matched_email}")
    print(f"Matched dom+name : {matched_domain_name}")
    print(f"Matched name+co  : {matched_fullname_country}")
    print(f"Unmatched        : {unmatched}")
    print(f"Updated          : {updated}")
    print(f"No new data      : {skipped_no_update}")
    print(f"Errors           : {errors}")
    print(f"{'=' * 50}")
    if args.dry_run:
        print("[DRY RUN] No data written to DB.")


if __name__ == "__main__":
    main()
