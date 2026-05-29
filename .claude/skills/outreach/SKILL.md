---
name: outreach
description: Generate personalized cold outreach emails and save as Gmail drafts. Use when asked to create outreach emails, personalize messages for prospects, or draft cold emails. Input is a list of email addresses, company domains, or domains with manual contact info. Looks up contacts in the Neon PostgreSQL database, fetches company websites, generates role-matched personalized emails, and creates Gmail drafts with recipients pre-filled. Triggers on "outreach", "cold email", "personalize email", "draft emails", "email prospects".
---

# Outreach Email Generator

Generate personalized cold emails for direct prospects (Cluster 1) and save as Gmail drafts.

## Workflow

For each entry in the input:

### 1. Lookup contact data

Run the lookup script:
```bash
uv run .claude/skills/outreach/scripts/lookup_contact.py <email_or_domain>
```

Parse the JSON output. The script returns:
- `found`: whether company/contacts exist in DB
- `contacts`: eligible contacts (first_name, last_name, title, email, country)
- `already_contacted`: contacts already emailed (skip these)
- `company`: company info (name, domain, short_description, industry, country)
- `audit_exists` / `audit_file` / `audit_url`: whether audit exists, local file path, and the ready-to-use URL for the email

### 2. Handle input variations

- **Email found in DB**: use the contact data returned
- **Domain found in DB**: use up to 3 returned contacts
- **Not in DB but manual info provided** (format: `domain | Name, Title | description`): use manual info, still fetch the site
- **Not in DB, no manual info**: extract domain from email, fetch site, generate for generic "decision maker", flag as incomplete in summary

### 3. Check audit exists

If `audit_exists` is false from the lookup script: STOP processing this contact. Tell the user "No audit found for {domain}" and move to the next entry.

### 4. Prepare

1. **Extract contact fields**: from the lookup output, note `first_name`, `email`, `country`, `title`. Use `first_name` in the greeting. NEVER infer name from the email address prefix.
2. **Get product_category**: from lookup output `company.product_category`. If missing, derive from `short_description`.
3. **Match role**: use `title` to identify role via `references/role_briefings.md`. This determines framing for any personalization beyond the base template.
4. **Read writing rules**: `context/writing.md`
5. **Read template**: `references/email_template.md`

### 5. Write the email

Use one of the three frames from `references/email_template.md`:
- **Frame A** ("something interesting"): default. Works for most brands.
- **Frame B** ("competitive comparison"): when the brand has clear competitors.
- **Frame C** ("research inclusion"): for batch outreach or when you lack strong GEO data.

The email does NOT contain site observations, product bridges, or explanations of what Brainform does. It creates curiosity and drives a click to the audit page. That's the only job.

**Language**: check `contact.country`. Non-English countries: write entire email in local language. Keep subject line, audit URL, and "Daniel from Brainform" in English.

### 6. Self-check (before creating draft)

1. No em dashes (`—` or `–`). Replace with comma or period.
2. No rule-of-three lists.
3. No banned words or filler openers from `context/writing.md`.
4. Contact's full first name used (not initial, not abbreviated).
5. Audit link present.
6. "Daniel from Brainform" in signature.
7. No site observations, no product bridges, no Brainform explanation.
8. No pitch language ("we can help", "happy to discuss", "I'd love to show you").
9. No outside diagnosis ("you're not showing up", "your competitors are ahead", "your site fails").
10. No tease language ("some of the results surprised me", "something interesting came up").
11. No fear-poking or manufactured urgency.
12. Follows the chosen frame structure exactly. No extra lines or paragraphs.
13. Has a soft CTA question.
14. No vague social proof ("a few agencies", "several brands" with no names). Either name them or don't mention them.

After checking these rules, read `.claude/skills/follow-up/references/anti_ai_patterns.md` and run every check from that file against the draft. Fix ALL violations before proceeding.

### 7. Create Gmail draft

**Create the draft immediately after self-check passes. Do NOT ask for confirmation or show the draft for review first.**

Use the `gmail_create_draft` MCP tool:
- **To**: contact's email
- **Subject**: `[domain] audit discussion`
- **Body**: the generated email text

### 8. Show summary

```
Drafts created:
  Daniel Alter (CEO) — suave.com — draft created

Skipped (already contacted):
  - Mike Clark (suave.com) — sent_1

Skipped (no data):
  - jane@unknown.com — not in DB, no company match
```

---

## Writing Principles

All anti-AI rules live in `context/writing.md`. Read it at step 4.

### Give frame
The audit is the gift. The email delivers it without diagnosing problems, pointing out failures, or poking fears. "Put together a breakdown" = giving. "Your competitors show up and you don't" = diagnosing. The reader opens the audit and discovers the gaps themselves.

### No outside diagnosis
Never tell the brand what's wrong with their site, visibility, or strategy. The audit does that. The email just delivers it.

### Autonomy over pressure
Soft CTAs only. "Thought you'd want to see it" preserves choice. No manufactured urgency, no fear-poking, no "your competitors are ahead."

### Three-layer pattern (when personalizing beyond base template)
If role is known from `title`, frame the email so the reader's personal job is implicitly served through the business outcome. The email is minimal, but the framing line can land differently:
- Head of eCommerce: "how AI agents recommend [product_category]" — they see a channel to report on
- Head of Support: framing around product choice questions — they see ticket deflection
- CMO: framing around the customer experience — they see something to own
- CEO: framing around the category — they see revenue signal

Don't force this. The base template works for most contacts. Only personalize when the role is clear and the framing change is natural.

### What the email does NOT contain
- Site observations or product analysis
- Bridge sentences explaining what Brainform does
- Company research or flattery
- Tease language ("some of the results surprised me", "something interesting came up")
- Fear-poking ("your competitors are ahead", "you're not showing up")
- Pitch language ("we can help", "happy to discuss", "I'd love to show you")

It contains: greeting, one sentence about what you tested, brand name, audit link, soft CTA. That's it.
