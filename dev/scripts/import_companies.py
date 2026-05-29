#!/usr/bin/env python3
"""
Import companies from Apollo CSV → Neon DB via upsert_company().
Usage: uv run dev/scripts/import_companies.py <csv_path>
"""

import argparse
import csv
import os
import sys
import re
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DB_URL = os.environ["DATABASE_URL"]


def to_array(val: str) -> list[str] | None:
    if not val or not val.strip():
        return None
    return [x.strip() for x in val.split(",") if x.strip()]


def to_int(val: str) -> int | None:
    if not val or not val.strip():
        return None
    cleaned = re.sub(r"[^\d]", "", val)
    return int(cleaned) if cleaned else None


def to_bigint(val: str) -> int | None:
    """Parse currency strings like '$183,000,000' or '183000000'."""
    if not val or not val.strip():
        return None
    cleaned = re.sub(r"[^\d]", "", val)
    return int(cleaned) if cleaned else None


def to_date(val: str) -> str | None:
    if not val or not val.strip():
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(val.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def to_str(val: str) -> str | None:
    v = val.strip() if val else ""
    return v if v else None


def main():
    parser = argparse.ArgumentParser(description="Import companies from Apollo CSV")
    parser.add_argument("csv_path", help="Path to Apollo CSV file")
    parser.add_argument(
        "--segment",
        type=str,
        default=None,
        help="Pre-tag all imported companies with this segment (e.g. 'agency')",
    )
    args = parser.parse_args()

    csv_path = args.csv_path
    segment = [args.segment] if args.segment else None

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    BATCH_SIZE = 100

    inserted = 0
    updated = 0
    errors = 0
    total = 0
    batch_start_log_id = None

    # Record log cursor before import
    cur.execute("SELECT COALESCE(MAX(id), 0) FROM upsert_log")
    log_id_before = cur.fetchone()[0]

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            name = to_str(row.get("Company Name", ""))
            if not name:
                print(f"  [SKIP] row {total} — no company name")
                continue

            try:
                cur.execute("""
                    SELECT upsert_company(
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    ) AS id
                """, (
                    name,
                    to_str(row.get("Website")),
                    to_str(row.get("Apollo Account Id")),
                    to_str(row.get("Industry")),
                    to_str(row.get("Company Country")),
                    to_str(row.get("Company City")),
                    to_int(row.get("# Employees")),
                    to_str(row.get("Company Linkedin Url")),
                    to_int(row.get("Founded Year")),
                    None,                                           # p_research
                    to_str(row.get("Tier")),
                    to_str(row.get("Company State")),
                    to_str(row.get("Company Phone")),
                    to_str(row.get("Short Description")),
                    to_array(row.get("Keywords")),
                    to_array(row.get("Technologies")),
                    to_array(row.get("SIC Codes")),
                    to_array(row.get("NAICS Codes")),
                    to_bigint(row.get("Annual Revenue")),
                    to_bigint(row.get("Total Funding")),
                    to_str(row.get("Latest Funding")),
                    to_bigint(row.get("Latest Funding Amount")),
                    to_date(row.get("Last Raised At")),
                    to_int(row.get("Number of Retail Locations")),
                    to_str(row.get("Subsidiary of")),
                    to_str(row.get("Subsidiary of (Organization ID)")),
                    segment,
                ))
                print(f"  row {total}: {name}")

            except Exception as e:
                conn.rollback()
                errors += 1
                print(f"  [ERROR] {name} — {e}")
                continue

            # Commit every BATCH_SIZE rows
            if total % BATCH_SIZE == 0:
                conn.commit()
                print(f"  --- committed batch ({total} rows so far) ---")

    # Final commit for remainder
    conn.commit()

    # Summary from upsert_log (single query at the end)
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE was_insert = TRUE)  as inserted,
            COUNT(*) FILTER (WHERE was_insert = FALSE) as updated
        FROM upsert_log
        WHERE id > %s
    """, (log_id_before,))
    row = cur.fetchone()
    inserted, updated = row[0], row[1]

    cur.close()
    conn.close()

    print(f"\n{'='*50}")
    print(f"Total rows : {total}")
    print(f"Inserted   : {inserted}")
    print(f"Updated    : {updated}")
    print(f"Errors     : {errors}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
