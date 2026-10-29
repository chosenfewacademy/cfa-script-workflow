"""Phone/prop checks: dense motion-clip sampling, >1 phone, stacked/fused device, vanishing phone (v6 shots 2 and 5)."""
import render
fails = []
def check(n, c, d=""):
    print(("PASS " if c else "FAIL ") + n, "" if c else d)
    c or fails.append(n)
V = render.prop_verdict
check("one phone throughout passes", V([{"phones": 1}] * 6, 1)["ok"])
check("no phone anywhere passes", V([{"phones": 0}] * 6, 0)["ok"])
check("two phones fails", not V([{"phones": 1}, {"phones": 2}], 1)["ok"])
check("stacked device fails", not V([{"phones": 1, "stacked": True}], 1)["ok"])
r = V([{"phones": 1}] * 4 + [{"phones": 0}] * 2, 1)
check("phone vanishing mid-clip fails", not r["ok"] and "vanishes" in r["why"][-1], r)
check("still had a phone, clip never shows it -> vanish", not V([{"phones": 0}] * 3, 1)["ok"])
seen = []
def ask(tt):
    seen.append(len(tt)); return {"frames": [{"phones": 1}] * len(tt)}
v = render.prop_check("x.mp4", "k", "video", ask=ask, expect_phone=1)
check("dense sampling ~2 fps in batches", sum(seen) == 6 and max(seen) <= render.PROP_BATCH and render.PROP_EVERY_S == 0.5 and render.PROP_WIDTH == 1024, (seen,))
check("i2v system prompt asks for stacked/fused", "stacked" in render.PROP_CHECK_SYS and "fused" in render.PROP_CHECK_SYS)
sv = render.prop_check("x.png", "k", "image", ask=lambda tt: {"phones": 2, "stacked": True})
check("still mode: stacked phones fail", not sv["ok"] and len(sv["why"]) == 2, sv)
check("still mode prompt uses zoomed crops", "zoomed" in render.PROP_STILL_SYS)
print("%d failure(s)" % len(fails)); raise SystemExit(1 if fails else 0)
