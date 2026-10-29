# v8 locked style (approved Oct 29, 2026)

v8 is the approved standard: "the best version we've had, let's lock this in". Every render must match it. `tools/render/baseline_check.py` checks a report against it, and `tools/render/baseline_v8_report.json` holds the reference report.

## Look
- 3D Pixar-style characters. The narrator stays outside the story, and mouths stay closed.
- One character per shot, with exactly one phone. No captions, overlays or on-screen writing.
- **Cinema look** (`CINEMA_LOOK_RULE`):
  - medium close-up;
  - warm rim light on hair and shoulders;
  - high contrast, with shadows that are deep but readable;
  - shallow depth of field.
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
