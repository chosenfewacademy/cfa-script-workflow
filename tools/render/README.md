# CFA final-edit renderer

Turns the **Export for final edit** bundle from `CFA_Script_Workflow.html` (Step 6, completion screen)
into a finished, edited MP4 + thumbnail. Grok plans the edit; ffmpeg renders it. No Premiere.

## Workflow
1. Finish all scenes in the tool → click **🎬 Export for final edit**. It downloads
   `CFA_FinalEdit_EPxx_<title>.zip` (every fal image/clip is fetched into the zip, so expiring links don't matter).
   If the page was reloaded since the voiceover was made, it asks you to pick the voiceover MP3 from Step 5.
2. Send the zip to Grok Bot in chat (or run the command below on any Linux box with ffmpeg).
3. Get back `final.mp4` + `thumbnail.jpg`.

```bash
python3 tools/render/render.py CFA_FinalEdit_EP07_....zip -o out/                    # 1920x1080
python3 tools/render/render.py bundle.zip -o out_v/ --vertical                        # 1080x1920 (Shorts/Reels)
python3 tools/render/render.py bundle.zip -o out/ --music bed.mp3                     # music ducked under the voice
#  --no-grok  deterministic edit only   --caption-style bold_pop|clean_lower|boxed
#  --no-title / --no-end-card            --model grok-4.3   --keep-work
```
`XAI_API_KEY` comes from the environment (or `--keys-env FILE`, default `/home/box/secrets/cfa_keys.env`). Keys are never written to output.

## What it does
| Stage | Detail |
|---|---|
| Unpack | zip (or unpacked folder, or JSON `{bundle, files:{name: base64}}`); rejects unsafe paths |
| Timing | Beat `start/end` from the ElevenLabs `/with-timestamps` word list. Missing beats are re-aligned from the words, else interpolated by word count. Cuts sit in the pause before each beat; the last shot ends exactly at the end of the voice |
| EDL | `grok-4.3`, `response_format: json_object`: per-beat motion (zoom/pan/static), intensity, transition (cut/dissolve/fadeblack/wipe/slide…), emphasis words, caption style, title/end card, thumbnail pick |
| Validation | Durations are **always** taken from the voice (Grok's are ignored); unknown motions/transitions coerced; transitions capped at 40% of neighbouring shots; video clips forced static; on-screen text rewritten so it says "digital assets", never "crypto". Unusable output → retry once → deterministic fallback edit |
| Shots | Beats are merged into shots of at least `--min-hold` (3.75s) each, preferring a beat's video clip. Stills: slow, subtle Ken Burns (≤7% zoom) on a 2× canvas. Clips: cover-crop, slowed up to 1.5× then last-frame hold; clip audio dropped |
| Pacing | Natural silences are spliced into the voice using the timestamps (`--beat-pause` 0.6s between beats, `--sentence-pause` 0.45s between sentences); words, captions and cuts shift to match. Crossfades 0.8–1.0s at mid-pause |
| Assembly | `xfade` chain at the cut times, burned-in ASS phrase captions (5–8 words, broken at punctuation, held ~0.8s longer with a 200ms fade, no per-word highlight, never spanning a beat), title card, end card |
| Audio | Optional music: −16 dB, looped, faded, `sidechaincompress` keyed by the voice, `amix`. Two-pass `loudnorm` to **−14 LUFS / −1 dBTP**, AAC 192k 48 kHz |
| Output | `final.mp4` (H.264 high, CRF 18, 30 fps, faststart), `thumbnail.jpg` (1280×720 or 720×1280, caption-free frame + title), `edl.json`, `captions.ass`, `report.json` (duration vs voice, LUFS, caption cues, EDL source/problems) |

Output length equals the voiceover length (title and end cards overlay picture, they don't add time).

## Test
`python3 tools/render/test_render.py` — $0, synthetic bundle, renders 16:9 and 9:16 with music, checks duration == voice,
audio present, −14 LUFS ±1, every word captioned at its spoken time, no "crypto" on screen, EDL validator/fallback.

## Limits
- Vertical is a centre crop of 16:9 art, so wide two-character shots lose the edges (generate 9:16 art for Shorts).
- The narration script already says "digital assets" (writer rule). If a "crypto" slips through, captions get a grammar-aware swap ("crypto is" → "digital assets are", "a crypto" → "a digital asset"); the audio still says the original word.
- Merging beats into longer shots means some generated images are not used.
- Captions use Montserrat/Anton from the box's fonts (falls back to the system sans elsewhere).
- Render time ≈ 1.5× real time for 1080p on 8 cores (a 6-minute episode ≈ 8–10 minutes).
