"""Quality fixes: gamma cap, encode settings, sharpen + upscale gate, hole reframe (v6 feedback)."""
import render, inspect
fails = []
def check(n, c, d=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else d)
    c or fails.append(n)
g = render.lift_filter(37)
check("gamma lift capped at 1.35", "gamma=1.35" in g, g)
check("bright still not lifted", render.lift_filter(120) == "")
check("final encode crf 14 slow >= 8M", render.FINAL_CRF == 14 and render.FINAL_PRESET == "slow" and render.FINAL_MINRATE == "8M")
src = inspect.getsource(render.encode_video)
check("encode_video uses FINAL_* and INTER_CRF", "FINAL_CRF" in src and "FINAL_MINRATE" in src and "INTER_CRF" in src)
check("intermediates near-lossless", render.INTER_CRF <= 10)
check("sharpen + lanczos in shot fit", "unsharp" in render.SHARPEN_VF and "lanczos" in inspect.getsource(render.render_shot))
check("upscale limit set", 1.5 <= render.UPSCALE_MAX <= 1.8)
check("hole reframes with punch-in and reports a gate", "punch-in reframe" in inspect.getsource(render) and 'gate["holes"]' in inspect.getsource(render))
check("cover crops keep headroom (top-biased)", 0 < render.HEADROOM_Y < 0.5 and "HEADROOM_Y" in inspect.getsource(render.render_shot) and "HEADROOM_Y" in inspect.getsource(render.fill_graph))
check("bitrate floor re-encode present", "FINAL_MIN_KBPS" in inspect.getsource(render.encode_video))
print("%d failure(s)" % len(fails)); raise SystemExit(1 if fails else 0)
