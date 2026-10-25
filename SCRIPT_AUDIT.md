# Script audit — v02, v11, v23 (round 5, Oct 24 2026)

Judge: grok-4.3, 3 seeds, 11 criteria (judge.py). Old = r1_old prose scripts. r3 = PR #38 prompts. r5 = PR #39 (dialogue-mode lint fix + RHYTHM & FOCUS).

| Ep | Old mean | r3 mean | r5 mean |
|---|---|---|---|
| v02 | 7.61 | 4.85 | **8.24** |
| v11 | 7.76 | 7.06 | **7.82** |
| v23 | 8.06 | 7.70 | 7.76 |

r5 vs Old, per criterion (✔ = beats, = tie, ✘ = behind):
- v02: flow 7.67/7.33 ✔ · cohesion 8.33/8.33 = · newcomer 9.0/8.67 ✔ · hook 7.67/6.33 ✔ · accuracy 9.0/8.67 ✔ · grounding 9.0/9.0 = · continuity 8.0/8.33 ✘ · realism 8.33/6.67 ✔ · non_generic 8.0/7.67 ✔ · pull 7.67/6.67 ✔ · human 8.0/6.0 ✔
- v11: flow 7.33/7.67 ✘ · cohesion 8.33/8.0 ✔ · newcomer 8.67/8.33 ✔ · hook 6.67/7.33 ✘ · accuracy 9.33/9.33 = · grounding 8.33/8.67 ✘ · continuity 8.0/8.0 = · realism 7.33/7.0 ✔ · non_generic 8.0/8.0 = · pull 7.0/6.67 ✔ · human 7.0/6.33 ✔
- v23: flow 7.67/8.0 ✘ · cohesion 7.33/8.67 ✘ · newcomer 8.67/9.0 ✘ · hook 5.67/7.0 ✘ · accuracy 9.0/9.67 ✘ · grounding 9.0/9.0 = · continuity 8.0/9.0 ✘ · realism 8.0/7.0 ✔ · non_generic 7.67/8.0 ✘ · pull 6.67/7.33 ✘ · human 7.67/6.0 ✔

**Goal "beat old on every criterion": NOT met.** v02 is ahead on 8 of 11 (2 ties). v11 is mixed. v23 is still behind on hook, cohesion and continuity. Human-likeness and dialogue realism now beat the old scripts on all three.

## Line-level findings (automatic checks)
| Run | Ep | Avg character words | Clipped (<7 words) | Narrator % | Narrator first person | "crypto" |
|---|---|---|---|---|---|---|
| r3 | v02/v11/v23 | 9.1/7.8/8.6 | 23/24/24% | 0/5/6 | 0 | 0 |
| r5 | v02/v11/v23 | 10.0/9.8/10.9 | 5/17/11% | 5/5/3 | 0 | 0 |

Root cause of the r3 regression: the prose lint ("too few 2–4 word sentences", "paragraphs similar length") also ran in dialogue mode. Each fix pass chopped the lines into fragments, and the bank-transfer B-plot crowded out the lesson. Fixed in #39.

Other issues found by hand:
- r3 v02 l.37 "Lehman Brothers filed September 15, 2008…" — a fact dump with no reaction.
- r4 v11 "MARCUS: The paper came out… / MARCUS: The network started…" — stacked single-fact lines.
- Endings: v02 still closes on the episode's central question asked as a bare question ("Why do some people trust Bitcoin more than banks?") instead of a payoff line.
- Accuracy: no factual errors found against DIGITAL_ASSETS_PRIMER (Oct 31 2008 whitepaper, Jan 3 2009 genesis block / The Times headline, Ethereum Jul 30 2015, proof of stake Sep 2022).
- Narrator purity: no narrator first person, no narrator taking part in the action, 0–6% narration.

## Before / after (v02 opening)
Before (r3):
> JORDAN: Why won't it just send? / DEE: Five o'clock. They cancel the parts order. / JORDAN: Daily limit. I already hit send twice. / DEE: Stop hitting it. They only take a bank transfer.

After (r5):
> DEE: The bank just put the payment on hold again. / JORDAN: Why does it still have to go through them? / DEE: Han wants the money by five, or the pads stay in his warehouse. / JORDAN: Brake pads and chains. We can't open without those.

## Next
A HOOK & PULL rule (a concrete loss in line 1, plant an object early and pay it off at the end, continuity) was drafted. Its test run hung at the research step, so it is not merged. It targets v23's hook and continuity gaps.

# Rounds 6–7 (Oct 24 2026, 9:00–10:00 PM ET)
- **r6 (PR #41, merged).** Research step: 120 s timeout with fallback to the verified primer. Added the HOOK & PULL and ENDING rules and a lint that flags a script ending on a question.
  - Scores: v02 5.94, v11 7.61, v23 **7.97** (hook 6.67, cohesion 8.33, story_pull 7.33, accuracy 9.33).
  - v02 ending, before: "…Why do some people trust Bitcoin more than banks?"
  - v02 ending, after: "We waited all afternoon for their yes. Bitcoin was built so a payment would not have to."
- **r7 (curiosity-gap opener rule, NOT merged).** Scores: v02 7.12, v11 7.03, v23 6.79. Worse on all three.
  - Openers did get sharper, e.g. "Twelve random words just filled my phone screen."
  - But dialogue realism and human-likeness dropped.

**Best scores so far vs old scripts:**

| Episode | Old scripts | Best new score | Round |
|---|---|---|---|
| v02 | 7.61 | 8.24 | r5 |
| v11 | 7.76 | 7.82 | r5 |
| v23 | 8.06 | 7.97 | r6 |

**Run-to-run noise.** The same prompts swing up to ±2.3 points on one episode (v02: 8.24 in r5, 5.94 in r6). One run per episode cannot show whether a prompt change helped. The next step is about 3 runs per episode per variant, about $3 each.

**Still behind the old scripts:** hook (all three) and v23 continuity. "Beat on every criterion" is not met.

# Repeated blind testing (Oct 24 2026, 9:30–11:00 PM ET)
Method: 3 generations per episode per version, 18 scripts judged blind under shuffled names (grok-4.3, 3 seeds × 11 criteria each). Baseline = main after #41 (r6 + 2 new runs). Variant = STAKES IN LINE 1 + CALLBACK to a prior-episode object + GROUNDING with 2 dated primer facts.

| Ep | Ver | mean ± sd | hook | cohesion | continuity | grounding | dialogue_realism | human_likeness | story_pull | flow |
|---|---|---|---|---|---|---|---|---|---|---|
| v02 | baseline | 6.14 ± 0.55 | 6.22 | 5.56 | 6.56 | 7.89 | 5.11 | 4.44 | 4.33 | 5.44 |
| v02 | variant | 7.64 ± 0.40 | 6.56 | 7.56 | 8.22 | 8.78 | 7.22 | 6.78 | 6.67 | 6.89 |
| v02 | old | 7.61 | | | | | | | | |
| v11 | baseline | 7.17 ± 0.46 | 5.00 | 7.33 | 7.67 | 8.55 | 6.56 | 5.89 | 6.67 | 6.44 |
| v11 | variant | 6.89 ± 0.49 | 6.44 | 6.89 | 7.45 | 8.44 | 5.78 | 4.78 | 6.44 | 6.00 |
| v11 | old | 7.76 | | | | | | | | |
| v23 | baseline | 7.30 ± 0.34 | 5.78 | 7.67 | 7.56 | 8.56 | 6.33 | 5.44 | 7.00 | 6.78 |
| v23 | variant | 6.95 ± 1.44 | 5.67 | 7.11 | 6.89 | 8.00 | 6.33 | 5.78 | 6.11 | 6.55 |
| v23 | old | 8.06 | | | | | | | | |
Baseline overall 6.87 ± 0.69
Variant overall 7.16 ± 0.97

**Verdict: variant NOT merged.** Overall +0.29 is within noise (sd 0.7–1.0, n=9). It helps v02 a lot (+1.5, about 3× its spread; continuity +1.7, realism +2.1). It slightly hurts v11 and v23 (human_likeness −1.1 on v11; v23 spread 1.44). Diff saved for a v02-style episode-specific trial: cfa-scripts-ab/variant_stakes_callback.diff.

**Against the old scripts (mean of 3 runs):** none of the three beats the old scripts. v02 variant 7.64 vs 7.61 is about a tie. v11 7.17 vs 7.76. v23 7.30 vs 8.06. The single-run highs earlier (8.24 / 7.97) were noise. Weakest criteria in every arm: hook (5.0–6.6) and human_likeness (4.4–6.8).

Opening lines, before (baseline): "DEE: Supplier texted. Paid by five, or the order dies." / "JORDAN: Bank app still says pending. Since yesterday afternoon."
Opening lines, after (variant): "DEE: The supplier just bounced two hundred dollars." / "JORDAN: Bounced? Those brake parts are due tomorrow morning."

# Hybrid narration structure (Oct 24 2026, 10:00–11:15 PM ET)
Bill gives a narrated cold open of 40–70 words (concrete stake), characters carry the scenes, and Bill adds 1–2 sentence bridges plus a closing reflection that calls back to the opening. Target 25–35% narration. Method: 3 generations per episode, judged blind (grok-4.3, 3 seeds × 11 criteria). Baseline = the 9 sparse-mode runs above.

| Ep | Version | mean ± sd | hook | cohesion | continuity | grounding | dialogue_realism | human_likeness | story_pull | flow |
|---|---|---|---|---|---|---|---|---|---|---|
| v02 | baseline (sparse) | 6.14 ± 0.55 | 6.22 | 5.56 | 6.56 | 7.89 | 5.11 | 4.44 | 4.33 | 5.44 |
| v02 | HYBRID | 7.19 ± 0.59 | 6.89 | 7.44 | 7.56 | 8.67 | 6.11 | 5.22 | 5.89 | 6.67 |
| v02 | old (prose) | 7.61 | | | | | | | | |
| v11 | baseline (sparse) | 7.17 ± 0.46 | 5.00 | 7.33 | 7.67 | 8.55 | 6.56 | 5.89 | 6.67 | 6.44 |
| v11 | HYBRID | 7.63 ± 0.20 | 6.00 | 8.22 | 7.89 | 8.89 | 7.22 | 6.56 | 7.00 | 7.22 |
| v11 | old (prose) | 7.76 | | | | | | | | |
| v23 | baseline (sparse) | 7.30 ± 0.34 | 5.78 | 7.67 | 7.56 | 8.56 | 6.33 | 5.44 | 7.00 | 6.78 |
| v23 | HYBRID | 8.07 ± 0.13 | 7.78 | 8.44 | 8.22 | 8.89 | 7.22 | 6.67 | 7.67 | 7.78 |
| v23 | old (prose) | 8.06 | | | | | | | | |

Baseline overall 6.87 ± 0.69

Hybrid overall 7.63 ± 0.51

**Verdict: MERGED as the default** (setting: Narration = Hybrid | Sparse).
- Hybrid beats the baseline on all 3 episodes and on all 8 criteria above: overall +0.76 (7.63 ± 0.51 vs 6.87 ± 0.69, n=9 each, about 3× the standard error).
- v23 ties the old prose (8.07 vs 8.06) and v11 is close (7.63 vs 7.76). v02 is still 0.42 behind.
- Human-likeness stays the weakest criterion (5.2–6.7).
- Caveat: the hybrid and baseline batches were judged in separate sessions of the same blind setup.

Line checks (9 hybrid scripts):
- Narration landed at 17–28%, so the model under-narrates against the 25–35% target.
- The cold open was the NARRATOR line in all 9, at 13–59 words.
- No narrator first person; "crypto" ×0.

Excerpt (v23, run h2):
> NARRATOR: At the Spoke & Chain back office, twelve words filled the shop laptop, and the screenshot button sat grey under a warning Jordan could not dismiss. The parts invoice beside the keyboard had five o'clock circled in red. …
> JORDAN: Dee, hold on. Last night I wrote up the private key. Now it wants twelve words.
> …
> JORDAN: Those twelve words on the card are what I protect. A dead laptop I can replace.
> NARRATOR: Upstairs, the fireproof box sat closed on Marcus's shelf. Downstairs, the twelve words were gone from the shop laptop, and the supplier receipt still lay warm beside the green notebook.

Shot plan: NARRATOR beats get animated wide or establishing shots (slow push-in, pan or drift, people moving). The renderer already uses gentler motion, dissolves and the quiet "Narr" caption style for these beats. The hook guard is skipped in Hybrid so it does not chop the narrated cold open.
