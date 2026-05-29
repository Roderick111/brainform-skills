# Step 5: Anti-AI Cleanup

Go through the draft line by line. This is mechanical pattern matching. Remove or rewrite anything that matches the rules below.

**Important:** After cleanup, re-read the full post and check that the voice survived. AI pattern removal can flatten the writing into something technically clean but lifeless. If the cleanup killed a sentence that had personality, restore it and find a different fix.

---

## Hard rules

1. **No em dashes.** Use commas, periods, or parentheses.
2. **No rule-of-three lists.** Two items fine. Four fine. Never exactly three items in a list or sequence.
3. **No contrast framing.** "It's not X, it's Y" and all variants ("Not X. Y." counts too). Just say what you mean directly.
4. **No staccato bursts.** Three or more short sentences stacked in a row for dramatic effect. Vary length naturally.
5. **No rhetorical transitions.** "The catch?" "But here's the thing." "So what does this mean?" Delete.
6. **No self-narration.** "This highlights," "here's why this matters," "the pattern that keeps showing up:" = delete. State the thing directly.
7. **No vague scale.** "Many," "most," "significant," "strong results," "often," "increasingly" = replace with a number, a specific situation, or cut the claim.
8. **No -ing phrases tacked to sentence ends.** "We built a tool, making it easy to..." Cut after the comma. If the -ing part matters, make it a separate sentence with specifics.
9. **No "serves as / stands as / functions as."** Use "is."
10. **No formal transitions.** "However," "Moreover," "Furthermore," "Additionally" at sentence start = delete or rewrite.
11. **No significance inflation.** "Marking a pivotal moment," "a testament to," "a bigger deal than it sounds," "this changes everything."
12. **No weightless sentences.** If a sentence could be removed and nothing is lost, remove it. Setup sentences ("Let me explain"), summary sentences ("And that's why"), transition sentences that just connect paragraphs = delete.
13. **No false openers.** "Quick question," "Just wanted to," "Circling back," "Touching base" = cut.

---

## Banned words

**Adjectives:** cutting-edge, innovative, comprehensive, seamless, robust, game-changing, transformative, holistic, dynamic, compelling

**Verbs:** leverage, utilize, optimize, empower, elevate, harness, streamline, unlock, navigate (figurative), facilitate

**Phrases:** "in today's landscape", "at its core", "it's worth noting", "here's the thing", "the reality is", "level up", "move the needle", "bridges the gap"

**Filler openers (never, in any context):** "Quick question", "Quick thought", "Curious,", "Just checking in", "Just following up", "Bumping this", "Wanted to circle back", "Hope you're doing well", "Hope this finds you well", "I wanted to reach out", "Thought I'd reach out", "Any thoughts on this?", "Have you had a chance to...", "Did you get a chance to...", "Looping back on this", "Touching base", "Friendly reminder", "As I mentioned", "Per my last email", "Excited to", "Looking forward to"

---

## Plain replacements

| Instead of | Write |
|---|---|
| utilize | use |
| facilitate | help |
| optimize | improve |
| leverage | use |
| implement | build, start |
| navigate | handle |
| streamline | simplify |
| augment | add to |
| cultivate | build, grow |
| execute | do, run |

---

## Process

1. Read the draft from Step 4 line by line.
2. Flag every violation: quote the line, name the rule broken.
3. Fix each one.
4. **Voice check:** Re-read the cleaned version as a whole. Does it still sound like a person with a point of view, or did the cleanup turn it into a sterile document? If a fix killed the personality of a sentence, find an alternative fix that removes the AI pattern but keeps the energy.
5. Output the clean version AND a changelog of what you fixed and why.

---

## Output format

```
## Violations found

| Line | Rule | Fix |
|---|---|---|
| "quoted text" | Rule name (#N) | → "fixed text" |
| ... | ... | ... |

## Voice check
[Pass — still sounds like a person / Fail — restored X because cleanup flattened it]

## Clean version
[Full post]

## Changelog
[Summary of all changes]
```

---

## After Step 5

Show the final post. Ask if the user wants to:
- Push to Typefully as a draft (use the typefully skill)
- Adapt for Twitter/X (Step 6 in SKILL.md)
- Adapt for other platforms
- Edit further
