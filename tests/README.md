# CFA Script Workflow — Test Scripts

Live integration tests for every generation endpoint the workflow uses. Each
script mirrors the exact request body the workflow's HTML sends, so a passing
test means Chris won't hit a schema mismatch or dead endpoint during real work.

> **Run location:** these scripts expect to run from the **CFA-Script-Workflow
> root** (where `exports/CFA_Script_Workflow_Standalone.html` and `test-output/`
> live as siblings). Copy them up one level, or adjust the `__dirname` paths,
> before running.

## Scripts

| Script | What it tests | Approx cost |
|---|---|---|
| `cfa-pipeline-test.mjs` | Script generation + segmentation pipeline (Anthropic) | ~free |
| `cfa-comprehensive-test.mjs` | Full Kling image + video regression (12 cases) | ~$3.30 |
| `cfa-new-endpoints-test.mjs` | Gemini 3 Pro, Imagen 4 Ultra, Veo 3.1 smoke test | ~$0.52 |
| `cfa-gpt-image-test.mjs` | GPT Image text-correction (`/v1/images/edits`) across model strings | ~$0.20 |
| `cfa-live-sim.mjs` | End-to-end simulation of a full scene run | varies |

## Usage

```bash
# Anthropic-only pipeline test
node cfa-pipeline-test.mjs YOUR_ANTHROPIC_KEY

# fal.ai endpoint tests (pass the fal.ai key)
node cfa-new-endpoints-test.mjs YOUR_FAL_KEY
node cfa-comprehensive-test.mjs YOUR_FAL_KEY

# OpenAI GPT Image enhancement test
node cfa-gpt-image-test.mjs YOUR_OPENAI_KEY
```

Keys are passed as CLI arguments only — never hard-coded. Generated assets are
saved under `test-output/` (gitignored).

## Confirmed working endpoints (last verified)

- **Kling o1** image — `fal-ai/kling-image/o1`
- **Kling v1.6 Pro** video — `fal-ai/kling-video/v1.6/pro/image-to-video`
- **Gemini 3 Pro** image — `fal-ai/gemini-3-pro-image-preview/edit`
- **Imagen 4 Ultra** image — `fal-ai/imagen4/preview/ultra`
- **Veo 3.1** video — `fal-ai/veo3.1/image-to-video`
- **GPT Image 2** text fix — `https://api.openai.com/v1/images/edits` (model `gpt-image-2`)
