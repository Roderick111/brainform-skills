#!/usr/bin/env python3
"""
Email verification via MillionVerifier Single API.
Only processes contacts from target segments (ecom-agency + ecom brands).

Usage:
  uv run dev/scripts/verify_emails_mv.py verify --limit 100
  uv run dev/scripts/verify_emails_mv.py verify --limit 100 --dry-run
  uv run dev/scripts/verify_emails_mv.py credits
"""

import argparse
import asyncio
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from httpx import AsyncClient

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DB_URL = os.environ["DATABASE_URL"]

API_KEY = os.environ["MILLION_VERIFIER_API_KEY"]
API_BASE = "https://api.millionverifier.com/api/v3/"

CONCURRENCY = 20
BATCH_SIZE = 50

# Target segments: ecom agencies + direct ecom brands
TARGET_SEGMENTS = [
    "ecom-agency",
    "ecom-product",
    "beauty-skincare",
    "fashion-apparel",
    "consumer-electronics",
    "health-nutrition",
    "sporting-goods",
    "home-appliances",
    "cycling-fitness",
    "outdoor-tools",
    "baby-kids",
    "food-beverage",
    "pet-care",
]

# MV result → our enrichment_status
STATUS_MAP = {
    "ok": "verified",
    "catch_all": "catch_all",
    "invalid": "risky",
    "unknown": "risky",
    "disposable": "risky",
}


def get_conn():
    return psycopg2.connect(DB_URL)


# ── Credits ─────────────────────────────────────────────────


def cmd_credits():
    import requests

    resp = requests.get(f"{API_BASE}/credits", params={"api": API_KEY})
    data = resp.json()
    print(f"Single credits : {data['credits']}")
    print(f"Bulk credits   : {data['bulk_credits']}")
    print(f"Renewing       : {data['renewing_credits']}")
    print(f"Plan           : {data['plan']}")


# ── Fetch ───────────────────────────────────────────────────


def fetch_contacts(limit: int) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.email
        FROM contacts c
        JOIN companies comp ON comp.id = c.company_id
        WHERE c.enrichment_status = 'email_found'
          AND c.email IS NOT NULL
          AND comp.segment && %s
        ORDER BY c.id
        LIMIT %s
        """,
        (TARGET_SEGMENTS, limit),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def fetch_count() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*)
        FROM contacts c
        JOIN companies comp ON comp.id = c.company_id
        WHERE c.enrichment_status = 'email_found'
          AND c.email IS NOT NULL
          AND comp.segment && %s
        """,
        (TARGET_SEGMENTS,),
    )
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


def batch_update(updates: list[tuple[str, str]]) -> int:
    if not updates:
        return 0
    conn = get_conn()
    cur = conn.cursor()
    for contact_id, status in updates:
        cur.execute(
            "UPDATE contacts SET enrichment_status = %s, updated_at = NOW() WHERE id = %s",
            (status, contact_id),
        )
    conn.commit()
    cur.close()
    conn.close()
    return len(updates)


# ── Verify ──────────────────────────────────────────────────


async def verify_one(
    client: AsyncClient, sem: asyncio.Semaphore, contact: dict
) -> tuple[str, str]:
    """Returns (contact_id, new_status)"""
    async with sem:
        try:
            resp = await client.get(
                API_BASE,
                params={
                    "api": API_KEY,
                    "email": contact["email"],
                    "timeout": 15,
                },
            )
            data = resp.json()

            if data.get("error"):
                err = data["error"]
                if "insufficient_credits" in err:
                    print(f"  [STOP] Out of credits!")
                    return contact["id"], "error_credits"
                print(f"  [ERROR] {contact['email']}: {err}")
                return contact["id"], "error"

            result = data.get("result", "").lower()
            new_status = STATUS_MAP.get(result, "risky")
            quality = data.get("quality", "")
            print(f"  {contact['email']} → {new_status} (result={result}, quality={quality})")
            return contact["id"], new_status

        except Exception as e:
            print(f"  [ERROR] {contact['email']}: {e}")
            return contact["id"], "error"


async def cmd_verify(limit: int, dry_run: bool):
    total_available = fetch_count()
    rows = fetch_contacts(limit)

    if not rows:
        print("No contacts to verify in target segments.")
        return

    print(f"Target contacts available: {total_available}")
    print(f"Verifying {len(rows)} contacts from target segments...")

    sem = asyncio.Semaphore(CONCURRENCY)

    stats = {"verified": 0, "catch_all": 0, "risky": 0, "errors": 0}

    async with AsyncClient(timeout=30) as client:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(rows) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} contacts)...")

            tasks = [verify_one(client, sem, c) for c in batch]
            results = await asyncio.gather(*tasks)

            credit_error = any(s == "error_credits" for _, s in results)

            updates = []
            for contact_id, status in results:
                if status in STATUS_MAP.values():
                    stats[status] = stats.get(status, 0) + 1
                    updates.append((contact_id, status))
                elif status.startswith("error"):
                    stats["errors"] += 1

            if not dry_run and updates:
                written = batch_update(updates)
                print(f"  Written {written} to DB")

            if credit_error:
                print("\n[STOPPED] Out of credits. Partial results saved.")
                break

    print(f"\n{'=' * 40}")
    print(f"Total      : {len(rows)}")
    print(f"Verified   : {stats['verified']}")
    print(f"Catch-all  : {stats['catch_all']}")
    print(f"Risky      : {stats['risky']}")
    print(f"Errors     : {stats['errors']}")
    print(f"{'=' * 40}")
    if dry_run:
        print("[DRY RUN] No data written to DB.")


# ── Main ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="MillionVerifier email verification")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("credits", help="Check API credits")

    p_verify = sub.add_parser("verify", help="Verify emails from target segments")
    p_verify.add_argument("--limit", type=int, default=100)
    p_verify.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    if args.cmd == "credits":
        cmd_credits()
    elif args.cmd == "verify":
        asyncio.run(cmd_verify(args.limit, args.dry_run))


if __name__ == "__main__":
    main()
