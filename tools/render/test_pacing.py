"""Shot pacing after the unique-shots rule (Nov 16): a still is never split into re-shown parts of itself
(no drift / punch-in parts); pacing comes from distinct stills (tool: 1 still per phrase, Fast Cuts: 1-3 s)."""
import render as R

fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else " -- " + str(info)))
    fails += 0 if ok else 1

check("drift splitting of one still is removed", not hasattr(R, "split_drift"))
check("wide -> punch-in splitting of one still is removed", not hasattr(R, "split_punch_ins"))
check("gap filling from another shot's picture is removed", not hasattr(R, "same_line_media"))
words = [["w", round(0.4 * k, 2), round(0.4 * k + 0.3, 2)] for k in range(40)]
one = R.split_fast_cuts([{"index": 1, "beats": [1], "start": 0.0, "end": 8.0, "duration": 8.0, "media": "a.png", "mediaType": "image", "motion": "zoom_in"}], words, [{"index": 1}])
check("fast cuts never re-shows a still to fill time (no cutaways -> one long shot)", len(one) == 1 and one[0]["media"] == "a.png", [(x["media"], x["duration"]) for x in one])
g = R.fast_cuts_gate(one)
check("...and the fast-cuts gate asks for more distinct stills", not g["pass"] and "add more distinct stills" in " ".join(g["fails"]), g)
two = R.split_fast_cuts([{"index": 1, "beats": [1], "start": 0.0, "end": 8.0, "duration": 8.0, "media": "a.png", "mediaType": "image"}], words, [{"index": 1, "cutaways": ["b.png"]}])
check("with one cutaway: exactly two parts, two different pictures", [x["media"] for x in two] == ["a.png", "b.png"], [x["media"] for x in two])
print("%d failed" % fails)
raise SystemExit(1 if fails else 0)
