#!/usr/bin/env python3
"""
Normalize company names for outreach: strip legal suffixes, taglines, noise.
Usage:
  uv run dev/scripts/normalize_company_names.py --limit 50
  uv run dev/scripts/normalize_company_names.py --limit 50 --write
"""

import argparse
import asyncio
import json
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
MAX_RETRIES = 4
RETRY_DELAY = 3

SYSTEM_PROMPT = """# Role

You are a data cleanup assistant. You normalize raw company names from a CRM database so they look natural in outreach messages like:

"I found some interesting results about [NAME]"
"saw you're at [NAME]"

The name must look like something a human would type when referring to a brand — not a legal filing, not a database entry.

# What to remove

1. LEGAL SUFFIXES: GmbH, GmbH & Co. KG, S.r.l., S.R.L., Srl, S.p.A., S.p.a., Spa, SAS, SARL, SA, SL, S.L., S.L.U., SLU, LLC, Ltd, Inc, Corp, AG, PLC, BV, B.V., NV, AB, A/S, ApS, KG, SE, SB, Co., & Co., Group, International (when it's a suffix, not part of the brand).

2. TAGLINES AND DESCRIPTIONS after separators: everything after " - ", " | ", " // ", " / " IF what follows is a tagline, description, or parent company — NOT if both sides are the brand name. "COCUNAT | Clinical Cosmetics" → "COCUNAT". But "Coleman / Camping Gaz / Sevylor" → keep as-is, those are all brand names.

3. PARENTHETICAL NOISE: "(mucki®)", "(Just Over The Top)", "(Cirosport, S.L.)" — remove the parentheses and contents UNLESS the parenthetical IS the known brand name.

4. SPECIAL CHARACTERS: ®, ™, >, §, trailing dots, leading apostrophes.

5. ".com" / ".dk" / ".net" SUFFIXES: only when they're clearly a domain suffix tacked onto a brand. "Coolshop.com" → "Coolshop". But keep if the .com IS the brand (like "neckermann.com" — the brand is literally that).

6. EMBEDDED TAGLINES: "BODY ATTACK - FOR REAL PERFORMERS!" → "BODY ATTACK". "Famille Mary french beekeeper since 1921" → "Famille Mary".

# What to KEEP

- THE BRAND NAME AS THE MARKET KNOWS IT. Don't invent a shorter version. Don't translate.
- INTENTIONAL CAPITALIZATION: "BUFF" stays "BUFF". "DYNAFIT" stays "DYNAFIT". "edubily" stays "edubily". These are brand styles.
- GEOGRAPHIC OR PRODUCT QUALIFIERS that are part of the brand: "K-WAY France" → "K-WAY" (France is a regional qualifier, not part of the brand). But "Blue Banana Brand" → "Blue Banana Brand" (Brand is part of their name).
- NON-ENGLISH NAMES: "Café du Cycliste" stays. "Médor et Compagnie" stays. Don't anglicize.

# Decision logic

Ask yourself: "If I were writing a LinkedIn message to someone at this company, how would I refer to it?" That's your answer.

# Examples

| Input | Output | Why |
|---|---|---|
| Centershop Korn Vertriebs GmbH & Co. KG | Centershop Korn | Strip "Vertriebs GmbH & Co. KG" |
| COCUNAT \| Clinical Cosmetics | COCUNAT | Tagline after pipe |
| Naked Copenhagen - Supplying Girls With Sneakers | Naked Copenhagen | Tagline after dash |
| AnovonA Medsupps GmbH (mucki®) | AnovonA Medsupps | Legal suffix + parenthetical |
| JOTT (Just Over The Top) | JOTT | Parenthetical expansion |
| Farmacia Loreto Gallo Srl - Gruppo Farmacie Italiane Srl | Farmacia Loreto Gallo | Legal suffix + parent company |
| Fashioncenter GmbH // Lotto Sport Germany | Fashioncenter | Second brand after separator |
| BODY ATTACK - FOR REAL PERFORMERS! | BODY ATTACK | Tagline after dash |
| Famille Mary french beekeeper since 1921 | Famille Mary | Embedded tagline |
| Coolshop.com | Coolshop | Domain suffix |
| edubily® | edubily | Registered mark |
| '+Watt S.r.l. | +Watt | Legal suffix + leading apostrophe |
| Tunturi Fitness \| B Corp™ | Tunturi Fitness | Certification after pipe |
| INTERSPORT Krumholz | INTERSPORT Krumholz | Both words are the brand — keep |
| Castelli Cycling | Castelli Cycling | Brand name — keep |
| Café du Cycliste | Café du Cycliste | Non-English brand — keep |
| Coleman / Camping gaz / Sevylor | Coleman / Camping Gaz / Sevylor | Multiple brands — keep |
| Ana Maria Lajusticia® | Ana Maria Lajusticia | Just strip ® |
| SVB Spezialversand für Yacht- und Bootszubehör GmbH | SVB | Long German descriptor + legal suffix |
| Natur I Floriterapia I Integratori PNEI Curativi I Formazione Naturopatia I Cosmesi Bio Emozionale | Natur | Everything after first word is a description |
| Isomed \| Alimenti ed Integratori per diete chetogeniche | Isomed | Description after pipe |
| Matt - A&D S.p.A. Gruppo Alimentare e Dietetico | Matt | Brand is "Matt", rest is legal entity info |

# Output

ONLY the cleaned name. No quotes, no explanation."""


class CleanName(BaseModel):
    clean_name: str = Field(
        description="The normalized brand name, ready for outreach messages",
    )


def fetch_companies(limit: int) -> list[dict]:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name
        FROM companies
        WHERE needs_name_cleanup = TRUE
        ORDER BY name
        LIMIT %s
        """,
        (limit,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


async def normalize_one(
    client: instructor.AsyncInstructor,
    row: dict,
    sem: asyncio.Semaphore,
) -> tuple[dict, str | None, str | None]:
    name = row["name"]

    async with sem:
        for attempt in range(MAX_RETRIES):
            try:
                result = await client.chat.completions.create(
                    model=MODEL,
                    max_tokens=64,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": name},
                    ],
                    response_model=CleanName,
                    max_retries=2,
                )
                return row, result.clean_name, None
            except Exception as e:
                err = str(e)
                is_transient = "502" in err or "503" in err or "429" in err
                if is_transient and attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
                    continue
                return row, None, err


def write_names(results: list[tuple[int, str]]) -> int:
    if not results:
        return 0
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for company_id, clean_name in results:
        cur.execute(
            "UPDATE companies SET name = %s, needs_name_cleanup = FALSE WHERE id = %s",
            (clean_name, company_id),
        )
    conn.commit()
    cur.close()
    conn.close()
    return len(results)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize company names via LLM")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--write", action="store_true", help="Write cleaned names to DB",
    )
    args = parser.parse_args()

    rows = fetch_companies(args.limit)
    if not rows:
        print("No companies need name cleanup.")
        return

    total = len(rows)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"Loaded {total} companies needing cleanup. Model: {MODEL}")

    openai_client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    client = instructor.from_openai(openai_client)
    sem = asyncio.Semaphore(CONCURRENCY)

    all_results = []
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"\nBatch {batch_num}/{total_batches} ({len(batch)} names)...")

        tasks = [normalize_one(client, row, sem) for row in batch]
        batch_results = await asyncio.gather(*tasks)

        ok = 0
        errors = 0
        to_write = []
        for row, clean, err in batch_results:
            orig = row["name"]
            if err:
                errors += 1
                print(f"  [ERROR] {orig}: {err[:60]}")
            else:
                ok += 1
                changed = " *" if orig != clean else ""
                print(f"  {orig[:40]:<40} → {clean[:40]}{changed}")
                if orig != clean:
                    to_write.append((row["id"], clean))

        if args.write and to_write:
            written = write_names(to_write)
            print(f"  Written {written} to DB")

        all_results.extend(batch_results)

        if i + BATCH_SIZE < total:
            print(f"  Waiting {BATCH_DELAY}s...")
            await asyncio.sleep(BATCH_DELAY)

    total_ok = sum(1 for _, c, e in all_results if c is not None)
    total_changed = sum(1 for r, c, e in all_results if c is not None and r["name"] != c)
    total_errors = sum(1 for _, _, e in all_results if e is not None)

    print(f"\n{'=' * 50}")
    print(f"Total      : {total}")
    print(f"OK         : {total_ok}")
    print(f"Changed    : {total_changed}")
    print(f"Unchanged  : {total_ok - total_changed}")
    print(f"Errors     : {total_errors}")
    if not args.write:
        print(f"\nDry run. Use --write to save.")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
