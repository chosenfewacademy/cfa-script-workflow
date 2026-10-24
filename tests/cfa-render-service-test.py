#!/usr/bin/env python3
"""Browser end-to-end: tool page -> 🚀 Send to Grok for final edit -> upload progress -> timer/stage screen -> review
(video plays, download link, vertical re-render, re-edit with notes) against a real tools/render/service.py (renderer runs with --no-grok).
Run: CHROME=/usr/bin/google-chrome python3 tests/cfa-render-service-test.py   (set CFA_TOOL_URL to test the live Pages build)"""
import asyncio, base64, json, os, socket, subprocess, sys, tempfile, threading, time, urllib.request, functools, http.server
from playwright.async_api import async_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0
def check(c, m):
    global fails
    print(("PASS " if c else "FAIL ") + m, flush=True); fails += 0 if c else 1
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def media(d):
    def ff(*a): subprocess.run(["ffmpeg", "-y", "-v", "error"] + list(a), check=True)
    ff("-f", "lavfi", "-i", "sine=f=220:d=9", "-ac", "1", os.path.join(d, "vo.mp3"))
    for k, c in enumerate(["0x2b4c7e", "0x7e2b4c", "0x4c7e2b"]):
        ff("-f", "lavfi", "-i", "color=c=%s:s=640x360:d=1" % c, "-frames:v", "1", os.path.join(d, "s%d.png" % k))
    ff("-f", "lavfi", "-i", "testsrc=s=640x360:d=3:r=24", "-pix_fmt", "yuv420p", os.path.join(d, "v.mp4"))

async def main():
    d = tempfile.mkdtemp(prefix="cfa-rs-ui-"); media(d)
    tool_url = os.environ.get("CFA_TOOL_URL")
    hp = free_port()
    if not tool_url:
        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
        http.server.ThreadingHTTPServer.allow_reuse_address = True
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", hp), h)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        tool_url = "http://127.0.0.1:%d/CFA_Script_Workflow.html" % hp
    origin = "/".join(tool_url.split("/")[:3])
    sp = free_port(); base = "http://127.0.0.1:%d" % sp
    tok = "ui-" + os.urandom(8).hex(); open(os.path.join(d, "token"), "w").write(tok)
    env = dict(os.environ, CFA_RENDER_DATA=os.path.join(d, "data"), CFA_RENDER_TOKEN_FILE=os.path.join(d, "token"), CFA_RENDER_PORT=str(sp),
               CFA_RENDER_ARGS="--no-grok --no-score --no-whisper --keys-env /dev/null", CFA_RENDER_MUSIC="", CFA_ALLOWED_ORIGINS=origin)
    svc = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools/render/service.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try: urllib.request.urlopen(base + "/health", timeout=1); break
        except Exception: time.sleep(0.2)
    b64 = lambda f: base64.b64encode(open(os.path.join(d, f), "rb").read()).decode()
    try:
        async with async_playwright() as p:
            br = await p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), headless=True, args=["--disable-features=LocalNetworkAccessChecks,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights"])  # https Pages -> http loopback test service only
            pg = await br.new_page(accept_downloads=True)
            errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(tool_url, wait_until="load")
            await pg.evaluate("""(a)=>{ const m=document.getElementById('settings-modal'); if(m) m.classList.remove('open');
              const blob=(b,t)=>URL.createObjectURL(new Blob([Uint8Array.from(atob(b),c=>c.charCodeAt(0))],{type:t}));
              finalScript='Why build new money? Jordan froze. That is why Satoshi wrote it.'; selId='v03';
              sceneData=[{line:'1. Why build new money?',tag:'IMAGE',characters:'JORDAN',resultURL:blob(a.s0,'image/png'),resultType:'image'},
                         {line:'2. Jordan froze.',tag:'VIDEO',characters:'JORDAN',resultURL:blob(a.v,'video/mp4'),resultType:'video'},
                         {line:'3. That is why Satoshi wrote it.',tag:'IMAGE',characters:'NONE',resultURL:blob(a.s2,'image/png'),resultType:'image'}];
              voAudioURL=blob(a.vo,'audio/mpeg');
              const W=[['Why',0.2,0.5],['build',0.5,0.8],['new',0.8,1.1],['money?',1.1,1.8],['Jordan',3.0,3.5],['froze.',3.5,4.2],['That',5.5,5.8],['is',5.8,6],['why',6,6.3],['Satoshi',6.3,6.9],['wrote',6.9,7.3],['it.',7.3,8.0]];
              voWords=W; goTo(6); }""", {"s0": b64("s0.png"), "s2": b64("s2.png"), "v": b64("v.mp4"), "vo": b64("vo.mp3")})
            await pg.evaluate("()=>{ document.querySelectorAll('.screen').forEach(s=>{s.classList.remove('vis');s.classList.add('hr')}); const c=document.getElementById('btn-send-grok').closest('.screen'); c.classList.remove('hr'); c.classList.add('vis'); c.style.display='flex'; for(let el=document.getElementById('btn-send-grok'); el && el!==c; el=el.parentElement){ if(getComputedStyle(el).display==='none') el.style.display='block'; } }")
            # 1. no service configured -> explains and opens settings
            await pg.evaluate("()=>{sessionStorage.removeItem('cfa_render_url');sessionStorage.removeItem('cfa_render_token')}")
            await pg.evaluate("document.getElementById('btn-send-grok').click()")
            msg = await pg.text_content("#fe-status")
            check("render service URL" in msg and await pg.evaluate("document.getElementById('settings-modal').classList.contains('open')"), "without a service: explains + opens Settings")
            await pg.fill("#sm-render-url", base + "/"); await pg.fill("#sm-render-token", "wrong")
            await pg.click("[onclick='smSaveRender()']")
            check(await pg.evaluate("sessionStorage.getItem('cfa_render_url')") == base and await pg.evaluate("localStorage.getItem('cfa_render_token')") is None, "URL + token saved to the session only (not localStorage)")
            await pg.evaluate("closeSettings()")
            await pg.evaluate("document.getElementById('btn-send-grok').click()"); await asyncio.sleep(2.5)
            _m=await pg.text_content("#fe-status"); check("access token" in _m, "wrong token -> clear message"+("" if "access token" in _m else " GOT: "+_m[:300]+" ERRS:"+str(errs)[:300]))
            await pg.evaluate("(t)=>{sessionStorage.setItem('cfa_render_token',t)}", tok)
            await pg.select_option("#rs-aspect", "landscape")
            await pg.evaluate("document.getElementById('btn-send-grok').click()")
            await pg.wait_for_function("document.getElementById('s-render').style.display==='flex'", timeout=30000)
            up = await pg.text_content("#rs-upload-txt")
            check("Uploaded" in up and await pg.evaluate("document.getElementById('rs-upload-bar').style.width") == "100%", "upload progress bar reached 100%% (%s)" % up.strip()[:40])
            check(await pg.is_visible("#rs-progress-view") and await pg.is_visible("#rs-elapsed"), "progress screen with timer shown")
            await asyncio.sleep(2.2)
            t1 = await pg.text_content("#rs-elapsed")
            stages = set()
            for _ in range(240):
                stages.add(await pg.text_content("#rs-stage-txt"))
                if await pg.is_visible("#rs-review-view"): break
                await asyncio.sleep(0.25)
            check(t1 != "0:00" or len(stages) > 1, "timer ticks (%s)" % t1)
            check(any("Rendering" in x or "Mixing" in x or "Encoding" in x or "planning" in x for x in stages), "live stage text: %s" % sorted(stages)[:4])
            check(await pg.is_visible("#rs-review-view"), "review screen appears when done")
            await pg.wait_for_function("document.getElementById('rs-video').readyState>=1", timeout=20000)
            dur = await pg.evaluate("document.getElementById('rs-video').duration")
            check(dur > 7, "review player loaded the rendered MP4 (%.1fs)" % dur)
            check((await pg.get_attribute("#rs-download", "href")).startswith("blob:") and (await pg.get_attribute("#rs-download", "download")).endswith(".mp4"), "download link ready")
            async with pg.expect_download() as dl:
                await pg.click("#rs-download")
            path = await (await dl.value).path()
            check(open(path, "rb").read(12)[4:8] == b"ftyp", "download saves a real MP4")
            check("1920x1080" in await pg.text_content("#rs-meta"), "16:9 render details shown")
            # vertical + notes
            await pg.select_option("#rs-aspect2", "vertical")
            await pg.fill("#rs-notes", "hold the last shot longer")
            await pg.click("[onclick='reEditRender(false)']")
            await pg.wait_for_function("document.getElementById('rs-progress-view').style.display===''", timeout=10000)
            check("re-edit" in await pg.text_content("#rs-title") and "9:16" in await pg.text_content("#rs-title"), "re-edit with notes goes back to the timer (9:16)")
            await pg.wait_for_function("document.getElementById('rs-review-view').style.display===''", timeout=120000)
            check("1080x1920" in await pg.text_content("#rs-meta"), "vertical re-edit rendered and shown")
            jobs = os.listdir(os.path.join(d, "data", "jobs"))
            notes = [json.load(open(os.path.join(d, "data", "jobs", j, "job.json"))).get("notes") for j in jobs]
            check("hold the last shot longer" in notes, "notes reached the service")
            await pg.click("#rs-review-view [onclick='closeRenderScreen()']")
            check(await pg.is_visible("#btn-send-grok") and not await pg.is_visible("#s-render"), "back to scenes restores the previous screen")
            # zip fallback still works
            async with pg.expect_download() as dl2:
                await pg.click("#btn-final-edit")
            check((await dl2.value).suggested_filename.endswith(".zip"), "zip export fallback still downloads")
            check(not errs, "no page errors %s" % errs[:2])
            await br.close()
    finally:
        svc.terminate()
    print("\n%d failure(s)" % fails); sys.exit(1 if fails else 0)
asyncio.run(main())
