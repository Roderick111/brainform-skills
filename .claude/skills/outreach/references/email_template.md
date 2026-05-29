# Email Template

Three frames available. Pick the best fit based on what you know about the company. Default to Frame A.

## Frame A: "AI agents + your brand" (default)

Best for: most brands. Direct, states what you did, no tease.

```
Subject: [domain] audit discussion

Hey [First_name],

I was testing how AI agents recommend [product_category] and [brand] came up in the results. Put together a quick breakdown:

[audit_url]

Thought you'd want to see it.

Daniel from Brainform
```

## Frame B: "Competitive comparison"

Best for: brands with clear competitors in the audit's GEO data.

```
Subject: [domain] audit discussion

Hey [First_name],

Ran a comparison of how AI agents recommend [product_category] brands. [brand] and a few competitors are in the breakdown.

Full results here: [audit_url]

Curious what you make of it.

Daniel from Brainform
```

## Frame C: "Research inclusion"

Best for: batch outreach or when you don't have strong GEO data for the specific brand.

```
Subject: [domain] audit discussion

Hey [First_name],

We're benchmarking how AI agents handle product discovery across [product_category] retailers. [brand] is in the dataset.

Your company's breakdown: [audit_url]

Let me know if anything looks off or if I'm missing context.

Daniel from Brainform
```

## Field rules

- `[domain]` = company domain (e.g. suave.com)
- `[brand]` = company name as it appears publicly (e.g. "Merrell", "Applied Nutrition")
- `[First_name]` = contact's first name from lookup
- `[product_category]` = from companies.product_category in DB (e.g. "outdoor footwear", "sports nutrition", "skincare and cosmetics"). If not available, derive from company description.
- `[audit_url]` = use the `audit_url` field returned by the lookup script. Do NOT construct the URL manually.
- **Audit link is MANDATORY.** If `audit_exists` is false, STOP and tell the user "No audit found for {domain}."

## Key principles

- The audit is the gift. The email delivers it. That's the only job.
- Do NOT summarize audit findings. Let the page do the work.
- Do NOT explain what Brainform does. Zero pitch language.
- Do NOT diagnose their site, visibility, or strategy. No "you're not showing up", "your competitors are ahead."
- Do NOT use tease language. No "some of the results surprised me", "something interesting came up." Just say what you did.
- Do NOT say "we can help", "happy to discuss", "I'd love to show you."
- CTA is soft: "thought you'd want to see it", "curious what you make of it", "let me know if anything looks off."

## Language

Check `contact.country` from lookup. Non-English countries: write entire email in local language. Keep subject line, audit URL, and "Daniel from Brainform" in English.

## What NOT to do

- Do NOT add observations about their site in the email. The audit page handles that.
- Do NOT add bridge sentences explaining what Brainform does.
- Do NOT add extra paragraphs beyond the template.
- Do NOT personalize beyond the frame structure (no "I noticed your team", no "love what you're doing").
