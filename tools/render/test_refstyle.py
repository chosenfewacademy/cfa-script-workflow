"""$0 checks for the reference-video style (Oct 29): linear ffmpeg moves aimed at what the line names, subtle i2v, cinema still look."""
import inspect, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render
fails = 0
def check(name, ok):
    global fails
    print(("PASS " if ok else "FAIL ") + name); fails += 0 if ok else 1
check("still motion default is ffmpeg kenburns (no depth warp)", render.STILL_MOTION == "kenburns" or os.environ.get("CFA_STILL_MOTION"))
check("moves are linear", render.LINEAR_MOVES)
ap = render.action_prompt({"one_char": "JORDAN", "line": "I screenshot them"})
check("i2v prompt: subtle, line-matched, no new props", "subtle" in ap and "no new props" in ap and "second phone" in ap)
src = inspect.getsource(render.render_shot)
check("zoom aims at narration target", '_aim' in src)
check("aim helper ignores missing key", render.narration_aim("x.png", "line", None) is None)
html = open(os.path.join(os.path.dirname(__file__), "..", "..", "CFA_Script_Workflow.html")).read()
check("still prompts carry the cinema look", all(k in html for k in ("rim light", "high contrast", "medium close-up", "shallow depth of field")) and "+CINEMA_LOOK_RULE" in html)
check("drift splits keep shots <= 4 s", render.DRIFT_MAX <= 4.0)
print("%d failure(s)" % fails)
