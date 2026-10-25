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
