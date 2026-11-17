# v8 locked style (approved Oct 29, 2026)

v8 is the approved standard: "the best version we've had, let's lock this in". Every render must match it. `tools/render/baseline_check.py` checks a report against it, and `tools/render/baseline_v8_report.json` holds the reference report.

## Look
- 3D Pixar-style characters. The narrator stays outside the story, and mouths stay closed.
- One character per shot, with exactly one phone. No captions, overlays or on-screen writing.
- **Cinema look** (`CINEMA_LOOK_RULE`): "medium close-up, warm rim light, high contrast, shallow depth of field, character tack-sharp."
- **Crisp props** (`CRISP_PROPS_RULE`): "Sharp, detailed foreground objects, crisp edges on props; background softly blurred."
- Edges are never smeared. The edge gate allows depth-of-field falloff but fails on a blurry band with a seam.

## Pictures
- **Stills:** Kling o1 at `resolution: '2K'` (2720×1536), at the same price as 1K ($0.028). The renderer scales them *down* to 1080p with lanczos. The sharpness gate fails any still that is upscaled more than 1.5×.
- **Sharpening:** `,unsharp=3:3:0.9:3:3:0,cas=0.35` is the default. You can override it with `CFA_SHARPEN_VF`.
- **Bitrate:** the final file must be at least 8 Mbps (`FINAL_MIN_KBPS=8000`). If it falls short, it is re-encoded at 10M.

## Motion
- **Stills:** a linear (ffmpeg) zoom or pan with no depth warp. The move aims at what the narration names (`narration_aim`). `CFA_AIMS` can pin the aims.
- **Shots:** 2–5 s each; the v8 median is about 4.3 s.
- **Action shots:** one Hailuo i2v clip with a single subtle action. No new props and no second phone.
- **Upscaling:** each accepted i2v clip is upscaled by `fal-ai/video-upscaler`.
  - The upscaler always works from the **raw** clip, at the exact factor needed to reach 1080p.
  - It costs about $0.25 per 5 s clip. This is already included in `i2v_cost()`, so it counts toward the estimate and the cap.
  - Set `CFA_VIDEO_UPSCALE=0` to turn it off. If the upscaler fails, the raw clip is kept.

## Script fidelity
- Each shot's **action, object and emotion** must match its own line.
- **Tool:** the shot audit asks `action_match` and `object_match` and uses the emotion score. If any of them misses, the still is regenerated with a fix note.
- **Renderer:** i2v clips are checked, and a miss triggers a retry within the cap. The report's `motion_gate.fidelity` lists stills that do not match; those fail the gate.

## Gates (all must pass)
edge, hole, sharpness (kbps ≥ 8000 and upscale ≤ 1.5×), text, motion, similarity, distortion, props (one phone), fidelity.

## v8 reference
- 20.88 s, 5 shots (3.12, 3.38, 4.44, 4.91, 5.03 s).
- Median shot 4.33 s; motion 7.27 px/s.
- 1 Hailuo clip; 10.1 Mbps.

## Fast Cuts (opt-in style, Nov 16, 2026)
v8 stays the default. **⚙ Settings → Episode format → Cut style → "Fast Cuts"** switches one episode to the editing borrowed from the top-ranked direct-response ad the team studied (camera cuts and scene changes only; **no captions**):
- **Tool:** on entering Scene Generation (Step 6) the script is split into 1–3 s phrase shots (still cap 3 s, minimum 1 s, emotional lines too). Every shot prompt adds a FAST CUTS note: show literally and only what those words describe, one readable subject, the new place when the story moves, no on-screen words. The export bundle carries `cutStyle: "fast_cuts"`.
- **Renderer:** `cutStyle` from the bundle (or `--cut-style v8|fast_cuts`) picks the edit. Fast Cuts uses a 1 s minimum hold, no drift/punch-in re-angles, hard cuts only, and tighter pauses (0.3 s between beats and 0.25 s between sentences, unless you set them on the command line). Any still over 3 s is split at word gaps onto the beat's `cutaways` (extra stills), with each part getting its own words as its line. With no cutaway left it falls back to an aimed punch-in, and the report flags it as `fast_reframe`. Lip-sync shots are never split, and clips only split onto cutaways.
- **Gate:** `motion_gate.fast_cuts` fails if the median shot is over 3 s or any still is over 3.25 s. The report records `cut_style`.
- Everything else is v8: 2K stills, crisp sharpen, ≥ 8 Mbps, aimed linear moves, one character per shot, one phone, and no text.
