#!/usr/bin/env python3
"""
LLM segmentation: classify companies by type + vertical.
Usage: uv run dev/scripts/segment_companies.py --limit 50
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

COMPANY_TYPES = Literal[
    "ecom-product",
    "service-business",
    "b2b-manufacturer",
    "software-tech",
    "healthcare",
    "wholesale",
    "agency",
    "other",
]

VERTICALS = Literal[
    "beauty-skincare",
    "health-nutrition",
    "sporting-goods",
    "home-appliances",
    "consumer-electronics",
    "cycling-fitness",
    "fashion-apparel",
    "baby-kids",
    "food-beverage",
    "outdoor-tools",
    "pet-care",
]


class CompanySegment(BaseModel):
    company_type: COMPANY_TYPES = Field(
        description="Business model: how the company sells",
    )
    verticals: list[VERTICALS] = Field(
        default_factory=list,
        max_length=2,
        description="Product domain, only for ecom-product",
    )

    @model_validator(mode="after")
    def verticals_only_for_ecom(self) -> "CompanySegment":
        if self.company_type != "ecom-product" and self.verticals:
            raise ValueError(
                "verticals must be empty when company_type is not ecom-product"
            )
        return self


SYSTEM_PROMPT = """# Role
You are a company classifier for a B2B SaaS that sells AI commerce tools to online retailers.
Your task: given a company profile, classify it by company type and vertical.

# Company types (pick exactly one)
- ecom-product: brand that sells physical products directly to consumers (D2C) through its own online store or website
- service-business: provides services, not products — spa, salon, gym, clinic, restaurant, medical aesthetics, dental, resort, franchise, repair, consulting
- b2b-manufacturer: manufactures or supplies products for OTHER businesses (B2B), no consumer-facing online store
- software-tech: builds software, apps, platforms, or online marketplaces (no physical product — if the company sells a physical device with an app, it is ecom-product, not software-tech). Includes: SaaS, marketplaces where the company does not own inventory, simulation/technology platforms sold B2B.
- healthcare: hospitals, pharma companies, pharmaceutical manufacturers, medical device companies, clinical research, telemedicine platforms. ANY company whose primary business is developing, manufacturing, or selling pharmaceuticals, nutraceuticals, or medical devices = healthcare, even if they "manufacture" products.
- wholesale: distributes products to other businesses with NO consumer-facing brand or store of its own. A pure distributor, reseller, or supply chain intermediary. Key signal: "distributor", "distribution", "supply" in description with no own-brand manufacturing.
- agency: eCommerce or digital marketing agency
- other: does not fit any of the above, or insufficient information to classify. Includes: sports teams, professional associations, foundations, publishers, holding companies, educational institutions, media companies, event organizers. Do NOT force a company into ecom-product just because it might sell something — use "other" when the primary business is clearly not commerce.

# Verticals (pick 0-2, only if company_type is ecom-product)
- beauty-skincare: cosmetics, skincare, fragrance, personal care
- health-nutrition: supplements, vitamins, wellness products
- sporting-goods: sports equipment, outdoor gear, athletic products
- home-appliances: kitchen, laundry, home electronics
- consumer-electronics: audio, gaming peripherals, smart devices, gadgets
- cycling-fitness: bicycles, cycling gear, fitness equipment
- fashion-apparel: clothing, footwear, accessories
- baby-kids: baby products, kids toys, children's gear
- food-beverage: specialty food, drinks, grocery
- outdoor-tools: DIY, tools, garden equipment, automotive accessories
- pet-care: pet food, accessories, animal health

# How to decide: description > industry field
The industry field comes from a third-party data provider and is often WRONG. Always prioritize the description. If the description says the company sells consumer products online but the industry field says "manufacturing" or "engineering", trust the description.

# Core rule: company_type is about HOW THE COMPANY SELLS, not what it makes
- A company that sells skincare PRODUCTS through its own online store = ecom-product + beauty-skincare
- A company that provides skincare SERVICES (salon, spa, injections) = service-business
- A company that makes skincare for OTHER COMPANIES (B2B supply) = b2b-manufacturer
- A company with NO consumer brand that only distributes to retailers = wholesale

# DTC-priority rule
If a company manufactures products AND sells them to end consumers through its own website or online store, classify as ecom-product — NOT b2b-manufacturer. The b2b-manufacturer label is ONLY for companies that sell exclusively to other businesses with no consumer-facing store.
Similarly, if a company operates an online store selling products to consumers (even if it curates from multiple brands), classify as ecom-product — NOT wholesale. Wholesale is ONLY for companies with no consumer-facing brand or storefront.

# ecom-product signals (look for these in the description)
- "online store", "direct-to-consumer", "D2C", "e-commerce", "available on their website"
- Brand sells its own products, has its own website/store
- Revenue comes from consumer sales through their own channels
- Company owns a consumer brand and sells physical products to end consumers — even if ALSO available in retail chains (Walmart, Target, Amazon). Retail distribution does NOT disqualify from ecom-product.
- Company sells a physical consumer device with a companion app/software. The device is the product → ecom-product, not software-tech.
- Company has both service locations (salons, clinics) AND sells its own branded product line D2C online. If the product line is a core business → ecom-product.

# NOT ecom-product signals
- Company has NO consumer brand of its own — purely distributes or resells others' products
- Products sold ONLY through custom installers, dealers, or B2B channels, no consumer-facing store at all
- Company provides services only (treatments, consultations, repairs) and does not sell its own product line

# Anti-patterns
- Do NOT trust the industry field blindly. "electrical/electronic manufacturing" does NOT mean b2b-manufacturer if the company sells consumer products.
- Do NOT classify a service provider (spa, clinic, medical aesthetics, restaurant) as ecom-product.
- Do NOT classify a consumer brand as wholesale just because it also sells through retail chains. Wholesale = no consumer brand, pure distributor.
- Do NOT classify a physical device company as software-tech because it has an app or AI features.
- Do NOT classify a service+product hybrid as service-business if the product line is a core business.
- Do NOT assign verticals to non-ecom companies.
- Do NOT classify a company as b2b-manufacturer just because it manufactures its own products. If it sells those products to end consumers through its own website or online store, it is ecom-product.
- Do NOT classify an online retailer as wholesale. If the company operates a consumer-facing e-commerce store (even selling other brands), it is ecom-product. Wholesale = no consumer storefront, sells only to businesses.
- Do NOT classify a pharmaceutical, nutraceutical, or medical device company as b2b-manufacturer. If the company's core domain is health/pharma/medical, it is healthcare regardless of whether it "manufactures" its products.
- Do NOT classify an online marketplace or platform as ecom-product. If the company connects buyers and sellers but does not own inventory, it is software-tech.
- Do NOT classify a distributor as b2b-manufacturer. If the company distributes/resells products it did not make, it is wholesale.
- Do NOT force "ecom-product" on sports teams, associations, foundations, publishers, or holding companies. These are "other".
- Do NOT output anything except valid JSON.

# Rules
1. Pick exactly one company_type.
2. Pick 0-2 verticals only if company_type is ecom-product. Otherwise empty list.
3. Use only the labels listed above.
4. If the company does not clearly fit any category, use "other".
5. Output ONLY valid JSON. No reasoning, no meta-text, no explanations."""

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
        WHERE segment IS NULL
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
    cur.execute("SELECT COUNT(*) FROM companies WHERE segment IS NULL")
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
) -> tuple[int, str, CompanySegment | None, str | None]:
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
                    max_tokens=512,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_model=CompanySegment,
                    max_retries=2,
                )
                segment_list = [result.company_type, *result.verticals]
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


def write_segments(results: list[tuple[int, CompanySegment]]) -> int:
    if not results:
        return 0
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    written = 0
    for company_id, seg in results:
        segment_array = [seg.company_type, *seg.verticals]
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
    parser = argparse.ArgumentParser(description="Segment companies via LLM")
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
            print("No unclassified companies found.")
        return

    total = len(rows)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    emit({"event": "start", "total": total, "model": MODEL}, json_out)
    if not json_out:
        print(f"Fetched {total} unclassified companies. Model: {MODEL}")

    openai_client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    client = instructor.from_openai(openai_client, mode=instructor.Mode.JSON)
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
