#!/usr/bin/env python3
"""
LLM segmentation: classify agencies by type + platforms.
Usage: uv run dev/scripts/segment_agencies.py --limit 50
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from typing import Literal

import instructor
import psycopg2
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator

DB_URL = os.environ["DATABASE_URL"]

MODEL = "google/gemma-4-31b-it"

AGENCY_TYPES = Literal[
    "ecom-agency",
    "marketing-agency",
    "dev-shop",
    "bpo-outsourcing",
    "not-agency",
    "other",
]

PLATFORMS = Literal[
    "shopify",
    "magento",
    "bigcommerce",
    "sfcc",
    "woocommerce",
    "prestashop",
    "shopware",
]


class AgencySegment(BaseModel):
    agency_type: AGENCY_TYPES = Field(
        description="Primary business model of the agency",
    )
    platforms: list[PLATFORMS] = Field(
        default_factory=list,
        max_length=3,
        description="eCommerce platforms the agency works with, only for ecom-agency",
    )

    @model_validator(mode="after")
    def platforms_only_for_ecom(self) -> "AgencySegment":
        if self.agency_type != "ecom-agency" and self.platforms:
            raise ValueError(
                "platforms must be empty when agency_type is not ecom-agency"
            )
        return self


SYSTEM_PROMPT = """# Role
You are an agency classifier for a B2B SaaS that sells AI commerce tools to online retailers.
Your task: given an agency profile, classify it by agency type and eCommerce platforms.

# Agency types (pick exactly one)

- ecom-agency: agency whose core business is building, managing, or optimizing online stores for clients. Must have eCommerce implementation as a primary service — not just "we also do ecom". Includes: Shopify/Magento/BigCommerce agencies, eCommerce consultancies, conversion optimization agencies focused on online stores, full-service digital agencies where eCommerce is the clear primary revenue driver.
- marketing-agency: digital marketing agency (SEO, PPC, social media, email marketing, content) that may touch eCommerce but does NOT build or manage online stores as a core service. The agency sells marketing services, not store builds.
- dev-shop: generic software development company, web development studio, or IT consultancy with no specific eCommerce focus. Builds websites, apps, custom software — eCommerce is just one of many things they could do, not a specialty.
- bpo-outsourcing: business process outsourcing, offshore staffing, data entry, call centers, IT body shops. Sells labor, not expertise.
- not-agency: not an agency at all — actually a SaaS product, hardware company, manufacturer, retailer, or other non-agency business that was miscategorized in the source data.
- other: does not fit any of the above, or insufficient information to classify.

# Platforms (pick 0-3, only if agency_type is ecom-agency)
- shopify: includes Shopify, Shopify Plus, Shopify Partner
- magento: includes Magento, Adobe Commerce
- bigcommerce
- sfcc: Salesforce Commerce Cloud
- woocommerce
- prestashop
- shopware

# Decision rules

1. Description > keywords > industry field. The industry field is often wrong.
2. If the agency lists eCommerce platforms (Shopify, Magento, etc.) as core services in the description, it is ecom-agency.
3. If the agency only mentions "ecommerce" in keywords but the description is about generic marketing/SEO/social for all industries — it is marketing-agency. BUT if the agency's marketing services are exclusively or primarily for eCommerce/online store clients, classify as ecom-agency.
4. A company that builds its OWN software product (SaaS) is not-agency, even if it serves eCommerce clients.
5. An agency that does "everything" (web, mobile, IoT, games, ecommerce) with no ecom specialization = dev-shop.
6. Offshore dev companies that sell developer hours, not eCommerce expertise = bpo-outsourcing.
7. If the description is in a foreign language, still classify based on the content.

# Output
ONLY valid JSON. No reasoning, no explanations."""

MAX_KEYWORDS = 15
MAX_RETRIES = 4
RETRY_DELAY = 3
CONCURRENCY = 50
BATCH_SIZE = 50
BATCH_DELAY = 3


def emit(data: dict, json_output: bool) -> None:
    if json_output:
        print(json.dumps(data), flush=True)


def fetch_unclassified(limit: int) -> list[dict]:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, short_description, keywords, industry
        FROM companies
        WHERE segment = ARRAY['agency']
        LIMIT %s
        """,
        (limit,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def fetch_unclassified_count() -> int:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM companies WHERE segment = ARRAY['agency']")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count


def build_user_prompt(row: dict) -> str:
    name = row["name"] or "Unknown"
    desc = row["short_description"] or "No description"
    industry = row["industry"] or "Unknown"
    keywords = row.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",")]
    keywords = keywords[:MAX_KEYWORDS]
    kw_str = ", ".join(keywords) if keywords else "None"
    return (
        f'Company: "{name}" | Industry: "{industry}"\n'
        f'Description: "{desc}"\n'
        f"Keywords: {kw_str}"
    )


def has_enough_data(row: dict) -> bool:
    return bool(row.get("short_description") or row.get("keywords"))


async def classify_one(
    client: instructor.AsyncInstructor,
    row: dict,
    sem: asyncio.Semaphore,
    json_output: bool,
) -> tuple[int, str, AgencySegment | None, str | None]:
    name = row["name"] or "Unknown"

    if not has_enough_data(row):
        emit(
            {"event": "skipped", "name": name, "reason": "no description or keywords"},
            json_output,
        )
        return row["id"], name, None, None

    user_prompt = build_user_prompt(row)

    async with sem:
        for attempt in range(MAX_RETRIES):
            try:
                result = await client.chat.completions.create(
                    model=MODEL,
                    max_tokens=128,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_model=AgencySegment,
                    max_retries=2,
                )
                segment_list = ["agency", result.agency_type, *result.platforms]
                emit(
                    {"event": "classified", "name": name, "segment": segment_list},
                    json_output,
                )
                if not json_output:
                    print(f"  {name} → {', '.join(segment_list)}")
                return row["id"], name, result, None
            except Exception as e:
                err_msg = str(e)
                is_transient = "502" in err_msg or "503" in err_msg or "429" in err_msg
                if is_transient and attempt < MAX_RETRIES - 1:
                    if not json_output:
                        print(f"  [RETRY] {name}: {RETRY_DELAY}s (attempt {attempt + 1})")
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                emit(
                    {"event": "error", "name": name, "message": err_msg},
                    json_output,
                )
                if not json_output:
                    print(f"  [ERROR] {name}: {e}")
                return row["id"], name, None, err_msg


def write_segments(results: list[tuple[int, AgencySegment]]) -> int:
    if not results:
        return 0
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    written = 0
    for company_id, seg in results:
        segment_array = ["agency", seg.agency_type, *seg.platforms]
        cur.execute(
            "UPDATE companies SET segment = %s WHERE id = %s",
            (segment_array, company_id),
        )
        written += 1
    conn.commit()
    cur.close()
    conn.close()
    return written


async def main() -> None:
    parser = argparse.ArgumentParser(description="Segment agencies via LLM")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Emit JSONL events to stdout (for app integration)",
    )
    parser.add_argument(
        "--count-only",
        action="store_true",
        help="Print unclassified count as JSON and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify but don't write to DB",
    )
    args = parser.parse_args()

    if args.count_only:
        count = fetch_unclassified_count()
        print(json.dumps({"count": count}), flush=True)
        return

    json_out = args.json_output

    rows = fetch_unclassified(args.limit)
    if not rows:
        if json_out:
            emit({"event": "done", "classified": 0, "skipped": 0, "errors": 0}, True)
        else:
            print("No unclassified agencies found.")
        return

    total = len(rows)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    emit({"event": "start", "total": total, "model": MODEL}, json_out)
    if not json_out:
        print(f"Fetched {total} unclassified agencies. Model: {MODEL}")

    openai_client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    client = instructor.from_openai(openai_client)
    sem = asyncio.Semaphore(CONCURRENCY)

    total_classified = 0
    total_skipped = 0
    total_errors = 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1

        emit(
            {
                "event": "batch_start",
                "batch": batch_num,
                "total_batches": total_batches,
                "size": len(batch),
            },
            json_out,
        )
        if not json_out:
            print(f"Batch {batch_num}/{total_batches} ({len(batch)} rows)...")

        tasks = [classify_one(client, row, sem, json_out) for row in batch]
        batch_results = await asyncio.gather(*tasks)

        batch_classified = [
            (cid, seg) for cid, _, seg, err in batch_results if seg is not None
        ]
        batch_skipped = sum(
            1 for _, _, seg, err in batch_results if seg is None and err is None
        )
        batch_errors = sum(1 for _, _, seg, err in batch_results if err is not None)

        if not args.dry_run and batch_classified:
            written = write_segments(batch_classified)
            if not json_out:
                print(f"  Written {written} to DB")

        total_classified += len(batch_classified)
        total_skipped += batch_skipped
        total_errors += batch_errors

        emit({"event": "batch_done", "batch": batch_num}, json_out)

        if i + BATCH_SIZE < total:
            emit({"event": "waiting", "seconds": BATCH_DELAY}, json_out)
            if not json_out:
                print(f"  Waiting {BATCH_DELAY}s...")
            await asyncio.sleep(BATCH_DELAY)

    if args.dry_run:
        if not json_out:
            print("\n[DRY RUN] No data written to DB.")
        emit(
            {
                "event": "done",
                "classified": total_classified,
                "skipped": total_skipped,
                "errors": total_errors,
                "dry_run": True,
            },
            json_out,
        )
    else:
        emit(
            {
                "event": "done",
                "classified": total_classified,
                "skipped": total_skipped,
                "errors": total_errors,
            },
            json_out,
        )
        if not json_out:
            print(f"\n{'=' * 40}")
            print(f"Total      : {total}")
            print(f"Classified : {total_classified}")
            print(f"Skipped    : {total_skipped}")
            print(f"Errors     : {total_errors}")
            print(f"{'=' * 40}")


if __name__ == "__main__":
    asyncio.run(main())
