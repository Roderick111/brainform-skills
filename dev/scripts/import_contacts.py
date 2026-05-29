#!/usr/bin/env python3
"""
Import contacts from Apollo CSV → Neon DB.
Matches contacts to companies by domain (via normalize_domain) or org_id.
Usage: uv run dev/scripts/import_contacts.py <csv_path>
"""

import csv
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DB_URL = os.environ["DATABASE_URL"]

# Apollo CSV columns we expect
REQUIRED_COLUMNS = [
    "First Name",
    "Last Name",
    "Title",
    "Email",
    "Apollo Contact Id",
]


def to_str(val: str) -> str | None:
    v = val.strip() if val else ""
    return v if v else None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Import contacts from Apollo CSV")
    parser.add_argument("csv_path", help="Path to Apollo CSV file")
    parser.add_argument(
        "--company-id",
        type=int,
        default=None,
        help="Force all contacts to this company_id (skip domain/org matching)",
    )
    args = parser.parse_args()

    csv_path = args.csv_path
    forced_company_id = args.company_id

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    total = 0
    matched = 0
    unmatched = 0
    errors = 0
    unmatched_list = []

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        # Validate columns
        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            print(f"ERROR: Missing required columns: {missing}")
            print(f"Found columns: {reader.fieldnames}")
            sys.exit(1)

        for row in reader:
            total += 1

            contact_id = to_str(row.get("Apollo Contact Id"))
            if not contact_id:
                print(f"  [SKIP] row {total} — no Apollo Contact Id")
                errors += 1
                continue

            first_name = to_str(row.get("First Name"))
            last_name = to_str(row.get("Last Name"))
            title = to_str(row.get("Title"))
            email = to_str(row.get("Email"))
            secondary_email = to_str(row.get("Secondary Email"))
            work_phone = to_str(row.get("Work Direct Phone"))
            mobile_phone = to_str(row.get("Mobile Phone"))
            corporate_phone = to_str(row.get("Corporate Phone"))
            linkedin = to_str(row.get("Person Linkedin Url"))
            website = to_str(row.get("Website"))
            country = to_str(row.get("Country"))
            org_id = to_str(row.get("Apollo Account Id"))

            # Match to company
            if forced_company_id:
                company_id = forced_company_id
            else:
                company_id = None

                if website:
                    cur.execute(
                        "SELECT id FROM companies WHERE domain = normalize_domain(%s) LIMIT 1",
                        (website,),
                    )
                    result = cur.fetchone()
                    if result:
                        company_id = result[0]

                if company_id is None and org_id:
                    cur.execute(
                        "SELECT id FROM companies WHERE org_id = %s LIMIT 1",
                        (org_id,),
                    )
                    result = cur.fetchone()
                    if result:
                        company_id = result[0]

                if company_id is None:
                    unmatched += 1
                    name = f"{first_name or ''} {last_name or ''}".strip()
                    unmatched_list.append(f"{name} ({website or 'no domain'})")
                    print(f"  [UNMATCHED] row {total}: {name} — {website or 'no domain'}")
                    continue

            # Normalize corporate phone for company record
            normalized_phone = None
            if corporate_phone:
                cur.execute("SELECT normalize_phone(%s, %s)", (corporate_phone, country))
                normalized_phone = cur.fetchone()[0]

            # Upsert contact
            try:
                cur.execute(
                    """
                    INSERT INTO contacts (
                        id, company_id, org_id,
                        first_name, last_name, title,
                        email, secondary_email, linkedin,
                        work_phone, mobile_phone, corporate_phone,
                        is_empty, enrichment_status
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        company_id        = COALESCE(EXCLUDED.company_id, contacts.company_id),
                        org_id            = COALESCE(EXCLUDED.org_id, contacts.org_id),
                        first_name        = COALESCE(EXCLUDED.first_name, contacts.first_name),
                        last_name         = COALESCE(EXCLUDED.last_name, contacts.last_name),
                        title             = COALESCE(EXCLUDED.title, contacts.title),
                        email             = COALESCE(EXCLUDED.email, contacts.email),
                        secondary_email   = COALESCE(EXCLUDED.secondary_email, contacts.secondary_email),
                        linkedin          = COALESCE(EXCLUDED.linkedin, contacts.linkedin),
                        work_phone        = COALESCE(EXCLUDED.work_phone, contacts.work_phone),
                        mobile_phone      = COALESCE(EXCLUDED.mobile_phone, contacts.mobile_phone),
                        corporate_phone   = COALESCE(EXCLUDED.corporate_phone, contacts.corporate_phone),
                        enrichment_status = CASE
                            WHEN EXCLUDED.email IS NOT NULL THEN 'email_found'
                            ELSE contacts.enrichment_status
                        END,
                        updated_at        = NOW()
                    """,
                    (
                        contact_id,
                        company_id,
                        org_id,
                        first_name,
                        last_name,
                        title,
                        email,
                        secondary_email,
                        linkedin,
                        work_phone,
                        mobile_phone,
                        corporate_phone,
                        email is None,  # is_empty
                        "email_found" if email else "not_found",
                    ),
                )

                # Update phone on company if we have a normalized one and company has none
                if normalized_phone:
                    cur.execute(
                        "UPDATE companies SET phone = %s WHERE id = %s AND phone IS NULL",
                        (normalized_phone, company_id),
                    )

                matched += 1
                name = f"{first_name or ''} {last_name or ''}".strip()
                print(f"  row {total}: {name} → company_id={company_id}")

            except Exception as e:
                conn.rollback()
                errors += 1
                print(f"  [ERROR] row {total} — {e}")
                continue

            if total % 100 == 0:
                conn.commit()
                print(f"  --- committed batch ({total} rows so far) ---")

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n{'='*50}")
    print(f"Total rows  : {total}")
    print(f"Matched     : {matched}")
    print(f"Unmatched   : {unmatched}")
    print(f"Errors      : {errors}")
    print(f"{'='*50}")

    if unmatched_list:
        print(f"\nUnmatched contacts:")
        for u in unmatched_list:
            print(f"  - {u}")


if __name__ == "__main__":
    main()
