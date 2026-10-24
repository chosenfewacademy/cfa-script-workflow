# CFA Script Workflow — Test Scripts

Live integration tests for every generation endpoint the workflow uses. Each
script mirrors the exact request body the workflow's HTML sends, so a passing
test means Chris won't hit a schema mismatch or dead endpoint during real work.

> **Run location:** run from `tests/`. Scripts look for
> `exports/CFA_Script_Workflow_Standalone.html` in `tests/` or the repo root
> (the repo now ships `exports/`). Output goes to `tests/test-output/`.

## Scripts

| Script | What it tests | Approx cost |
|---|---|---|
| `cfa-pipeline-test.mjs` | Character upload → fal storage → Kling o1 with `image_urls` (needs the **fal** key) | ~$0.04 |
| `cfa-comprehensive-test.mjs` | Full Kling image + video regression (12 cases) | ~$3.30 |
| `cfa-new-endpoints-test.mjs` | Gemini 3 Pro, Nano Banana, Veo 3.1 smoke test | ~$0.52 |
| `cfa-gpt-image-test.mjs` | GPT Image text-correction (`/v1/images/edits`) across model strings | ~$0.20 |
| `cfa-live-sim.mjs` | End-to-end simulation of a full scene run | varies |
| `cfa-character-isolation-test.mjs` | Character isolation: Marcus/Jordan refs used correctly, secondary chars distinct, NONE→Nano Banana (6 live generations) | ~$0.60 |
| `cfa-grok-pipeline-test.mjs` | Full Grok (xAI) pipeline: script (grok-4.7) → segment → classify → prompts (grok-4.3), no-consec enforcement, secondary-char note injection (9 checks) | ~$0.03 |
| `cfa-adversarial-mock-test.py` | Headless browser test of the real HTML with **every API mocked** (Playwright): API errors (401/429/500/network/mid-stream), aborts, rapid clicks, XSS, huge/empty input, scene switching mid-generation, corrupt/old saved state, full storage, VO timestamps + SRT, auto video length, Generate-all batch, Export-for-final-edit zip | $0 |

## Usage

```bash
# Character upload + Kling o1 pipeline test
node cfa-pipeline-test.mjs YOUR_FAL_KEY

# Full Grok pipeline + secondary-char note injection (9 checks)
XAI_API_KEY=xai-... node cfa-grok-pipeline-test.mjs

# Free, fully mocked browser test (pip install playwright && playwright install chromium)
python3 cfa-adversarial-mock-test.py            # all groups, or e.g.: python3 cfa-adversarial-mock-test.py fal batch

# fal.ai endpoint tests (pass the fal.ai key)
node cfa-new-endpoints-test.mjs YOUR_FAL_KEY
node cfa-comprehensive-test.mjs YOUR_FAL_KEY

# Character isolation live test — 6 real generations, visual inspection required
node cfa-character-isolation-test.mjs YOUR_FAL_KEY

# OpenAI GPT Image enhancement test
node cfa-gpt-image-test.mjs YOUR_OPENAI_KEY
```

Keys are passed as CLI arguments or environment variables only — never hard-coded. Generated assets are
saved under `test-output/` (gitignored).

## Confirmed working endpoints (last verified)

- **Kling o1** image — `fal-ai/kling-image/o1`
- **Kling v1.6 Pro** video — `fal-ai/kling-video/v1.6/pro/image-to-video`
- **Gemini 3 Pro** image — `fal-ai/gemini-3-pro-image-preview/edit`
- **Nano Banana** text-only image — `fal-ai/nano-banana` (replaces `fal-ai/imagen4`, retired by fal 2026-06-30)
- **Veo 3.1** video — `fal-ai/veo3.1/image-to-video`
- **Grok** text — `https://api.x.ai/v1/chat/completions` (`grok-4.7` writer, `grok-4.3` fast)
- **ElevenLabs** voiceover — `POST /v1/text-to-speech/{voice}/with-timestamps` (audio + character timing)
- **GPT Image 2** text fix — `https://api.openai.com/v1/images/edits` (model `gpt-image-2`)

Renderer test (no API spend): `python3 ../tools/render/test_render.py` — see `tools/render/README.md`.
