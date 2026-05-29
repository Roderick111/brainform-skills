---
description: Personalize outreach email for direct prospects (Cluster 1)
---

# Personalize Outreach Email

## Context — read before doing anything

1. Read `context/product_summary.md` — what Brainform does
2. Read `context/outreach_templates.md` — for follow-up sequence and connection notes
3. Read `context/writing.md` — writing rules and anti-AI checklist (read AGAIN right before writing)

## Input

$ARGUMENTS

Format per entry:
```
website_url / email | Person Name, Job Title | optional company description
```

Single entry or a list.

## For each entry

1. **Match the title** to the closest role from the Role Briefings below.
2. **Fetch the homepage only** using WebFetch. You're looking for ONE thing: what they sell and why their catalog is complex.
3. **Fill in the template** using the matched role's lens, language, and fear.

## Subject line (for email only, skip for LinkedIn DMs)

Format: `[brand].com audit discussion`

## Template

```
Subject: [brand].com audit discussion

Hi [First_name],

Spent some time on [brand].com, [1-2 sentences: ONE concrete observation from their site, framed through this role's pain lens, using their language]

Full audit: [audit_url]

Open to a 20 min chat if relevant.

Best,
Daniel from Brainform
```

## Role Briefings

### Head of eCommerce / Digital Director
- **Lens:** Conversion gap on search/category pages they can't explain from analytics
- **Language:** Conversion rate, category performance, search exit, "tried X but..."
- **Fear:** Buying something that doesn't move the number, then explaining it at QBR
- **Frame the observation as:** Something specific on their site where search or category navigation fails a customer with a real question

### COO / VP Operations
- **Lens:** Returns with "wrong product" as the reason = selection problem on site, not defect
- **Language:** Return rate, cost per return, margin, operational cost
- **Fear:** Investing in a site change ops can't control that doesn't move the number
- **Frame the observation as:** A catalog complexity that predictably produces wrong purchases

### Head of Customer Support
- **Lens:** Pre-purchase tickets ("which one?", compatibility, sizing) the site should handle
- **Language:** Ticket volume, pre-purchase questions, deflection, "this isn't a CS problem"
- **Fear:** Being told to "just handle it" instead of root cause getting fixed
- **Frame the observation as:** Types of questions customers clearly can't answer from the site

### CMO / CDO / Head of CX
- **Lens:** Online experience can't replicate what a store rep does in 5 minutes
- **Language:** Customer experience, NPS, online vs offline, brand consistency
- **Fear:** Deploying something that feels off-brand or gives wrong advice
- **Frame the observation as:** Where the site feels transactional while the brand promises consultative

### Founder / CEO
- **Lens:** Invisible revenue loss from customers who leave to figure it out elsewhere
- **Language:** Revenue, growth, "money left on the table", traffic vs conversion
- **Fear:** Wasting time on something that demos well but doesn't move revenue
- **Frame the observation as:** Where customers with real needs silently leave because the site can't help

## What NOT to do

- Do NOT add paragraphs beyond what the template has
- Do NOT research company history, leadership, funding, strategy
- Do NOT add "insights" about their business you can't see on the site
- Do NOT try to sound smart or analytical. One observation is enough.
- Do NOT rewrite the template structure. Follow it exactly.
- If you can't find a concrete observation from the homepage, use the template with a generic framing for that role. Generic > fake-specific.

## Audit link

Audit link is MANDATORY. URL format: `https://brainform.beautiful-apps.com/{company-slug}`
Check `dev/audits/` for matching files. If no audit found, STOP and tell the user. Do not generate email without audit link.

## Writing rules

All rules in `context/writing.md`. Re-read it right before writing the email.

After drafting, self-check:
1. Any em dashes (—)? Replace with comma or period.
2. Any group of exactly three? Change to two or four.
3. Any banned word? Swap for plain version.
4. Audit link present? If not, STOP.
5. Template structure intact? No extra lines?

## Output

For each entry:
1. **[Person Name — Company]**
2. Role matched to: [which role]
3. The personalized message (ready to send)

Do NOT save to file. Output drafts only.
