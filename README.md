# CFA Script Workflow

Single-file browser tool: `CFA_Script_Workflow.html` (mirrored to `exports/CFA_Script_Workflow_Standalone.html`).
Tests: `tests/`. Finished-edit renderer (bundle → edited MP4 with ffmpeg + Grok edit plan): `tools/render/`.

## Reviewer feedback
Every step has a **💬 Feedback** button (bottom right) with a 1–5 rating, a comment and an optional shot or line. Feedback is saved on the render service (Settings → render URL + access key).
- **Fix this episode**: the note is added to that step's prompts and the step is regenerated straight away (script revised, voiceover remade, shot regenerated, or a render re-edit). If there's no output yet, the note is kept for the next time the step runs.
- **Suggest a change to the tool**: queued in `inbox.jsonl` for the developer.
- Accepted suggestions become the **feedback memory**, which is added to the script, director and image prompts.
- Each item shows *Submitted*, *In progress* or *Ready*. When one is ready, a **Changes ready** banner, a badge and a browser notification appear.
