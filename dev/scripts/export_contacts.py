#!/usr/bin/env python3
"""
Export contacts to GetSales-ready CSV.
Usage:
  uv run dev/scripts/export_contacts.py --segment agency --limit 500
  uv run dev/scripts/export_contacts.py --segment ecom-product --status verified
  uv run dev/scripts/export_contacts.py --all
"""

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DB_URL = os.environ["DATABASE_URL"]

DOWNLOADS = Path.home() / "Downloads"


def fetch_contacts(segment: str | None, status: str | None, limit: int | None, today: bool = False) -> list[dict]:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    where = ["1=1"]
    params = []

    if segment:
        where.append("%s = ANY(comp.segment)")
        params.append(segment)

    if status:
        where.append("c.enrichment_status = %s")
        params.append(status)

    if today:
        where.append("c.created_at >= CURRENT_DATE")

    where_clause = " AND ".join(where)
    limit_clause = f"LIMIT {int(limit)}" if limit else ""

    cur.execute(
        f"""
        SELECT
            c.first_name,
            c.last_name,
            c.title,
            c.email,
            c.secondary_email,
            c.work_phone,
            c.mobile_phone,
            c.corporate_phone,
            c.linkedin,
            c.enrichment_status,
            comp.name AS company_name,
            comp.domain,
            comp.country,
            comp.segment,
            comp.product_category,
            comp.phone AS company_phone
        FROM contacts c
        JOIN companies comp ON comp.id = c.company_id
        WHERE {where_clause}
        ORDER BY comp.name, c.last_name
        {limit_clause}
        """,
        params,
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def main():
    parser = argparse.ArgumentParser(description="Export contacts to CSV")
    parser.add_argument("--segment", help="Filter by segment (e.g. agency, ecom-product)")
    parser.add_argument("--status", help="Filter by enrichment_status (e.g. verified, catch_all)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--all", action="store_true", help="Export all contacts")
    parser.add_argument("--today", action="store_true", help="Only contacts created today")
    parser.add_argument("--output", help="Output file path (default: ~/Downloads/)")
    args = parser.parse_args()

    if not args.all and not args.segment and not args.status:
        print("Specify --segment, --status, or --all")
        sys.exit(1)

    rows = fetch_contacts(args.segment, args.status, args.limit, args.today)
    if not rows:
        print("No contacts found.")
        return

    segment_tag = args.segment or "all"
    status_tag = f"_{args.status}" if args.status else ""
    date_tag = datetime.now().strftime("%Y%m%d")
    filename = f"contacts_{segment_tag}{status_tag}_{date_tag}.csv"

    output_path = Path(args.output) if args.output else DOWNLOADS / filename

    fieldnames = [
        "first_name", "last_name", "title", "email", "secondary_email",
        "work_phone", "mobile_phone", "corporate_phone", "linkedin",
        "enrichment_status", "company_name", "domain", "country",
        "segment", "product_category", "company_phone",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            seg = row.get("segment") or []
            row["segment"] = ", ".join(seg) if isinstance(seg, list) else seg
            writer.writerow(row)

    print(f"Exported {len(rows)} contacts → {output_path}")

    # Summary
    statuses = {}
    for r in rows:
        s = r["enrichment_status"] or "unknown"
        statuses[s] = statuses.get(s, 0) + 1
    print(f"\nBy status:")
    for s, count in sorted(statuses.items(), key=lambda x: -x[1]):
        print(f"  {s}: {count}")


if __name__ == "__main__":
    main()
