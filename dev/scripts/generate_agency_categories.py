#!/usr/bin/env python3
"""
Generate product_category for ecom-agencies without platform in segment.
Uses LLM to classify into: specific platform, amazon, ecommerce development,
ecommerce marketing, ecommerce consulting, marketplace management.

Usage:
  uv run dev/scripts/generate_agency_categories.py --limit 30
  uv run dev/scripts/generate_agency_categories.py --limit 50 --write
"""

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import instructor
import psycopg2
from openai import AsyncOpenAI
from pydantic import BaseModel, Field


DB_URL = os.environ["DATABASE_URL"]

MODEL = "google/gemma-4-31b-it"
CONCURRENCY = 50
BATCH_SIZE = 50
BATCH_DELAY = 3


SYSTEM_PROMPT = """You classify an ecommerce agency into one category.

The category will be used in LinkedIn messages like:
- "you guys have been doing [CATEGORY] for a while"
- "saw you specialize in [CATEGORY]"

Pick ONE from this list. Nothing else. No variations. No combinations.

CATEGORIES:
- "Shopify" — builds or manages Shopify/Shopify Plus stores
- "Prestashop" — builds or manages Prestashop stores
- "Magento" — builds or manages Magento/Adobe Commerce stores
- "WooCommerce" — builds or manages WooCommerce stores
- "headless commerce" — builds on commercetools, MACH, composable, or headless platforms
- "Amazon seller management" — manages Amazon seller/vendor accounts, Amazon ads, Amazon SEO
- "marketplace selling" — manages selling on multiple marketplaces (not Amazon-only)
- "ecommerce development" — builds online shops, no single dominant platform
- "ecommerce marketing" — runs ads, SEO, growth, retention for ecom brands. Does NOT build shops.
- "ecommerce consulting" — advises on ecom strategy. Does NOT build or run ads.

RULES (non-negotiable):

1. OUTPUT EXACTLY ONE CATEGORY from the list above. Copy it letter for letter.

2. If the agency clearly focuses on one platform (Shopify, Magento, etc.), pick that platform even if they also do other things.

3. Amazon agencies are common. If the agency ONLY does Amazon, pick "Amazon seller management". If they manage Amazon AND other marketplaces (eBay, Kaufland, etc.), pick "marketplace selling". Do NOT pick "ecommerce marketing" for Amazon agencies.

4. If they build shops AND do marketing, pick based on what they lead with. If unclear, pick "ecommerce development".

5. NO META-COMMENTARY. No "I chose X because". Just the answer.
"""


class AgencyCategory(BaseModel):
    category: str = Field(
        description="Exactly one category from the allowed list",
    )
    reasoning: str = Field(
        description="What the agency does. One factual sentence.",
    )


def fetch_agencies(limit: int) -> list[dict]:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, short_description, keywords, industry, segment, domain
        FROM companies
        WHERE segment[1] = 'agency'
          AND segment[2] = 'ecom-agency'
          AND (segment[3] IS NULL OR array_length(segment, 1) = 2)
          AND product_category IS NULL
        LIMIT %s
        """,
        (limit,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def build_user_prompt(row: dict) -> str:
    name = row["name"] or "Unknown"
    desc = row["short_description"] or "No description"
    industry = row["industry"] or "Unknown"
    keywords = row.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",")]
    keywords = keywords[:10]
    kw_str = ", ".join(keywords) if keywords else "None"
    domain = row.get("domain") or "None"

    return (
        f'Agency: "{name}" | Domain: {domain}\n'
        f'Industry: "{industry}"\n'
        f'Description: "{desc}"\n'
        f"Keywords: {kw_str}"
    )


async def classify_one(
    client: instructor.AsyncInstructor,
    row: dict,
    sem: asyncio.Semaphore,
) -> tuple[dict, AgencyCategory | None, str | None]:
    if not row.get("short_description") and not row.get("keywords"):
        return row, None, "no description or keywords"

    user_prompt = build_user_prompt(row)

    async with sem:
        try:
            result = await client.chat.completions.create(
                model=MODEL,
                max_tokens=128,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_model=AgencyCategory,
                max_retries=3,
            )
            return row, result, None
        except Exception as e:
            return row, None, str(e)


async def run_batch(
    rows: list[dict],
    iteration: int,
    total_iterations: int,
) -> list[tuple[dict, AgencyCategory | None, str | None]]:
    openai_client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    client = instructor.from_openai(openai_client)
    sem = asyncio.Semaphore(CONCURRENCY)

    print(f"\n{'=' * 70}")
    print(f"ITERATION {iteration}/{total_iterations}")
    print(f"{'=' * 70}")

    all_results = []
    total = len(rows)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} agencies)...")

        tasks = [classify_one(client, row, sem) for row in batch]
        batch_results = await asyncio.gather(*tasks)
        all_results.extend(batch_results)

        if i + BATCH_SIZE < total:
            print(f"  Waiting {BATCH_DELAY}s...")
            await asyncio.sleep(BATCH_DELAY)

    # Print results
    ok = 0
    errors = 0
    skipped = 0

    print(f"\n{'─' * 70}")
    print(f"{'Company':<35} {'Category':<25} {'Reasoning'}")
    print(f"{'─' * 70}")

    for row, result, err in all_results:
        name = row["name"][:34]
        if result:
            ok += 1
            print(f"{name:<35} {result.category:<25} {result.reasoning[:50]}")
        elif err and "no description" in err:
            skipped += 1
            print(f"{name:<35} {'[SKIPPED]':<25}")
        else:
            errors += 1
            print(f"{name:<35} {'[ERROR]':<25} {str(err)[:50]}")

    # Category distribution
    cats = {}
    for _, result, _ in all_results:
        if result:
            cats[result.category] = cats.get(result.category, 0) + 1

    print(f"\n{'─' * 70}")
    print(f"OK: {ok} | Skipped: {skipped} | Errors: {errors}")
    print(f"\nDistribution:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {cat:<30} {count}")

    # Message preview
    print(f"\n{'─' * 70}")
    print("MESSAGE PREVIEW (how it reads in outreach):")
    print(f"{'─' * 70}")
    previewed = set()
    for row, result, _ in all_results:
        if result and result.category not in previewed:
            previewed.add(result.category)
            name = row["name"]
            print(f'  "you guys have been doing {result.category} for a while" — {name}')
            print(f'  "saw you specialize in {result.category}" — {name}')
            print()

    return all_results


def write_categories(
    results: list[tuple[dict, AgencyCategory | None, str | None]],
) -> int:
    to_write = [(row["id"], res.category) for row, res, err in results if res]
    if not to_write:
        return 0
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for company_id, category in to_write:
        cur.execute(
            "UPDATE companies SET product_category = %s WHERE id = %s",
            (category, company_id),
        )
    conn.commit()
    cur.close()
    conn.close()
    return len(to_write)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate categories for ecom agencies",
    )
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument(
        "--write", action="store_true", help="Write results to companies.product_category",
    )
    args = parser.parse_args()

    rows = fetch_agencies(args.limit)
    if not rows:
        print("No unprocessed ecom-agencies found.")
        return

    print(f"Loaded {len(rows)} ecom-agencies without product_category.")

    for i in range(1, args.iterations + 1):
        results = await run_batch(rows, i, args.iterations)

    if args.write:
        written = write_categories(results)
        print(f"\n✓ Written {written} categories to DB.")
    else:
        print(f"\nDry run. Use --write to save to DB.")


if __name__ == "__main__":
    asyncio.run(main())
