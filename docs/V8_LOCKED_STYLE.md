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
**unique shots**, edge, hole, sharpness (kbps ≥ 8000 and upscale ≤ 1.5×), text, motion, similarity, distortion, props (one phone), fidelity.

## v8 reference
- 20.88 s, 5 shots (3.12, 3.38, 4.44, 4.91, 5.03 s).
- Median shot 4.33 s; motion 7.27 px/s.
- 1 Hailuo clip; 10.1 Mbps.

## Fast Cuts (opt-in style, Nov 16, 2026)
v8 stays the default. **⚙ Settings → Episode format → Cut style → "Fast Cuts"** switches one episode to the editing borrowed from the top-ranked direct-response ad the team studied (camera cuts and scene changes only; **no captions**):
- **Tool:** on entering Scene Generation (Step 6) the script is split into 1–3 s phrase shots (still cap 3 s, minimum 1 s, emotional lines too). Every shot prompt adds a FAST CUTS note: show literally and only what those words describe, one readable subject, the new place when the story moves, no on-screen words. The export bundle carries `cutStyle: "fast_cuts"`.
- **Renderer:** `cutStyle` from the bundle (or `--cut-style v8|fast_cuts`) picks the edit. Fast Cuts uses a 1 s minimum hold, no drift/punch-in re-angles, hard cuts only, and tighter pauses (0.3 s between beats and 0.25 s between sentences, unless you set them on the command line). Any still over 3 s is split at word gaps onto the beat's `cutaways` (extra stills), with each part getting its own words as its line. With no distinct cutaway left the still stays one shot and the Fast Cuts gate fails, asking for more distinct stills (nothing is reframed or re-shown). Lip-sync shots are never split, and clips only split onto cutaways.
- **Gate:** `motion_gate.fast_cuts` fails if the median shot is over 3 s or any still is over 3.25 s. The report records `cut_style`.
- Everything else is v8: 2K stills, crisp sharpen, ≥ 8 Mbps, aimed linear moves, one character per shot, one phone, and no text.

## Unique shots (both styles, Nov 16, 2026)
Owner: "Don't reuse the same shot over and over again, each shot should be unique." Applies to v8 **and** Fast Cuts.
- **Tool:** every shot prompt (director and per-shot) demands a frame no other shot has: change at least two of camera angle, shot size/framing, subject and location; never a repeat, re-crop, punch-in, alternate take or re-angle. A director shot list that repeats a frame (same shot size + place + subject, word overlap ≥ 0.7) is flagged and that shot is re-prompted, naming the shot it repeated. A still is never recycled as another shot's clip start frame (no "Set as Start Frame", no auto start frame, no last-frame continuation, enhanced stills stay on their own shot); a clip that needs an opening frame gets its own through the normal priced, budget-gated generation. Export/Send **refuses** (no override) when any shot has no picture of its own, two shots share identical bytes (SHA-256), or two shots (all pairs, stills and clip frames at 5/50/95 %) are near-identical (64-bit dHash distance ≤ 6), naming the colliding shots.
- **Renderer:** a hard `uniqueness` gate runs before anything is billed or rendered and again after any generated motion clip replaces a still. It fails (exit ≠ 0, `DuplicateShotError`, `report.json` → `uniqueness`) on a line or shot without its own picture, an unreadable picture, the same file bytes (SHA-256) in two shots, or any near-duplicate pair (all pairs, not just neighbours; clips sampled at 5/50/95 %): ORB feature match ≥ 30 RANSAC inliers (640×360, 800 features, ratio 0.75, 5 px), or equalised 160×90 dHash ≤ 6, or SSIM ≥ 0.90. The message names the colliding shots and media. Removed: drift/punch-in splits, same-line/neighbour fill, Fast Cuts reframe fallback, and the similarity gate's match-cut exemption. Calibration on real CFA assets: same still / upscale / animation / alternate take 51-800 inliers; unrelated shots 0-13.
