#!/usr/bin/env python3
"""
Generate human-sounding product category phrases for outreach templates.
Reads ecom-product companies from DB, uses LLM to generate short category phrases.

Usage:
  uv run dev/scripts/generate_product_categories.py --limit 50
  uv run dev/scripts/generate_product_categories.py --limit 50 --write
"""

import argparse
import asyncio
import json
import os
import sys
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


SYSTEM_PROMPT = """You generate a short product category phrase for a company.

The phrase MUST work in ALL three of these sentences:
- "how AI agents recommend [PHRASE]"
- "how AI agents recommend [PHRASE] brands"
- "product discovery across [PHRASE] retailers"

If appending "brands" or "retailers" sounds wrong, YOUR PHRASE IS WRONG. Fix it.

RULES (non-negotiable):

1. CATEGORY LEVEL, NOT PRODUCT LEVEL. "outdoor footwear" not "hiking boots". "men's grooming" not "razors". The phrase must describe the SPACE the company operates in, not a single product they sell.

2. 2-4 WORDS MAX. No exceptions.

3. BUYER LANGUAGE ONLY. Use words a normal person would type into Google. No industry jargon, no insider terminology, no technical specs. If your mom wouldn't understand it, rewrite it.

4. NO MARKETING SPEAK. Never use: premium, innovative, cutting-edge, luxury, solutions, comprehensive, advanced, next-generation. Just describe what they sell.

5. NO META-COMMENTARY. Output ONLY the category phrase and reasoning. No disclaimers, no "this is tricky because", no "I chose X over Y because". Just the answer.

6. SPECIFIC ENOUGH TO IDENTIFY THE SPACE. "beauty products" is too vague — could be anything. "skincare and cosmetics" tells you the space. "consumer electronics" is useless — could be anything. "electric scooters" tells you the space.

Examples:
- A company selling protein powders and workout supplements → "sports nutrition"
- A company selling strollers, diaper bags, teethers → "baby gear"
- A company selling perfumes and scented candles → "fragrances"
- A company making AR-15 rifles and pistols → "firearms"
- A DTC brand selling face serums and moisturizers → "skincare"
"""


class ProductCategory(BaseModel):
    category_phrase: str = Field(
        description="2-4 word category phrase, lowercase, must sound natural before 'brands' and 'retailers'",
    )
    reasoning: str = Field(
        description="What the company sells. One factual sentence, no opinions or justifications.",
    )


def fetch_companies(limit: int) -> list[dict]:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, short_description, keywords, industry, segment, domain
        FROM companies
        WHERE segment[1] = 'ecom-product'
          AND product_category IS NULL
        ORDER BY created_at DESC
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
    keywords = keywords[:8]
    kw_str = ", ".join(keywords) if keywords else "None"
    segment = row.get("segment") or []
    verticals = ", ".join(segment[1:]) if len(segment) > 1 else "None"
    domain = row.get("domain") or "None"

    return (
        f'Company: "{name}" | Domain: {domain}\n'
        f'Industry: "{industry}" | Verticals: {verticals}\n'
        f'Description: "{desc}"\n'
        f"Keywords: {kw_str}"
    )


MAX_RETRIES = 4
RETRY_DELAY = 3


async def classify_one(
    client: instructor.AsyncInstructor,
    row: dict,
    sem: asyncio.Semaphore,
) -> tuple[dict, ProductCategory | None, str | None]:
    name = row["name"] or "Unknown"

    if not row.get("short_description") and not row.get("keywords"):
        return row, None, "no description or keywords"

    user_prompt = build_user_prompt(row)

    async with sem:
        for attempt in range(MAX_RETRIES):
            try:
                result = await client.chat.completions.create(
                    model=MODEL,
                    max_tokens=512,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_model=ProductCategory,
                    max_retries=2,
                )
                return row, result, None
            except Exception as e:
                err = str(e)
                is_transient = "502" in err or "503" in err or "429" in err
                if is_transient and attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                return row, None, err


async def run_iteration(
    rows: list[dict],
    iteration: int,
    total_iterations: int,
) -> list[tuple[dict, ProductCategory | None, str | None]]:
    openai_client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    client = instructor.from_openai(openai_client)
    sem = asyncio.Semaphore(CONCURRENCY)

    print(f"\n{'=' * 60}")
    print(f"ITERATION {iteration}/{total_iterations}")
    print(f"{'=' * 60}")

    all_results = []
    total = len(rows)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} companies)...")

        tasks = [classify_one(client, row, sem) for row in batch]
        batch_results = await asyncio.gather(*tasks)
        all_results.extend(batch_results)

        if i + BATCH_SIZE < total:
            print(f"  Waiting {BATCH_DELAY}s for rate limit...")
            await asyncio.sleep(BATCH_DELAY)

    # Print results
    ok = 0
    errors = 0
    skipped = 0

    print(f"\n{'─' * 60}")
    print(f"{'Company':<30} {'Category Phrase':<35} {'Reasoning'}")
    print(f"{'─' * 60}")

    for row, result, err in all_results:
        name = row["name"][:29]
        if result:
            ok += 1
            phrase = result.category_phrase[:34]
            reason = result.reasoning[:60]
            print(f"{name:<30} {phrase:<35} {reason}")
        elif err == "no description":
            skipped += 1
            print(f"{name:<30} {'[SKIPPED: no desc]':<35}")
        else:
            errors += 1
            print(f"{name:<30} {'[ERROR]':<35} {err[:60]}")

    print(f"\n{'─' * 60}")
    print(f"OK: {ok} | Skipped: {skipped} | Errors: {errors}")

    return all_results


def write_categories(
    results: list[tuple[dict, ProductCategory | None, str | None]],
) -> int:
    to_write = [(row["id"], res.category_phrase) for row, res, err in results if res]
    if not to_write:
        return 0
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for company_id, phrase in to_write:
        cur.execute(
            "UPDATE companies SET product_category = %s WHERE id = %s",
            (phrase, company_id),
        )
    conn.commit()
    cur.close()
    conn.close()
    return len(to_write)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate product category phrases for outreach",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument(
        "--write", action="store_true", help="Write results to companies.product_category",
    )
    args = parser.parse_args()

    rows = fetch_companies(args.limit)
    if not rows:
        print("No unprocessed ecom-product companies found.")
        return

    print(f"Loaded {len(rows)} companies (ecom-product, no product_category yet).")

    results = await run_iteration(rows, 1, 1)

    if args.write:
        written = write_categories(results)
        print(f"\n✓ Written {written} categories to DB.")
    else:
        print(f"\nDry run. Use --write to save to DB.")


if __name__ == "__main__":
    asyncio.run(main())
