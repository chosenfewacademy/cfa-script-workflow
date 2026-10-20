# cfa-script-workflow
CFA Script Generation Workflow — a single, fully self-contained HTML tool (`CFA_Script_Workflow.html`;
copy in `exports/CFA_Script_Workflow_Standalone.html`). Open it in a browser; no build step and no
external code, fonts, or libraries are loaded. Everything (CSS, JS, jsPDF, Marcus/Jordan reference images)
is inline, and any change must keep it that way.

## Flow
1. **Pick a concept** (+ optional Creative Dials) → 2. **Grok writes the script** (xAI `grok-4.7`: an education-first plan (core concept, mechanics, terms, misconception, analogy, accuracy check, word budget) → streamed draft → fact-check + critique-and-revise polish → length fit to 650–900 words if needed; set Writing Passes to "single pass" for a faster draft) → 3. **Review/edit** →
4. **Segment** into numbered 4–6 s beats (`grok-4.3`) → 5. **Voiceover** with ElevenLabs (Young Jamal voice;
the `/with-timestamps` endpoint also times every beat; download the beat timings as `.srt`) →
6. **Scenes**: Grok tags each beat IMAGE/VIDEO and writes prompts; generate images on fal.ai (Kling o1 /
Gemini 3 Pro with the Marcus/Jordan references, Nano Banana for character-less concept shots; or
**⚡ Generate all remaining images** 3 at a time) and videos (Kling v1.6 / Veo 3.1; clip length auto-picked from
the beat's narration time); optional GPT Image text fix → 7. **Export** (manifest, PDF, assets).

## Keys and spend
Open ⚙ Settings and paste keys for xAI, fal.ai, ElevenLabs and (optionally) OpenAI. Keys are kept in
`sessionStorage` only (cleared when the tab closes) and are never written into the file. Settings shows
tracked spend: fal/GPT against an optional budget, Grok (from xAI's per-call `cost_in_usd_ticks`, or
token pricing as a fallback), and an ElevenLabs list-price estimate.

## Tests
See `tests/README.md`. `tests/cfa-adversarial-mock-test.py` is a free, fully mocked browser regression suite;
the `.mjs` scripts are live, paid endpoint checks.
