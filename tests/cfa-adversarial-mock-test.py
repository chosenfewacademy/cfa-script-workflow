# Headless adversarial test: every external API (xAI, fal, ElevenLabs) is mocked via request
# interception, so it costs $0. Run: pip install playwright && python3 tests/cfa-adversarial-mock-test.py [group ...]
# Groups: happy xaierr nokey abort trunc xss inputs prompts fal vo storage reload settings timing batch (default all)
# Optional: CHROME=/usr/bin/google-chrome to use a system Chrome.
import asyncio, json, re, base64, sys
from playwright.async_api import async_playwright
import os
import http.server, threading, functools
_ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),'..'))
class _Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
_HTTPD=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(_Q,directory=_ROOT))
threading.Thread(target=_HTTPD.serve_forever,daemon=True).start()
# Served over http (not file://): Chrome keeps file:// localStorage per renderer, so reload tests flaked under load.
URL='http://127.0.0.1:%d/CFA_Script_Workflow.html'%_HTTPD.server_address[1]
_ORIGIN='http://127.0.0.1:%d/'%_HTTPD.server_address[1]
LINEMP3=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'fixtures_line.mp3'),'rb').read()
CLIP=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'fixtures_clip.mp4'),'rb').read()
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
SC={'xai':'ok','fal':'ok','el':'ok','delay':0,'script':None,'cls':None,'falDelay':0}
cnt={'xai':0,'falgen':0,'upload':0}
results=[]
def check(name,cond,detail=''):
    results.append((name,bool(cond),detail)); print(('PASS ' if cond else 'FAIL ')+name+(' — '+str(detail)[:200] if not cond else ''))
DEFAULT_SCRIPT=("Jordan hit send before he checked. Marcus waited and read the address twice.\n\n"
 "The gap between them grew. Jordan asked, \"What is a wallet really doing?\"\n\nThat question waits.")
def sse(chunks, usage=True, finish='stop'):
    out=''
    for i,c in enumerate(chunks):
        out+='data: '+json.dumps({'choices':[{'index':0,'delta':{'content':c},'finish_reason':(finish if i==len(chunks)-1 else None)}]})+'\n\n'
    if usage: out+='data: '+json.dumps({'choices':[],'usage':{'prompt_tokens':1000,'completion_tokens':500,'completion_tokens_details':{'reasoning_tokens':100},'cost_in_usd_ticks':50000000}})+'\n\n'
    return out+'data: [DONE]\n\n'
async def xai_route(route):
    cnt['xai']+=1
    req=route.request; body=json.loads(req.post_data or '{}')
    if SC['delay']: await asyncio.sleep(SC['delay'])
    mode=SC['xai']
    if mode=='net': return await route.abort('failed')
    if mode in('401','429','500','400'):
        st=int(mode); payload={'error':'Incorrect API key provided.'} if st==401 else ({} if st in(429,500) else {'error':'bad request'})
        return await route.fulfill(status=st,content_type='application/json',body=json.dumps(payload))
    if mode=='html500': return await route.fulfill(status=502,content_type='text/html',body='<html>Bad gateway</html>')
    if req.url.endswith('/v1/responses'):
        cnt['research']=cnt.get('research',0)+1
        if SC.get('researchFail'): return await route.fulfill(status=500,content_type='application/json',body='{}')
        txt=SC.get('researchOut') or ('KEY CONCEPTS: a wallet holds keys, not coins. '*6+'REAL-WORLD ANCHORS: Bitcoin white paper, 31 Oct 2008 (bitcoin.org). Genesis block 3 Jan 2009.')
        return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'output':[{'type':'web_search_call'},{'type':'message','content':[{'type':'output_text','text':txt}]}],'usage':{'cost_in_usd_ticks':0}}))
    sysmsg=body['messages'][0]['content']; user=body['messages'][1]['content']
    if 'script doctor who reads scripts ALOUD' in sysmsg:
        cnt['readaloud']=cnt.get('readaloud',0)+1
        SC['lastReadAloud']=user
        q=SC.get('raq') or []
        if q: v=q.pop(0)
        else:
            sc_=user.split('SCRIPT:\n',1)[1] if 'SCRIPT:\n' in user else ''
            v={'scores':{'flow':9,'cohesion':9,'logic':9,'human':9,'story_pull':9,'accuracy':9},'problems':[],'script':sc_}
        content=v if isinstance(v,str) else json.dumps(v)
        return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'choices':[{'message':{'content':content},'finish_reason':'stop'}],'usage':{}}))
    if 'director and cinematographer' in sysmsg:
        cnt['director']=cnt.get('director',0)+1; SC['lastDirector']=user
        v=SC.get('dirOut')
        if v is None: content='no shot list today'
        else: content=v if isinstance(v,str) else json.dumps(v)
        return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'choices':[{'message':{'content':content},'finish_reason':'stop'}],'usage':{}}))
    if 'character-continuity supervisor' in sysmsg:
        cnt['idcheck']=cnt.get('idcheck',0)+1
        q=SC.get('idq') or []
        v=q.pop(0) if q else {'differences':[],'visible':True,'score':10,'verdict':'same'}
        return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'choices':[{'message':{'content':json.dumps(v)},'finish_reason':'stop'}],'usage':{}}))
    if 'art-direction QA' in sysmsg:
        cnt['vision']=cnt.get('vision',0)+1
        q=SC.get('vision') or []
        intro=user[0]['text'] if isinstance(user,list) else ''
        SC['lastVisionIntro']=intro
        mm=re.search(r'must appear: ([^.]*)\.',intro); names=[x.strip() for x in mm.group(1).split(',')] if mm else []
        v=q.pop(0) if q else {'style_score':9,'style_match':True,'problems':'','has_text':False,'text':[],'text_garbled':False}
        if 'identity' not in v: v=dict(v,identity=[{'name':n,'visible':True,'score':9} for n in names])
        return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'choices':[{'message':{'content':json.dumps(v)},'finish_reason':'stop'}],'usage':{}}))
    if 'story editor' in sysmsg and 'senior' not in sysmsg:
        cnt['plan']=cnt.get('plan',0)+1
        text='PREMISE: Jordan at the bus stop\nDETAILS: $212.40, 4 minutes'
    elif 'senior script editor' in sysmsg and user.startswith('ONLY TASK'):
        cnt['fit']=cnt.get('fit',0)+1
        body_=user.split('SCRIPT:\n',1)[1]
        text=SC.get('fitOut') if SC.get('fitOut') is not None else body_
    elif 'senior script editor' in sysmsg:
        cnt['revise']=cnt.get('revise',0)+1
        SC['lastRevise']=user
        draft=user.split('DRAFT SCRIPT:\n',1)[1] if 'DRAFT SCRIPT:\n' in user else ''
        text=SC.get('reviseOut') if SC.get('reviseOut') is not None else draft+'\n\nRevised.'
    elif 'narrative architect' in sysmsg or 'head writer' in sysmsg:
        SC['lastDraftUser']=user
        text=SC['script'] or DEFAULT_SCRIPT
    elif 'segmentation tool' in sysmsg:
        inner=user.replace('BEGIN SCRIPT\n','').replace('\nEND SCRIPT','')
        sents=[x.strip() for x in re.split(r'(?<=[.!?])\s+',inner) if x.strip()]
        text='\n'.join(f'{i+1}. {x}' for i,x in enumerate(sents))
    elif 'classifying script segments' in sysmsg:
        n=len([l for l in user.split('\n') if l.strip()])
        text=SC['cls'] if SC['cls'] is not None else '\n'.join(f'[{i+1}] '+('VIDEO' if i%2 else 'IMAGE') for i in range(n))
    else:
        if mode=='promptfail' and 'Marcus' in user.split('\n')[0]: return await route.fulfill(status=500,content_type='application/json',body='{}')
        text='A flat scene with an orange mug. <b>bold</b> "quotes"\nSCENE: desk, lamp, night'
    finish='length' if mode=='trunc' else 'stop'
    if body.get('stream'):
        chunks=[text[i:i+7] for i in range(0,len(text),7)] or ['']
        if mode=='midfail':
            return await route.fulfill(status=200,content_type='text/event-stream',body=sse(chunks[:3],usage=False,finish=None)+'data: {"error":{"message":"upstream reset"}}\n\n')
        return await route.fulfill(status=200,content_type='text/event-stream',body=sse(chunks,finish=finish))
    return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'choices':[{'message':{'content':text},'finish_reason':finish}],'usage':{'prompt_tokens':100,'completion_tokens':50,'cost_in_usd_ticks':5000000}}))
async def fal_route(route):
    u=route.request.url
    if 'storage/upload/initiate' in u:
        cnt['upload']+=1
        if SC['falDelay']: await asyncio.sleep(SC['falDelay'])
        if SC['fal']=='uploadfail': return await route.fulfill(status=500,content_type='application/json',body='{}')
        return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'upload_url':'https://upload.mock/put/'+str(cnt['upload']),'file_url':'https://v3b.fal.media/files/up_'+str(cnt['upload'])+'.jpg'}))
    if 'upload.mock' in u: return await route.fulfill(status=200,body='')
    if 'fal.media' in u and u.split('?')[0].endswith('.mp4'): return await route.fulfill(status=200,content_type='video/mp4',headers={'Access-Control-Allow-Origin':'*'},body=CLIP)
    if 'fal.media' in u: return await route.fulfill(status=200,content_type='image/png',body=PNG)
    if u.startswith('https://queue.fal.run/') and '/requests/' in u:
        rid=u.split('/requests/')[1].split('/')[0]; Q=SC.get('falQ') or {}; job=Q.get(rid)
        if job is None: return await route.fulfill(status=404,content_type='application/json',body='{"detail":"not found"}')
        if u.split('?')[0].endswith('/status'):
            job['polls']+=1
            if (SC.get('qStatusNetFail') or 0)>0: SC['qStatusNetFail']-=1; return await route.abort('timedout')
            if SC.get('qMode')=='failed': return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'status':'FAILED','error':'model crashed'}))
            st='COMPLETED' if job['polls']>(SC.get('qPolls') or 2) else 'IN_PROGRESS'
            if SC.get('qMode')=='never': st='IN_QUEUE'
            return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'status':st}))
        return await route.fulfill(status=200,content_type='application/json',body=json.dumps(job['result']))
    cnt['falgen']+=1
    if SC.get('falLog') is None: SC['falLog']=[]
    SC['falLog'].append((u,route.request.post_data or ''))
    if SC['delay']: await asyncio.sleep(SC['delay'])
    m=SC['fal']
    if m in('429','500','422','401'):
        st=int(m); b={'detail':[{'msg':'field required','loc':['body','prompt']}]} if st==422 else ({'detail':'Invalid key'} if st==401 else {})
        return await route.fulfill(status=st,content_type='application/json',body=json.dumps(b))
    if m=='empty': return await route.fulfill(status=200,content_type='application/json',body='{}')
    n=cnt['falgen']
    if u.startswith('https://queue.fal.run/'):
        rid='req%d'%n; ep=u.split('queue.fal.run/')[1].split('?')[0]; app='/'.join(ep.split('/')[:2])
        res={'video':{'url':f'https://v3b.fal.media/files/v{n}.mp4'}} if ('video' in u or 'avatar' in u or 'talk' in u or 'sync' in u) else {'images':[{'url':f'https://v3b.fal.media/files/g{n}.png'}]}
        if not SC.get('falQ'): SC['falQ']={}
        SC['falQ'][rid]={'polls':0,'result':res}
        return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'request_id':rid,'status_url':f'https://queue.fal.run/{app}/requests/{rid}/status','response_url':f'https://queue.fal.run/{app}/requests/{rid}'}))
    if 'video' in u: return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'video':{'url':f'https://v3b.fal.media/files/v{n}.mp4'}}))
    return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'images':[{'url':f'https://v3b.fal.media/files/g{n}.png'}]}))
async def el_route(route):
    m=SC['el']
    if SC.get('elFailN'):
        SC['elFailN']-=1; SC['elFails']=(SC.get('elFails') or 0)+1
        return await route.fulfill(status=503,content_type='application/json',body='{"detail":"busy"}')
    if m in('401','429'): return await route.fulfill(status=int(m),content_type='application/json',body=json.dumps({'detail':{'message':'nope'}}))
    if m=='empty': return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'audio_base64':'','alignment':None}))
    body=json.loads(route.request.post_data or '{}'); text=body.get('text',''); SC['elBody']=body; SC['elURL']=route.request.url
    (SC.__setitem__('elCalls',SC.get('elCalls') or []) or SC['elCalls']).append((route.request.url,body))
    assert route.request.url.endswith('/with-timestamps'), route.request.url
    chars=list(text); st=[round(i*0.06,3) for i in range(len(chars))]; en=[round(x+0.06,3) for x in st]
    return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'audio_base64':base64.b64encode(LINEMP3 if SC.get('elReal') else b'ID3fakeaudio').decode(),'alignment':{'characters':chars,'character_start_times_seconds':st,'character_end_times_seconds':en}}))
async def oai_route(route):
    cnt['oai']=cnt.get('oai',0)+1
    SC['oaiBody']=route.request.post_data_buffer or b''
    return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'data':[{'b64_json':base64.b64encode(PNG).decode()}]}))
async def down_route(route):
    # explicit mock: render service unreachable (connection refused), counted
    SC.setdefault('downHits',[]).append(route.request.method+' '+route.request.url.split('127.0.0.1:9')[1])
    return await route.abort('connectionrefused')
async def other_route(route):
    u=route.request.url
    if u.startswith(('file:','data:','blob:',_ORIGIN)): return await route.continue_()
    print('UNEXPECTED REQUEST',u); return await route.abort()

async def newpage(b, keys=True, pre=None):
    ctx=await b.new_context(accept_downloads=True)
    pg=await ctx.new_page()
    errs=[]
    pg.on('pageerror',lambda e: errs.append('pageerror: '+str(e)+(' @'+str(SC.get('_step')) if os.environ.get('FBDBG') else '')))
    pg.on('console',lambda m: errs.append(m.type+': '+m.text) if m.type=='error' else None)
    pg.on('dialog',lambda d: (SC.setdefault('dialogs',[]).append(d.message), asyncio.ensure_future(d.dismiss() if SC.get('dismiss') else d.accept())))
    await ctx.route('**/*',other_route)
    await ctx.route(re.compile(r'http://127\.0\.0\.1:9/.*'),down_route)
    await ctx.route('https://api.x.ai/**',xai_route)
    await ctx.route(re.compile(r'https://(fal\.run|queue\.fal\.run|rest\.alpha\.fal\.ai|upload\.mock|v3b\.fal\.media)/.*'),fal_route)
    await ctx.route('https://api.elevenlabs.io/**',el_route)
    await ctx.route('https://api.openai.com/**',oai_route)
    async def bal_route(route):
        if 'user_balance' in route.request.url:
            b=SC.get('falbal','27.0106725'); return await route.fulfill(status=200 if b is not None else 403,headers={'access-control-allow-origin':'*'},body=str(b) if b is not None else '{}')
        d=SC.get('elsub'); 
        if d is None: return await route.fulfill(status=401,headers={'access-control-allow-origin':'*'},content_type='application/json',body=json.dumps({'detail':{'message':'missing the permission user_read'}}))
        return await route.fulfill(status=200,headers={'access-control-allow-origin':'*'},content_type='application/json',body=json.dumps(d))
    await ctx.route(re.compile(r'https://(rest\.alpha\.fal\.ai/billing/user_balance|api\.elevenlabs\.io/v1/user/subscription).*'),bal_route)
    if pre: await ctx.add_init_script(pre)
    if keys:
        await ctx.add_init_script("try{if(localStorage.getItem('cfa_format')===null)localStorage.setItem('cfa_format','narration');}catch(e){}")
        await ctx.add_init_script("sessionStorage.setItem('cfa_xai_key','xai-test');sessionStorage.setItem('cfa_fal_key','fal-test');sessionStorage.setItem('cfa_el_key','el-test');localStorage.setItem('cfa_onboarded','1');")
    await pg.goto(URL); await pg.wait_for_timeout(300)
    return ctx,pg,errs
J=lambda pg,js,*a: pg.evaluate(js,*a)
async def persist_reload(pg, errs=None):
    """Save, reload, wait for the app to boot. (Page is served over http://127.0.0.1 - on file:// Chrome can drop
    localStorage when it swaps renderers under load.) Returns the page."""
    await J(pg,"()=>saveWorkflowState()")
    await pg.reload(); await pg.wait_for_function("()=>typeof resumeSavedSession==='function'")
    return pg
async def go_review(pg):
    await J(pg,"()=>{sv(document.querySelector('.vo'),'v01');startGen();}")
    await pg.wait_for_function("()=>curScreen===3||curScreen===1&&document.getElementById('e1').textContent",timeout=15000)
async def go_seg(pg):
    await J(pg,"()=>startSeg()")
    await pg.wait_for_function("()=>document.getElementById('s4r').style.display!=='none'||curScreen===3",timeout=15000)
async def go_scenes(pg):
    await J(pg,"()=>{goTo(6);enterSceneGeneration();}")
    await pg.wait_for_function("()=>{const b=document.querySelector('#s6-class-results .btn.bprim');return (b&&!b.disabled&&document.getElementById('s6-class-results').style.display!=='none')||document.getElementById('e6').textContent}",timeout=20000)

async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(**({'executable_path':os.environ['CHROME']} if os.environ.get('CHROME') else {}),headless=True)
        T=sys.argv[1:] or ['all']
        def want(n): return 'all' in T or n in T

        if want('happy'):
            for k in SC: SC[k]={'xai':'ok','fal':'ok','el':'ok'}.get(k,0 if k in('delay','falDelay') else None)
            ctx,pg,errs=await newpage(b)
            await go_review(pg); check('happy: review reached', await J(pg,'()=>curScreen')==3)
            check('story: research brief ran and is shown in review', cnt.get('research',0)>=1 and 'white paper' in await J(pg,"()=>document.getElementById('research-panel').textContent") )
            check('story: research brief fed into plan+draft', 'RESEARCH BRIEF' in SC.get('lastDraftUser',''))
            check('story: read-aloud critic ran once', cnt.get('readaloud',0)==1, cnt.get('readaloud'))
            check('story: read-aloud scores shown', 'flow 9/10' in await J(pg,"()=>document.getElementById('research-panel').textContent"))
            check('happy: text spend tracked (fast planner/critic/hook + draft + revise + length-fit)', abs(await J(pg,'()=>textSpend')-0.017)<1e-6, await J(pg,'()=>textSpend'))
            await go_seg(pg); check('happy: segments', await J(pg,"()=>(segScript.match(/^\\d+\\./gm)||[]).length")>=3)
            await go_scenes(pg)
            st=await J(pg,"()=>({n:sceneData.length,consec:sceneData.some((s,i)=>i&&s.tag==='VIDEO'&&sceneData[i-1].tag==='VIDEO'),prompts:sceneData.every(s=>s.prompt)})")
            kb=await J(pg,"()=>{const K=keyBeats(sceneData);return {def:motionMode(),ok:sceneData.every((s,i)=>s.tag===(K.has(i)?'VIDEO':'IMAGE')||s.tag==='TALK'),n:sceneData.length,k:[...K]}}")
            check('happy: key-beat motion is the default (clips only on key beats, near-stills elsewhere)', kb['def']=='keybeat' and kb['ok'] and 0 in kb['k'] and kb['n']-1 in kb['k'], kb)
            await J(pg,"()=>setMotionMode('full')")
            st2=await J(pg,"()=>({full:motionMode()==='full'&&sceneData.every(s=>s.tag==='VIDEO'||s.tag==='TALK'),ui:document.getElementById('s6-motion').value,opts:[...document.getElementById('s6-motion').options].map(o=>o.textContent)})")
            check('happy: classified+prompts (fully animated selectable: every non-talking beat is a clip)', st['n']>=3 and st['prompts'] and st2['full'] and st2['ui']=='full', [st,st2])
            check('motion selector shows all three modes with a per-episode cost', '$' in st2['opts'][0] and st2['opts'][0].startswith('Key-beat motion (recommended)') and st2['opts'][1].startswith('Fully animated') and st2['opts'][2].startswith('Mixed (cheaper)'), st2['opts'])
            st3=await J(pg,"()=>{setMotionMode('mixed');const r={consec:sceneData.some((s,i)=>i&&s.tag==='VIDEO'&&sceneData[i-1].tag==='VIDEO'&&!s.resultURL)};setMotionMode('full');return r}")
            check('mixed mode: never two consecutive generated clips', not st3['consec'], st3)
            await J(pg,"()=>startSceneGeneration()")
            await pg.wait_for_timeout(500)
            await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(800)
            check('happy: scene 1 generated', await J(pg,"()=>!!sceneData[0].resultURL"), await J(pg,"()=>document.getElementById('e6').textContent"))
            check('happy: no errors', not errs, errs)
            await ctx.close()

        if want('xaierr'):
            for mode,expect in [('401','rejected the API key'),('429','429'),('500','500'),('net','Network error'),('html500','502'),('midfail','upstream reset')]:
                SC['xai']=mode
                ctx,pg,errs=await newpage(b)
                await J(pg,"()=>{sv(document.querySelector('.vo'),'v01');startGen();}")
                await pg.wait_for_function("()=>curScreen===1&&document.getElementById('e1').textContent",timeout=15000)
                e1=await J(pg,"()=>document.getElementById('e1').textContent")
                check(f'xai {mode}: error shown + back to step 1', expect.lower() in e1.lower() and await J(pg,"()=>!document.getElementById('bgen').disabled"), e1)
                check(f'xai {mode}: no page errors', not [e for e in errs if 'pageerror' in e], errs)
                await ctx.close()
            SC['xai']='ok'

        if want('nokey'):
            ctx,pg,errs=await newpage(b,keys=False)
            await J(pg,"()=>{closeSettings();sv(document.querySelector('.vo'),'v01');startGen();}")
            e1=await J(pg,"()=>document.getElementById('e1').textContent")
            check('no key: message', 'key missing' in e1, e1)
            check('no key: onboarding opened settings once', await J(pg,"()=>localStorage.getItem('cfa_onboarded')")=='1')
            check('no key: stays on step 1', await J(pg,'()=>curScreen')==1)
            await ctx.close()

        if want('abort'):
            SC['delay']=1.5
            ctx,pg,errs=await newpage(b)
            await J(pg,"()=>{sv(document.querySelector('.vo'),'v01');startGen();}")
            await pg.wait_for_timeout(300); await J(pg,"()=>abortGen()"); await pg.wait_for_timeout(2500)
            check('abort: stays on step 1, no review', await J(pg,'()=>curScreen')==1 and await J(pg,"()=>!genScript"))
            check('abort: button re-enabled', await J(pg,"()=>!document.getElementById('bgen').disabled"))
            SC['delay']=0
            await go_review(pg); check('abort: can generate after abort', await J(pg,'()=>curScreen')==3)
            # rapid double click on generate
            await J(pg,"()=>goTo(1,'left')"); n0=cnt['xai']
            SC['delay']=0.5
            await pg.click('#bgen'); await pg.click('#bgen',force=True,timeout=2000) if await J(pg,"()=>!document.getElementById('bgen').disabled") else None
            await pg.wait_for_timeout(1500)
            check('rapid click: single pipeline (plan+draft+revise = 3 calls)', cnt['xai']-n0==3, cnt['xai']-n0)
            SC['delay']=0
            check('abort: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()

        if want('trunc'):
            SC['xai']='trunc'
            ctx,pg,errs=await newpage(b); await go_review(pg)
            check('truncated: warning on review', 'output limit' in await J(pg,"()=>document.getElementById('e3').textContent"))
            SC['xai']='ok'; await ctx.close()

        if want('xss'):
            SC['script']='Marcus said "<img src=x onerror=window.__pwned=1>" & left.\n\nJordan typed </textarea><script>window.__pwned=2</script> then paused.\n\nThe end\u2014 émojis 🚀 ok.'
            ctx,pg,errs=await newpage(b); await go_review(pg); await go_seg(pg); await go_scenes(pg)
            await J(pg,"()=>{startSceneGeneration(); sceneData.forEach(s=>{s.done=true;}); showCompletionScreen(); exportManifest();}")
            await pg.wait_for_timeout(500)
            check('xss: nothing executed', await J(pg,"()=>!window.__pwned"))
            check('xss: no injected img', await J(pg,"()=>!document.querySelector('img[src=\"x\"]')"))
            SC['script']=None; await ctx.close()

        if want('inputs'):
            ctx,pg,errs=await newpage(b)
            await go_review(pg)
            await J(pg,"()=>{document.getElementById('txed').value='   ';startSeg();}")
            check('empty script: blocked', 'empty' in (await J(pg,"()=>document.getElementById('e3').textContent")).lower())
            big=('Marcus checks the address. ' * 8000)
            await J(pg,"t=>{document.getElementById('txed').value=t;onEd();}",big)
            await go_seg(pg)
            check('huge script: segmented', await J(pg,"()=>(segScript.match(/^\\d+\\./gm)||[]).length")>1000)
            # segmented text with no numbered lines
            await J(pg,"()=>{document.getElementById('sgo').value='no numbers here';onSegEd();goTo(6);enterSceneGeneration();}")
            await pg.wait_for_timeout(300)
            check('no numbered lines: error', 'No numbered lines' in await J(pg,"()=>document.getElementById('e6').textContent"))
            # classification garbage → defaults IMAGE
            SC['cls']='I cannot do that.'
            await J(pg,"()=>{document.getElementById('sgo').value='1. Marcus waits.\\n2. Jordan sends.\\n3. A chart.';onSegEd();}")
            await go_scenes(pg)
            check('garbage classification: all IMAGE (animated in full mode)', await J(pg,"()=>sceneData.every(s=>s.origTag==='IMAGE' && s.tag===(motionMode()==='full'||(motionMode()==='keybeat'&&keyBeats(sceneData).has(sceneData.indexOf(s)))?'VIDEO':'IMAGE'))"))
            SC['cls']=None
            check('inputs: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()

        if want('prompts'):
            SC['xai']='promptfail'
            ctx,pg,errs=await newpage(b); 
            await J(pg,"()=>{segScript='1. Marcus waits.\\n2. A chart.\\n3. Marcus smiles.';segOriginal=segScript;goTo(6);enterSceneGeneration();}")
            await pg.wait_for_function("()=>{const b=document.querySelector('#s6-class-results .btn.bprim');return b&&!b.disabled&&document.getElementById('s6-class-results').style.display!=='none'&&!/Generating/.test(b.textContent)}",timeout=15000)
            lbl=await J(pg,"()=>document.querySelector('#s6-class-results .btn.bprim').textContent")
            check('prompt failures counted', '2 prompts failed' in lbl, lbl)
            SC['xai']='ok'; await ctx.close()

        if want('fal'):
            ctx,pg,errs=await newpage(b)
            await J(pg,"""()=>{sceneData=[{line:'1. Marcus waits.',tag:'IMAGE',characters:'MARCUS',prompt:'p',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''},
              {line:'2. Marcus sends.',tag:'VIDEO',characters:'MARCUS',prompt:'p',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''},
              {line:'3. A chart.',tag:'IMAGE',characters:'NONE',prompt:'p',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''},
              {line:'4. Marcus and Jordan talk.',tag:'IMAGE',characters:'BOTH',prompt:'p',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''}];
              goTo(6);document.getElementById('s6-phase1').style.display='none';document.getElementById('s6-phase2').style.display='';currentScene=0;loadScene(0);}""")
            await pg.wait_for_timeout(400)
            for m,exp in [('429','429'),('500','500'),('422','field required'),('401','rejected the API key'),('empty','No result')]:
                SC['fal']=m; await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(300)
                e6=await J(pg,"()=>document.getElementById('e6').textContent")
                check(f'fal {m}: error shown, no result, button enabled', exp.lower() in e6.lower() and await J(pg,"()=>!sceneData[0].resultURL && !document.getElementById('btn-generate-scene').disabled"), e6)
            SC['fal']='ok'
            sp0=await J(pg,'()=>sessionSpend')
            check('fal errors: no spend charged', sp0==0, sp0)
            # Rapid scene switching while uploads are slow → slots must match the scene shown
            SC['falDelay']=0.4; up0=cnt['upload']
            await J(pg,"()=>{for(const k of Object.keys(charUploadCache)) delete charUploadCache[k]}")
            await J(pg,"()=>{for(const i of [1,0,3,2,1,0,3]){currentScene=i;loadScene(i);}}")
            await pg.wait_for_timeout(2500)
            st=await J(pg,"()=>({cur:currentScene,subj:document.querySelector('#slot-subject img')?.alt||'',co:document.querySelector('#slot-cosubject img')?.alt||'',subjUrl:!!sceneRefs.subject?.url?.startsWith('https'),coUrl:!!sceneRefs.cosubject?.url?.startsWith('https'),uploading:!!document.getElementById('slot-subject').dataset.uploading})")
            check('rapid switching: BOTH scene has Marcus+Jordan refs', st['cur']==3 and st['subj']=='Marcus' and st['co']=='Jordan' and st['subjUrl'] and st['coUrl'] and not st['uploading'], st)
            check('character uploads deduped (2 uploads for 7 rapid scene loads)', cnt['upload']-up0==2, cnt['upload']-up0)
            SC['falDelay']=0
            # Upload failure path
            SC['fal']='uploadfail'
            await J(pg,"()=>{for(const k of Object.keys(charUploadCache)) delete charUploadCache[k]}")
            await J(pg,"()=>{currentScene=0;loadScene(0);}"); await pg.wait_for_timeout(500)
            await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(300)
            check('upload fail: generation blocked with message', 'uploading' in (await J(pg,"()=>document.getElementById('e6').textContent")).lower() or 'character' in (await J(pg,"()=>document.getElementById('e6').textContent")).lower(), await J(pg,"()=>document.getElementById('e6').textContent"))
            SC['fal']='ok'
            await J(pg,"()=>{for(const k of Object.keys(charUploadCache)) delete charUploadCache[k]}")
            # Generate scene 0, switch away mid-flight
            SC['delay']=0.8
            await J(pg,"()=>{currentScene=0;loadScene(0);}"); await pg.wait_for_timeout(400)
            await J(pg,"()=>{generateScene(); setTimeout(()=>jumpToScene(2),200);}"); await pg.wait_for_timeout(3500)
            st=await J(pg,"()=>({r0:!!sceneData[0].resultURL,r2:!!sceneData[2].resultURL,sf1:sceneData[1].savedStartFrameURL===sceneData[0].resultURL,shown:!!document.querySelector('#s6-result-content img')})")
            check('switch mid-gen: result on scene 1 only + start frame for scene 2', st['r0'] and not st['r2'] and st['sf1'] and not st['shown'], st)
            SC['delay']=0
            # Veo without start frame
            await J(pg,"()=>{sceneData[1].savedStartFrameURL='';sceneData[1].characters='NONE';sceneData[1].startFrameManual=true;sceneData[0].resultURL='';jumpToScene(1);setVideoModel('veo31');}")
            await pg.wait_for_timeout(300); await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(200)
            check('veo concept clip without start frame: blocked', 'start frame' in (await J(pg,"()=>document.getElementById('e6').textContent")).lower())
            check('fal: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()

        if want('queue'):
            for k in SC: SC[k]={'xai':'ok','fal':'ok','el':'ok'}.get(k,0 if k in('delay','falDelay') else None)
            ctx,pg,errs=await newpage(b)
            await J(pg,"()=>sessionStorage.setItem('cfa_fal_key','k')")
            run="(a)=>falQueuePost(a[0],{prompt:'x'},{pollMs:20,maxMs:a[1]||5000}).then(d=>({ok:d}),e=>({err:e.message}))"
            SC['qPolls']=2; r=await pg.evaluate(run,['fal-ai/kling-video/v1.6/pro/image-to-video',0])
            check('queue: Kling video submits to queue.fal.run, polls, returns the video', (r.get('ok') or {}).get('video',{}).get('url','').endswith('.mp4') and any(u.startswith('https://queue.fal.run/fal-ai/kling-video/v1.6/pro/image-to-video') for u,_ in SC.get('falLog',[])), r)
            SC['fal']='401'; r=await pg.evaluate(run,['fal-ai/kling-video/v1.6/pro/image-to-video',0]); SC['fal']='ok'
            check('queue: bad key on submit -> clear error, no polling', 'err' in r and 'network' not in r['err'].lower(), r)
            SC['qMode']='failed'; r=await pg.evaluate(run,['fal-ai/kling-video/v1.6/pro/image-to-video',0]); SC['qMode']=None
            check('queue: FAILED status surfaces fal error', 'model crashed' in r.get('err',''), r)
            SC['qStatusNetFail']=3; r=await pg.evaluate(run,['fal-ai/kling-video/v1.6/pro/image-to-video',0])
            check('queue: transient status network errors are retried (no "Network error")', 'ok' in r, r)
            SC['qMode']='never'; r=await pg.evaluate(run,['fal-ai/kling-video/v1.6/pro/image-to-video',400]); SC['qMode']=None
            check('queue: stuck job stops after maxMs with a check-the-dashboard message', 'dashboard' in r.get('err',''), r)
            SC['qMode']='never'; r=await pg.evaluate("()=>{const c=new AbortController();const p=falQueuePost('fal-ai/kling-video/v1.6/pro/image-to-video',{},{pollMs:20,signal:c.signal}).then(()=>'done',e=>e.name);setTimeout(()=>c.abort(),60);return p;}")
            SC['qMode']=None; check('queue: abort signal stops polling', r=='AbortError', r)
            SC['qPolls']=3; r=await pg.evaluate("()=>Promise.all(Array.from({length:25},(_,i)=>falQueuePost('fal-ai/kling-video/v1.6/pro/text-to-video',{i},{pollMs:15}))).then(a=>new Set(a.map(d=>d.video.url)).size)")
            check('queue stress: 25 concurrent clips all resolve to their own result', r==25, r)
            src=await J(pg,"()=>generateScene.toString()") if await J(pg,"()=>typeof generateScene==='function'") else ''
            check('queue: no video endpoint left on synchronous fal.run', not re.search(r"falPost\('fal-ai/(kling-video|veo3)", await J(pg,"()=>document.documentElement.outerHTML")) , '')
            await ctx.close()
        if want('vo'):
            for m,exp in [('401','Invalid API key'),('429','Rate limit'),('empty','Empty audio'),('ok','')]:
                SC['el']=m
                ctx,pg,errs=await newpage(b)
                await J(pg,"()=>{finalScript='Hello there.';selId='v01';goVO();generateVO();}"); await pg.wait_for_timeout(500)
                e5=await J(pg,"()=>document.getElementById('e5').textContent")
                if m=='ok': check('vo ok: audio ready', await J(pg,"()=>document.getElementById('s5-result').style.display!=='none'"), e5)
                else: check(f'vo {m}: error', exp.lower() in e5.lower() and await J(pg,"()=>!document.getElementById('btn-vo').disabled"), e5)
                await ctx.close()
            SC['el']='ok'

        if want('storage'):
            # corrupt values
            pre="""localStorage.setItem('cfa_session_spend','abc');localStorage.setItem('cfa_fal_budget','-5');localStorage.setItem('cfa_xai_spend','NaN');localStorage.setItem('cfa_session_gens','x');localStorage.setItem('cfa_workflow_state_v1','{not json');"""
            ctx,pg,errs=await newpage(b,pre=pre)
            st=await J(pg,"()=>({s:sessionSpend,t:textSpend,g:sessionGens,banner:document.getElementById('resume-banner').style.display,chip:document.getElementById('topbar-cost-chip-text')?.textContent})")
            check('corrupt storage: sane values, no banner', st['s']==0 and st['t']==0 and st['g']==0 and st['banner']=='none', st)
            check('corrupt storage: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()
            # corrupt structure inside valid JSON
            pre="localStorage.setItem('cfa_workflow_state_v1',JSON.stringify({version:1,savedAt:'x',sceneData:[null,5,{line:'1. Marcus waits.',tag:'VIDEO',resultURL:'javascript:alert(1)'},{line:''}],currentScene:99,selectedImageModel:'evil'}));"
            ctx,pg,errs=await newpage(b,pre=pre)
            check('corrupt state: banner shown', await J(pg,"()=>document.getElementById('resume-banner').style.display!=='none'"))
            await J(pg,"()=>resumeSavedSession()"); await pg.wait_for_timeout(500)
            st=await J(pg,"()=>({n:sceneData.length,cur:currentScene,url:sceneData[0].resultURL,m:selectedImageModel,screen:curScreen})")
            check('corrupt state: sanitised resume', st=={'n':1,'cur':0,'url':'','m':'kling-o1','screen':6}, st)
            check('corrupt state: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()
            # old 9bbf30e format
            old={'version':1,'savedAt':1760000000000,'finalScript':'Marcus waits. Jordan sends.','segScript':'1. Marcus waits.\n2. Jordan sends.\n3. A chart.',
                 'sceneData':[{'line':'1. Marcus waits.','tag':'IMAGE','characters':'MARCUS','prompt':'p1','sceneDesc':'desk','styleDesc':'','done':True,'resultURL':'https://v3b.fal.media/files/old.png','resultType':'image','resultModel':'Kling o1','savedStartFrameURL':''},
                              {'line':'2. Jordan sends.','tag':'VIDEO','characters':'JORDAN','prompt':'p2','sceneDesc':'','styleDesc':'','done':False,'resultURL':'','resultType':'','resultModel':'','savedStartFrameURL':'https://v3b.fal.media/files/old.png'},
                              {'line':'3. A chart.','tag':'IMAGE','characters':'NONE','prompt':'p3','sceneDesc':'','styleDesc':'','done':False,'resultURL':'','resultType':'','resultModel':'','savedStartFrameURL':''}],
                 'currentScene':1,'currentScreen':6,'selectedImageModel':'imagen4','selectedVideoModel':'veo31','sceneDuration':8}
            ctx,pg,errs=await newpage(b,pre="localStorage.setItem('cfa_workflow_state_v1',"+json.dumps(json.dumps(old))+");")
            await J(pg,"()=>resumeSavedSession()"); await pg.wait_for_timeout(600)
            st=await J(pg,"()=>({cur:currentScene,sf:sceneRefs.startframe?.url||'',vm:selectedVideoModel,dur:sceneDuration,seg:document.getElementById('sgo').value.length>0,veoBtn:document.querySelector('.duration-toggle .dur-btn.active')?.textContent})")
            check('old format: resumes on scene 2 with start frame + Veo 8s', st['cur']==1 and st['sf'].endswith('old.png') and st['vm']=='veo31' and st['dur']==8 and st['seg'], st)
            await J(pg,"()=>jumpToScene(0)"); await J(pg,"()=>jumpToScene(2)"); await pg.wait_for_timeout(300)
            m=await J(pg,"()=>selectedImageModel"); await J(pg,"()=>jumpToScene(0)"); m2=await J(pg,"()=>selectedImageModel")
            check('old format: imagen restored to kling for character scene', m=='imagen4' and m2=='kling-o1', (m,m2))
            check('old format: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()
            # quota full
            pre="Storage.prototype.setItem=function(k,v){ if(k.startsWith('cfa_')&&k!=='cfa_onboarded'&&this===localStorage){ const e=new Error('quota'); e.name='QuotaExceededError'; throw e;} };"
            ctx,pg,errs=await newpage(b,pre=pre)
            await J(pg,"()=>{trackSpend(0.04);trackTextSpend(0.01);sceneData=[{line:'1. x',tag:'IMAGE',characters:'NONE',prompt:'',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''}];saveWorkflowState();smSaveBudget&&0;}")
            check('quota full: warning shown, no crash', 'storage is full' in (await J(pg,"()=>document.getElementById('e6').textContent")).lower() and not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()
            # budget with cents
            ctx,pg,errs=await newpage(b)
            await J(pg,"()=>{openSettings();}")
            check('budget keeps cents', await J(pg,"()=>document.getElementById('sm-fal-budget').value")=='16.58')
            await ctx.close()

        if want('reload'):
            ctx,pg,errs=await newpage(b)
            await go_review(pg); await go_seg(pg); await go_scenes(pg)
            await J(pg,"()=>{startSceneGeneration();}"); await pg.wait_for_timeout(500)
            await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(600); await J(pg,"()=>confirmScene()"); await pg.wait_for_timeout(300)
            before=await J(pg,"()=>({n:sceneData.length,cur:currentScene,r:sceneData[0].resultURL,sel:selId})")
            pg=await persist_reload(pg,errs)
            check('reload: banner', await J(pg,"()=>document.getElementById('resume-banner').style.display!=='none'"), (before, SC))
            await J(pg,"()=>resumeSavedSession()"); await pg.wait_for_timeout(500)
            after=await J(pg,"()=>({n:sceneData.length,cur:currentScene,r:sceneData[0].resultURL,sel:selId})")
            check('reload: state restored', before==after, (before,after))
            check('reload: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()

        if want('settings'):
            ctx,pg,errs=await newpage(b,keys=False)
            await J(pg,"()=>{document.getElementById('sm-xai-key').value='  xai-abc  ';smSaveXai();}")
            check('key trimmed + saved', await J(pg,"()=>sessionStorage.getItem('cfa_xai_key')")=='xai-abc')
            await J(pg,"()=>{document.getElementById('sm-xai-key').value='';smSaveXai();}")
            check('clearing key removes it', await J(pg,"()=>sessionStorage.getItem('cfa_xai_key')") is None)
            await J(pg,"()=>{document.getElementById('sm-model-writer').value='grok-x';smSaveModels();}")
            check('model override', await J(pg,"()=>llmModel('writer')")=='grok-x' and await J(pg,"()=>llmModel('fast')")=='grok-4.3')
            check('settings: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()

        if want('timing'):
            ctx,pg,errs=await newpage(b)
            await go_review(pg); await go_seg(pg)
            await J(pg,"()=>{selId='v01';goVO();generateVO();}"); await pg.wait_for_timeout(800)
            st=await J(pg,"()=>({w:voWords.length,srt:document.getElementById('vo-srt-btn').style.display,note:document.getElementById('vo-timing-note').textContent,vs:voiceSpend})")
            check('timing: words aligned + SRT offered + voice spend', st['w']>5 and st['srt']=='' and 'segments timed' in st['note'] and st['vs']>0, st)
            async with pg.expect_download() as dl: await J(pg,"()=>downloadBeatSRT()")
            srt=open(await (await dl.value).path()).read()
            check('timing: SRT well-formed', srt.startswith('1\n00:00:00,000 --> ') and srt.count('-->')>=3, srt[:200])
            SC['cls']='[1] IMAGE\n[2] VIDEO\n[3] IMAGE\n[4] VIDEO\n[5] IMAGE'
            await go_scenes(pg); SC['cls']=None
            await J(pg,"()=>setMotionMode('full')")
            st=await J(pg,"()=>sceneData.map(s=>[s.tag,s.tStart,s.tEnd])")
            check('timing: every scene timed, monotonic', all(x[1] is not None for x in st) and all(st[i][1]>=st[i-1][2]-1e-6 for i in range(1,len(st))), st)
            await J(pg,"()=>{sceneData[1].tStart=0;sceneData[1].tEnd=7.3;startSceneGeneration();}"); await pg.wait_for_timeout(300)
            await J(pg,"()=>jumpToScene(1)"); await pg.wait_for_timeout(200)
            d=await J(pg,"()=>({d:sceneDuration,hint:document.getElementById('dur-hint').textContent})")
            check('timing: Kling O1 (default) picks the shortest clip that covers a 7.3s beat (8s, less morphing than 10s)', d['d']==8 and 'auto 8s' in d['hint'], d)
            await J(pg,"()=>setVideoModel('veo31')"); await J(pg,"()=>jumpToScene(0)"); await J(pg,"()=>jumpToScene(1)")
            check('timing: Veo picks 8s', await J(pg,'()=>sceneDuration')==8)
            await J(pg,"()=>setDuration(4)"); await J(pg,"()=>jumpToScene(0)"); await J(pg,"()=>jumpToScene(1)")
            check('timing: manual pick sticks per scene', await J(pg,'()=>sceneDuration')==4 and 'you picked 4s' in await J(pg,"()=>document.getElementById('dur-hint').textContent"))
            pg=await persist_reload(pg,errs); await J(pg,"()=>resumeSavedSession()"); await pg.wait_for_function("()=>sceneData.length>1",timeout=8000)
            check('timing: survives reload', await J(pg,"()=>voWords.length>5 && sceneData[1].videoDur===4 && sceneData[0].tEnd>0"), await J(pg,"()=>({w:voWords.length,d:sceneData[1]&&sceneData[1].videoDur,t:sceneData[0]&&sceneData[0].tEnd})"))
            check('timing: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()
            # too-long script for model
            ctx,pg,errs=await newpage(b)
            await J(pg,"()=>{finalScript='a'.repeat(12000);selId='v01';goVO();document.getElementById('el-model').value='eleven_v4';generateVO();}"); await pg.wait_for_timeout(300)
            check('vo: over-limit blocked before call', '10,000' in await J(pg,"()=>document.getElementById('e5').textContent"))
            await ctx.close()

        if want('batch'):
            ctx,pg,errs=await newpage(b)
            await J(pg,"""()=>{sceneData=[1,2,3,4,5,6,7].map(i=>({line:i+'. '+(i%3===0?'A chart.':i%2?'Marcus waits.':'Marcus and Jordan talk.'),tag:i===4?'VIDEO':'IMAGE',characters:i%3===0?'NONE':i%2?'MARCUS':'BOTH',prompt:'p'+i,sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''}));
              sceneData[6].prompt='';goTo(6);document.getElementById('s6-phase1').style.display='none';document.getElementById('s6-phase2').style.display='';currentScene=0;loadScene(0);}""")
            await pg.wait_for_timeout(300)
            check('batch: button counts 5 targets', 'all 5' in await J(pg,"()=>document.getElementById('btn-gen-all').textContent"))
            SC['delay']=0.4; n0=cnt['falgen']; peak={'v':0}
            await J(pg,"()=>{window.__peak=0;const of=window.fetch;window.fetch=async(...a)=>{const gen=String(a[0]).startsWith('https://fal.run/');if(gen){window.__inflight=(window.__inflight||0)+1;window.__peak=Math.max(window.__peak,window.__inflight);}try{return await of(...a);}finally{if(gen)window.__inflight--;}};generateAllImages();}")
            await pg.wait_for_timeout(300); await J(pg,"()=>generateAllImages()")  # clicking again = stop
            await pg.wait_for_timeout(1500)
            st=await J(pg,"()=>({peak:window.__peak,done:sceneData.filter(s=>s.resultURL).length,running:!!batchRun,e6:document.getElementById('e6').textContent})")
            check('batch: stop honoured, ≤3 in flight', st['peak']<=3 and st['done']==3 and not st['running'] and 'stopped' in st['e6'].lower(), st)
            await J(pg,"()=>generateAllImages()"); await pg.wait_for_timeout(1500)
            st=await J(pg,"()=>({done:sceneData.filter(s=>s.resultURL).length,sf:sceneData[3].savedStartFrameURL===sceneData[2].resultURL,vid:!!sceneData[3].resultURL,noprompt:!!sceneData[6].resultURL,models:sceneData.map(s=>s.resultModel),spend:sessionSpend,btn:document.getElementById('btn-gen-all').textContent})")
            check('batch: all prompted images done, video/no-prompt skipped, start frame set', st['done']==5 and st['sf'] and not st['vid'] and not st['noprompt'], st)
            check('batch: concept scenes no longer text-only — every still is Kling o1 with the style anchor', st['models'][2].startswith('Kling o1') and st['models'][0].startswith('Kling o1'), st['models'])
            SC['fal']='500'; g0=cnt['falgen']; await J(pg,"()=>{sceneData[0].resultURL='';sceneData[1].resultURL='';renderSceneDots();generateAllImages();}")
            for _ in range(40):
                await pg.wait_for_timeout(250)
                if not await J(pg,"()=>!!batchRun"): break
            check('batch: each failed scene is retried once automatically', cnt['falgen']-g0>=4, cnt['falgen']-g0)
            check('batch: failures reported', '2 failed' in await J(pg,"()=>document.getElementById('e6').textContent"), await J(pg,"()=>document.getElementById('e6').textContent"))
            SC['fal']='ok'; SC['delay']=0
            check('batch: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()

        if want('writing'):
            SC['xai']='ok'
            ctx,pg,errs=await newpage(b)
            p0,r0=cnt.get('plan',0),cnt.get('revise',0)
            await go_review(pg)
            st=await J(pg,"()=>({g:genScript,cur:curScreen})")
            check('writing: plan + revise ran, revised text used', cnt.get('plan',0)-p0==1 and cnt.get('revise',0)-r0==1 and st['g'].endswith('Revised.'), st)
            check('writing: plan passed to draft privately', 'PRIVATE STORY PLAN' in SC.get('lastDraftUser','') and '$212.40' in SC['lastDraftUser'])
            check('writing: plan not in output', 'PREMISE' not in st['g'])
            # short/empty revision → keep draft
            SC['reviseOut']='Too short.'
            await J(pg,"()=>goTo(1,'left')"); await go_review(pg)
            check('writing: too-short revision rejected, draft kept', await J(pg,"()=>genScript.startsWith('Jordan hit send')&&!genScript.includes('Too short')"))
            SC['reviseOut']=None
            # linter feeds the reviser
            SC['script']="Here's the thing. Jordan waited. It's not about money, it's about trust. Why? How? When? He left."
            await J(pg,"()=>goTo(1,'left')"); await go_review(pg)
            lr=SC.get('lastRevise','')
            check('writing: linter issues handed to reviser', 'SPECIFIC ISSUES' in lr and "here's the thing" in lr.lower() and 'Stacked rhetorical' in lr, lr[-400:])
            SC['script']=None
            # length enforcement: short mock script → one fit pass + UI flag; in-range fit output is used
            f0=cnt.get('fit',0)
            await J(pg,"()=>goTo(1,'left')"); await go_review(pg)
            check('length: out-of-range triggers a fit pass plus at most 2 final hard fits', 1<=cnt.get('fit',0)-f0<=3, cnt.get('fit',0)-f0)
            check('length: review flags out-of-range words', 'outside the 650' in await J(pg,"()=>document.getElementById('e3').textContent"))
            SC['fitOut']=' '.join(['word']*780)
            await J(pg,"()=>goTo(1,'left')"); await go_review(pg)
            st=await J(pg,"()=>({w:wordCount(genScript),e:document.getElementById('e3').textContent})")
            check('length: in-range fit result used, no flag', st['w']==780 and 'outside' not in st['e'], st)
            SC['fitOut']=None
            check('length: linter reports word count', 'must be 650' in await J(pg,"()=>scriptLint('a b c').issues.join(' ')"))
            # fast mode = single call
            n0=cnt['xai']
            await J(pg,"()=>{goTo(1,'left');document.getElementById('d-passes').value='fast';}"); await go_review(pg)
            check('writing: single-pass mode = 1 call', cnt['xai']-n0==1, cnt['xai']-n0)
            # dial guidance reaches the prompt
            await J(pg,"()=>{document.getElementById('d-pacing').value='slow burn';goTo(1,'left');}"); await go_review(pg)
            check('writing: dial expanded into instructions', 'Let moments breathe' in SC.get('lastDraftUser',''))
            # sampling params sent
            check('writing: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()

        if want('pace'):
            for k in SC: SC[k]={'xai':'ok','fal':'ok','el':'ok'}.get(k,SC[k]) if k in('xai','fal','el') else SC[k]
            ctx,pg,errs=await newpage(b)
            check('pace: Slow is the default', await J(pg,"()=>document.getElementById('el-pace').value")=='slow')
            await J(pg,"()=>{finalScript='Hello there. Calm now.';selId='v01';goVO();generateVO();}"); await pg.wait_for_timeout(900)
            vs=(SC.get('elBody') or {}).get('voice_settings',{})
            check('pace: slow sends speed 0.9 and stability 0.5', vs.get('speed')==0.9 and abs(vs.get('stability',0)-0.5)<1e-9, vs)
            check('pace: recorded with the timestamps', await J(pg,"()=>voPace")=='slow' and await J(pg,"()=>voWords.length")>0)
            await J(pg,"()=>{document.getElementById('el-pace').value='expressive';generateVO();}"); await pg.wait_for_timeout(900)
            vs=(SC.get('elBody') or {}).get('voice_settings',{})
            check('pace: expressive = unhurried 0.93, looser stability, more style', vs.get('speed')==0.93 and abs(vs.get('stability',0)-0.38)<1e-9 and abs(vs.get('style',0)-0.55)<1e-9, vs)
            check('pace: expressive recorded', await J(pg,"()=>voPace")=='expressive')
            await J(pg,"()=>{document.getElementById('el-pace').value='normal';generateVO();}"); await pg.wait_for_timeout(900)
            vs=(SC.get('elBody') or {}).get('voice_settings',{})
            check('pace: normal sends speed 1.0', vs.get('speed')==1.0 and abs(vs.get('stability',0)-0.5)<1e-9, vs)
            check('pace: summary shows pace', 'Normal pace' in await J(pg,"()=>{updateVSSummary();return document.getElementById('vs-summary').textContent}"))
            r=await J(pg,"()=>inferCharactersAcrossBeats(['1. Jordan sits down.','2. He sighs and opens the app.','3. A blockchain is a shared ledger.','4. Marcus and Jordan laugh.','5. They high-five.','6. The fee is tiny.'])")
            check('continuity: pronoun beats inherit the named character, concept beats stay NONE', r==['JORDAN','JORDAN','NONE','BOTH','BOTH','NONE'], r)
            r=await J(pg,"""()=>{sceneData=[{tag:'IMAGE',characters:'JORDAN',resultURL:'https://x/j.png',resultType:'image'},{tag:'IMAGE',characters:'NONE',resultURL:'https://x/c.png',resultType:'image'},{tag:'VIDEO',characters:'JORDAN'},{tag:'VIDEO',characters:'NONE'},{tag:'VIDEO',characters:'MARCUS'}];
              return [bestStartFrameFor(2),bestStartFrameFor(3),bestStartFrameFor(4)];}""")
            check('continuity: character clips start from a frame with that character, never a concept still', r==['https://x/j.png','https://x/c.png',''], r)
            r=await J(pg,"""()=>{sceneData=[{tag:'IMAGE',characters:'NONE',resultURL:'',resultType:''},{tag:'VIDEO',characters:'NONE'},{tag:'IMAGE',characters:'JORDAN',resultURL:'',resultType:''},{tag:'VIDEO',characters:'JORDAN'}];
              applyImageResult(0,'https://x/c.png','m'); const a=sceneData[3].savedStartFrameURL||''; applyImageResult(2,'https://x/j.png','m');
              return [sceneData[1].savedStartFrameURL,a,sceneData[3].savedStartFrameURL];}""")
            check('continuity: new images update start frames of later clips by character', r==['https://x/c.png','','https://x/j.png'], r)
            await J(pg,"""()=>{sceneData=[{line:'1. Dee has the laptop open.',tag:'IMAGE',characters:'NONE',prompt:'Dee at laptop',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''},
              {line:'2. A chart.',tag:'IMAGE',characters:'NONE',prompt:'chart',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''},
              {line:'3. Marcus walks in.',tag:'VIDEO',characters:'MARCUS',prompt:'Marcus walks in',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''},
              {line:'4. Dee laughs.',tag:'IMAGE',characters:'NONE',prompt:'Dee laughs',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''}];
              window.confirm=()=>true;}""")
            SC['falLog']=[]
            await J(pg,"async()=>{await generateAllImages();}")
            await pg.wait_for_timeout(500)
            log=[(u,json.loads(b or '{}')) for u,b in SC['falLog'] if 'upload' not in u]
            dee=[x for x in log if 'Dee (' in x[1].get('prompt','')]
            chart=[x for x in log if x[1].get('prompt','').startswith('chart')]
            first=await J(pg,"()=>sceneData[0].resultURL")
            check('cast: Dee scenes carry her fixed look, the chart does not', len(dee)==2 and chart and 'Dee (' not in chart[0][1]['prompt'], [x[1].get('prompt','')[:40] for x in log])
            deeRef=await J(pg,"()=>castRefReady.Dee||''")
            check('cast: every Dee still uses her fixed same-style reference sheet (Kling O1)', deeRef.startswith('https://') and len(dee)==2 and all('kling-image/o1' in u and deeRef in b.get('image_urls',[]) for u,b in dee), [(u[-30:],b.get('image_urls')) for u,b in dee])
            # ── Style anchor, vision style check, GPT text cleanup ──
            log=[(u,json.loads(b or '{}')) for u,b in SC['falLog'] if 'upload' not in u]
            mj=await J(pg,"async()=>await styleRefUrls()")
            check('style: concept still goes to Kling o1 with the Marcus/Jordan sheets as style refs + style spec', chart and 'kling-image/o1' in chart[0][0] and all(u in chart[0][1].get('image_urls',[]) for u in mj) and 'ART STYLE (locked' in chart[0][1]['prompt'] and 'ART-STYLE reference only' in chart[0][1]['prompt'], chart and chart[0][1])
            check('style: no Nano Banana text-only calls', not any('nano-banana' in u for u,b in log), [u for u,b in log])
            check('style: every still was vision-checked', cnt.get('vision',0)>=3, cnt.get('vision'))
            bad={'style_score':3,'style_match':False,'problems':'photo-real lighting','has_text':False,'text':[]}
            await J(pg,"()=>{window.__sd=sceneData;sceneData=[{line:'1. A crowd outside a bank.',tag:'IMAGE',characters:'NONE',prompt:'crowd outside a bank',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''}];}")
            SC['falLog']=[]; SC['vision']=[dict(bad),dict(bad),dict(bad),dict(bad)]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            gens=[u for u,b in SC['falLog'] if 'upload' not in u]
            qa=await J(pg,"()=>sceneData[0].styleQA")
            check('style: off-style result regenerated, capped at 2 redos', len(gens)==3 and qa['attempts']==3 and qa['match'] is False, (len(gens),qa))
            check('style: retry prompt asks to fix the named drift', 'photo-real lighting' in json.loads(SC['falLog'][-1][1])['prompt'], '')
            await J(pg,"()=>{sceneData[0].resultURL='';}")
            SC['falLog']=[]; SC['vision']=[dict(bad),{'style_score':9,'style_match':True,'problems':'','has_text':False,'text':[]}]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            check('style: stops as soon as the check passes', len([u for u,b in SC['falLog'] if 'upload' not in u])==2 and await J(pg,"()=>sceneData[0].styleQA.attempts")==2)
            # No writing unless the beat needs it; GPT cleanup only on those beats
            await J(pg,"()=>{sessionStorage.setItem('cfa_openai_key','oai-test');sceneData[0].resultURL='';}")
            o0=cnt.get('oai',0); SC['falLog']=[]; SC['vision']=[{'style_score':9,'style_match':True,'has_text':True,'text':['BANK OF AMERCIA']},{'style_score':9,'style_match':True,'has_text':False,'text':[]}]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            gl=[json.loads(b)['prompt'] for u,b in SC['falLog'] if 'upload' not in u]
            st=await J(pg,"()=>({m:sceneData[0].resultModel,qa:sceneData[0].styleQA,box:document.getElementById('qa-gpt-text').checked})")
            check('no-text: plain beat forbids writing in the prompt', gl and 'NO WRITING ANYWHERE' in gl[0], gl[:1])
            check('no-text: stray writing on a plain beat triggers a redo, not a GPT pass', len(gl)==2 and 'remove ALL text' in gl[1] and cnt.get('oai',0)==o0 and '+ GPT' not in st['m'] and st['box'], (len(gl),st))
            await J(pg,"()=>localStorage.setItem('cfa_overlay_only','0')")  # in-image text path (overlay-only off)
            await J(pg,"()=>{sceneData[0].resultURL='';sceneData[0].line='1. Jordan writes \"October 2008\" in the notebook.';sceneData[0].prompt='Jordan writing in a notebook';}")
            o0=cnt.get('oai',0); SC['falLog']=[]; SC['vision']=[{'style_score':9,'style_match':True,'has_text':True,'text':['Octobr 2008'],'identity':[{'name':'Jordan','visible':True,'score':9}]}]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            gl=[json.loads(b)['prompt'] for u,b in SC['falLog'] if 'upload' not in u]
            body=SC.get('oaiBody',b'').decode('latin1')
            check('gpt text: beat that needs words allows them and gets the GPT cleanup', gl and 'NO WRITING' not in gl[0] and 'Only the specific words' in gl[0] and cnt.get('oai',0)==o0+1 and '+ GPT' in await J(pg,"()=>sceneData[0].resultModel"), gl[:1])
            check('gpt text: edit keeps style/characters and gets the seen words', 'Octobr 2008' in body and '3D animated' in body and 'flat 2D' not in body and 'gpt-image' in body, body[:200])
            await J(pg,"()=>{setQaToggle('cfa_gpt_text',false);sceneData[0].resultURL='';}")
            o0=cnt.get('oai',0); SC['vision']=[{'style_score':9,'style_match':True,'has_text':True,'text':['X'],'identity':[{'name':'Jordan','visible':True,'score':9}]}]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            check('gpt text: toggle off skips it', cnt.get('oai',0)==o0)
            await J(pg,"()=>{setQaToggle('cfa_gpt_text',true);sessionStorage.removeItem('cfa_openai_key');}")
            # Identity check
            r=await J(pg,"()=>[beatNeedsText({line:'Jordan almost nodded.'}),beatNeedsText({line:'Marcus had underlined October 2008.'}),beatNeedsText({line:'\"People made money on this.\"'})]")
            check('no-text: needs-text detector', r==[False,True,True], r)
            await J(pg,"()=>localStorage.removeItem('cfa_overlay_only')")
            await J(pg,"()=>{sceneData[0]={line:'1. Jordan sits at the desk.',tag:'IMAGE',characters:'JORDAN',prompt:'Jordan at desk',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''};}")
            SC['falLog']=[]; v0=cnt.get('vision',0)
            off={'style_score':9,'style_match':True,'has_text':False,'text':[],'identity':[{'name':'Jordan','visible':True,'score':3,'problems':'older, darker hair, heavier build'}]}
            SC['vision']=[dict(off),{'style_score':9,'style_match':True,'has_text':False,'text':[],'identity':[{'name':'Jordan','visible':True,'score':9}]}]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            gl=[json.loads(b) for u,b in SC['falLog'] if 'upload' not in u]
            qa=await J(pg,"()=>sceneData[0].styleQA")
            check('identity: off-identity Jordan is regenerated with the named problems, then passes', len(gl)==2 and 'wrong look for Jordan' in gl[1]['prompt'] and 'heavier build' in gl[1]['prompt'] and qa['identityMatch'] is True and qa['attempts']==2, (len(gl),qa))
            jref=await J(pg,"async()=>await getCharacterUrl('Jordan',JORDAN_B64)")
            mref=await J(pg,"async()=>await getCharacterUrl('Marcus',MARCUS_B64)")
            check('identity: a Jordan still gets only his own sheet (no Marcus style ref pulling the face)', jref in gl[0]['image_urls'] and mref not in gl[0]['image_urls'], gl[0]['image_urls'])
            await J(pg,"()=>{sceneData[0].resultURL='';sceneData[0].done=false;}")
            SC['falLog']=[]; i0=cnt.get('idcheck',0)
            SC['vision']=[]; SC['idq']=[{'differences':['rounder face','much larger eyes'],'visible':True,'score':5,'verdict':'off-model'}]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            gl=[json.loads(b) for u,b in SC['falLog'] if 'upload' not in u]
            qa=await J(pg,"()=>sceneData[0].styleQA")
            check('identity: strict model-sheet check catches an off-model face the combined check passed', len(gl)==2 and 'larger eyes' in gl[1]['prompt'] and qa['identityMatch'] is True and cnt.get('idcheck',0)-i0>=2, (len(gl),qa))
            lu=await J(pg,"""async()=>{ const mk=c=>{ const k=document.createElement('canvas'); k.width=k.height=8; const x=k.getContext('2d'); x.fillStyle=c; x.fillRect(0,0,8,8); return k.toDataURL(); };
              return [await imageLuma(mk('#0a0a0a')), await imageLuma(mk('#e0e0e0')), DARK_LUMA]; }""")
            check('darkness: canvas luma measures dark vs bright stills', lu[0] < lu[2] < lu[1], lu)
            SC['falLog']=[]
            fv=await J(pg,"""async()=>{ setVideoFormat('vertical'); await falImageRequest('kling-o1','p',['https://v3b.fal.media/files/r.png']); const v=[frameAR(), document.getElementById('rs-aspect').value, document.getElementById('fmt-aspect').value]; setVideoFormat('landscape'); return v.concat([frameAR()]); }""")
            body=[json.loads(b or '{}') for u,b in SC['falLog'] if 'kling-image/o1' in u]
            check('format: 9:16 chosen -> stills requested natively vertical and the vertical render preselected', fv==['9:16','vertical','vertical','16:9'] and body and body[-1].get('aspect_ratio')=='9:16', (fv, body[-1:] and body[-1].get('aspect_ratio')))
            fp=await J(pg,"""()=>{ const p='SCENE '+'x '.repeat(1800)+CLIP_IDENTITY_GUARD+' STRICT, previous clip failed: writing appeared — no text at all.'; const r=fitClipPrompt(p); return [r.length, r.startsWith('SCENE'), r.includes('IDENTITY LOCK'), r.includes('no text at all'), fitClipPrompt('short')]; }""")
            check('clip prompt: over-long prompts trimmed under the 2500 limit, keeping scene start, identity guard and redo note', fp[0]<=2450 and fp[1] and fp[2] and fp[3] and fp[4]=='short', fp)
            SC['falLog']=[]
            await J(pg,"async()=>{ await falImageRequest('kling-o1','SCENE '+'y '.repeat(2000),['https://v3b.fal.media/files/r.png']); }")
            body=[json.loads(b or '{}') for u,b in SC['falLog'] if 'kling-image/o1' in u]
            check('image prompt: over-long still prompts trimmed under the fal limit', body and len(body[-1]['prompt'])<=2450, body and len(body[-1]['prompt']))
            lk=await J(pg,"""async()=>{ const keep=sceneData; sceneData=[{line:'1. Jordan locks the box.',tag:'IMAGE',characters:'JORDAN',prompt:'kept prompt',resultURL:'https://v3b.fal.media/files/k.png',resultType:'image'}];
              const seg=segScript; segScript='1. Jordan locks the box.\\n2. Marcus nods.'; await enterSceneGeneration(); const r=[sceneData.length, sceneData[0].tag, sceneData[0].resultURL, sceneData[0].prompt, !!sceneData[0].locked, !!sceneData[1].locked];
              segScript=seg; sceneData=keep; return r; }""")
            check('resume: unchanged beats with media keep their tag, prompt and result (no re-classify spend)', lk==[2,'IMAGE','https://v3b.fal.media/files/k.png','kept prompt',True,False], lk)
            # ── storyteller pipeline stress ──
            for k in SC: SC[k]={'xai':'ok','fal':'ok','el':'ok'}.get(k,0 if k in('delay','falDelay') else None)
            ctx2,pg2,errs2=await newpage(b)
            good=' '.join(['"Hang on," Jordan said, because the transfer had not arrived and rent was due Friday.']*50)
            SC['raq']=['not json at all {{{']
            cnt['readaloud']=0
            await go_review(pg2)
            v_=await J(pg2,"()=>[curScreen,document.getElementById('txed').value.length,document.getElementById('e1').textContent]")
            check('stress: junk read-aloud JSON keeps the script', v_[0]==3 and v_[1]>20, v_)
            SC['raq']=[{'scores':{'flow':5},'problems':['x'],'script':'crypto '+good}]
            await J(pg2,"()=>goTo(1,'left')"); await go_review(pg2)
            check('stress: read-aloud rewrite with "crypto" is rejected', 'crypto' not in (await J(pg2,"()=>document.getElementById('txed').value")).lower())
            SC['raq']=[{'scores':{'flow':6,'cohesion':6,'logic':9,'human':9,'story_pull':9,'accuracy':9},'problems':['jumpy'],'script':good},{'scores':{'flow':9,'cohesion':9,'logic':9,'human':9,'story_pull':9,'accuracy':9},'problems':[],'script':good}]
            cnt['readaloud']=0; await J(pg2,"()=>goTo(1,'left')"); await go_review(pg2)
            check('stress: read-aloud capped at one round (cost cap)', cnt.get('readaloud')==1, cnt.get('readaloud'))
            check('stress: accepted rewrite lands in the editor', (await J(pg2,"()=>document.getElementById('txed').value")).startswith('"Hang on,"'))
            SC['researchFail']=True; cnt['research']=0; await J(pg2,"()=>goTo(1,'left')"); await go_review(pg2)
            check('stress: web research failure falls back and still reaches review', await J(pg2,'()=>curScreen')==3)
            SC['researchFail']=None
            check('lint: leaked planning labels are flagged', await J(pg2,"()=>scriptLint('Jordan hit his trigger moment. The decision point came. '.repeat(3)).issues.some(x=>/labels leaked/.test(x))"))
            check('stress: no page errors', not [e for e in errs2 if 'pageerror' in e], errs2[:3])
            await ctx2.close()
            # ── voice defaults: Bill + eleven_v4, Slow pace ──
            for k in SC: SC[k]={'xai':'ok','fal':'ok','el':'ok'}.get(k,0 if k in('delay','falDelay') else None)
            ctx3,pg3,errs3=await newpage(b)
            await J(pg3,"()=>{finalScript='Card declined. The bank was closed.';selId='v01';goVO();generateVO();}"); await pg3.wait_for_timeout(1500)
            eb=SC.get('elBody') or {}; vs=eb.get('voice_settings',{})
            check('voice: default narrator is Bill', 'pqHfZKP75CvOlQylNhV4' in (SC.get('elURL') or ''), SC.get('elURL'))
            check('voice: default model eleven_v4 via with-timestamps', eb.get('model_id')=='eleven_v4' and (SC.get('elURL') or '').endswith('/with-timestamps'), eb.get('model_id'))
            check('voice: Slow pace speed 0.9, stability 0.5, similarity 0.75', vs.get('speed')==0.9 and abs(vs.get('stability',0)-0.5)<1e-9 and vs.get('similarity_boost')==0.75, vs)
            check('voice: summary shows Bill', 'Bill' in await J(pg3,"()=>document.getElementById('vs-summary').textContent"))
            await J(pg3,"()=>{document.getElementById('el-voice').value='jamal';updateVSSummary();goVO();generateVO();}"); await pg3.wait_for_timeout(1500)
            check('voice: Young Jamal still selectable', '6OzrBCQf8cjERkYgzSg8' in (SC.get('elURL') or ''), SC.get('elURL'))
            check('voice: no page errors', not [e for e in errs3 if 'pageerror' in e], errs3[:3])
            await ctx3.close()
            # ── director pass ──
            for k in SC: SC[k]={'xai':'ok','fal':'ok','el':'ok'}.get(k,0 if k in('delay','falDelay') else None)
            SC['dirOut']={'look':{'lighting':'warm late-afternoon window light','palette':'amber and teal','mood':'quiet worry'},'shots':[{'n':1,'place':'bike shop back office','image':'Jordan at the desk staring at his phone, a crypto chart behind him.','motion':'Jordan lowers the phone; slow push-in.','sfx':'shop bell, distant traffic','overlay':'$212.40 pending since Tuesday morning at nine'},{'n':2,'place':'bike shop back office','image':'Marcus leans in the doorway holding the green notebook.','motion':'gentle pan','sfx':'room tone','overlay':''}]}
            ctxd,pgd,errsd=await newpage(b)
            await J(pgd,"()=>{segScript='1. Jordan checked the payment.\\n2. Marcus walked in.\\n3. The bell rang.';enterSceneGeneration();}"); await pgd.wait_for_timeout(2500)
            sd=await J(pgd,"()=>sceneData.map(x=>({p:x.prompt,sfx:x.sfx,ov:x.overlay,d:!!x.directed,desc:x.sceneDesc,tag:x.tag}))")
            check('director: one call plans the shot list', cnt.get('director',0)>=1 and '[1]' in (SC.get('lastDirector') or '') and '[3]' in (SC.get('lastDirector') or ''), SC.get('lastDirector'))
            check('director: image + shared look applied', sd and sd[0]['d'] and 'warm late-afternoon' in sd[0]['p'] and sd[0]['desc']=='bike shop back office', sd[:1])
            check('director: VIDEO shot carries motion', 'Motion: gentle pan' in sd[1]['p'] if sd[1]['tag']=='VIDEO' else 'Motion:' not in sd[1]['p'], sd[1])
            check('director: sfx + overlay captured, overlay capped at 6 words', sd[0]['sfx']=='shop bell, distant traffic' and len(sd[0]['ov'].split())==6, sd[0])
            check('director: no "crypto" leaks into prompts', all('crypto' not in (x['p'] or '').lower() for x in sd), [x['p'] for x in sd])
            check('director: missing beat falls back to per-beat prompt', sd[2]['p'] and not sd[2]['d'], sd[2])
            SC['dirOut']=None; await ctxd.close()
            ctxd,pgd,errsd=await newpage(b)
            await J(pgd,"()=>{segScript='1. Jordan checked the payment.\\n2. Marcus walked in.';enterSceneGeneration();}"); await pgd.wait_for_timeout(2500)
            sd=await J(pgd,"()=>sceneData.map(x=>({p:x.prompt,d:!!x.directed}))")
            check('director: junk reply falls back for every beat', all(x['p'] and not x['d'] for x in sd), sd)
            check('director: no page errors', not [e for e in errsd if 'pageerror' in e], errsd[:3])
            await ctxd.close()
            # ── overlay-only text ──
            ctxo,pgo,errso=await newpage(b)
            r=await J(pgo,"""()=>{const a={line:'He wrote "check the first four" in the notebook.',characters:'JORDAN',tag:'IMAGE'};
              const b={line:'"Card declined," Dee said.',characters:'JORDAN',tag:'IMAGE'};
              const c={line:'Marcus walked in.',overlay:'one two three four five six seven',characters:'MARCUS',tag:'IMAGE'};
              const p=composeScenePrompt(a,'Jordan at the desk.');
              localStorage.setItem('cfa_overlay_only','0'); const p2=composeScenePrompt(a,'Jordan at the desk.'); localStorage.removeItem('cfa_overlay_only');
              return {noText:p.includes('NO WRITING ANYWHERE'), needs:beatNeedsText(a), ova:beatOverlayText(a), ovb:beatOverlayText(b), ovc:beatOverlayText(c), old:p2.includes('Only the specific words')};}""")
            check('overlay: a writing beat still forbids text in the image', r['noText'] and not r['needs'], r)
            check('overlay: the needed words become the overlay', r['ova']=='check the first four', r)
            check('overlay: plain dialogue gets no overlay', r['ovb']=='', r)
            check('overlay: director overlay capped at 6 words', len(r['ovc'].split())==6, r)
            check('overlay: toggle off restores in-image text', r['old'], r)
            await ctxo.close()
            # ── audit fixes ──
            await J(pg,"()=>{sceneData[0].resultURL='';sceneData[0].done=false;sessionStorage.setItem('cfa_openai_key','sk-test');}")
            SC['falLog']=[]; SC['idq']=[]; o0=cnt.get('oai',0)
            good={'style_score':9,'style_match':True,'has_text':True,'text':['Dromaasra'],'identity':[{'name':'Jordan','visible':True,'score':9}]}
            bad={'style_score':2,'style_match':False,'has_text':True,'text':['x'],'identity':[{'name':'Jordan','visible':False,'score':0,'problems':'photoreal'}]}
            SC['vision']=[dict(good),dict(bad),dict(bad)]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            gl=[json.loads(b) for u,b in SC['falLog'] if 'upload' not in u]
            r=await J(pg,"()=>[sceneData[0].styleQA, sceneData[0].resultModel]")
            check('audit: when every retry fails, the closest-to-model attempt is kept (not the last)', len(gl)>=2 and r[0]['match'] is True and r[0]['identityMatch'] is True, (len(gl),r[0]))
            check('audit: stray writing left on a no-text beat is removed with GPT (remove prompt)', cnt.get('oai',0)-o0==1 and b'REMOVE ALL WRITING' in SC.get('oaiBody',b'') and r[0]['strayText'] is False and 'GPT clean' in (r[1] or ''), (cnt.get('oai',0)-o0, r))
            await J(pg,"()=>{sceneData[0].resultURL='';sceneData[0].done=false;sceneData[0].line='1. Jordan sits at the desk.';}")
            o0=cnt.get('oai',0); SC['idq']=[]
            txt={'style_score':9,'style_match':True,'has_text':True,'text':['EXAM PREPARATION'],'identity':[{'name':'Jordan','visible':True,'score':9}]}
            SC['vision']=[dict(txt),dict(txt),dict(txt),dict(txt),dict(txt),dict(txt)]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            r=await J(pg,"()=>[sceneData[0].styleQA, sceneData[0].resultModel]")
            check('audit2: GPT clean is re-checked; text that survives two passes stays flagged', cnt.get('oai',0)-o0==2 and r[0]['strayText'] is True and 'text remains' in (r[1] or ''), (cnt.get('oai',0)-o0, r))
            await J(pg,"()=>localStorage.setItem('cfa_overlay_only','0')")  # in-image text path (overlay-only off)
            r=await J(pg,"()=>{sceneData[0].line='1. Jordan nearly typed the shop password into the exchange.'; return beatNeedsText(sceneData[0])}")
            await J(pg,"()=>{sceneData[0].resultURL='';sceneData[0].done=false;}")
            o0=cnt.get('oai',0)
            SC['vision']=[{'style_score':9,'style_match':True,'has_text':True,'text':['Jorialam','pasword'],'identity':[{'name':'Jordan','visible':True,'score':9}]},{'style_score':9,'style_match':True,'has_text':True,'text':['password'],'identity':[{'name':'Jordan','visible':True,'score':9}]}]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            body=SC.get('oaiBody',b'').decode('latin1')
            q=await J(pg,"()=>sceneData[0].styleQA")
            check('audit2: on a words beat, gibberish beyond the script line is treated as stray and GPT keeps only script words', (not r or cnt.get('oai',0)-o0==1) and 'ONLY words from this script line' in body and q['strayText'] is False, (r, cnt.get('oai',0)-o0, q, body[:300]))
            await J(pg,"()=>localStorage.removeItem('cfa_overlay_only')")
            r=await J(pg,"()=>deRealize('A dimly lit, cinematic room at night, laptop glowing')")
            check('audit: realism/darkness words are neutralised in still prompts', 'cinematic' not in r and 'dimly' not in r and 'night' not in r and 'glow' not in r, r)
            r=await J(pg,"()=>{const keep=currentScene; sceneData[keep].prompt=sceneData[keep].prompt||'A test prompt'; document.getElementById('s6-prompt').value=''; jumpToScene(keep); return document.getElementById('s6-prompt').value}")
            check('audit: jumping to the scene already on screen still fills its prompt (empty-prompt clip bug)', len(r.strip())>0, r)
            r=await J(pg,"()=>{const oc=window.confirm,D=[];window.confirm=m=>{D.push(m);return false}; sessionStorage.setItem('cfa_render_url','http://127.0.0.1:9');sessionStorage.setItem('cfa_render_token','t'); const u=sceneData[0].resultURL; sceneData[0].resultURL=''; sendToGrokRender(); sceneData[0].resultURL=u; window.confirm=oc; sessionStorage.removeItem('cfa_render_url'); return D}")
            check('audit: sending with scenes missing asks first', len(r)==1 and 'no image or clip' in r[0], r)
            r=await J(pg,"()=>{const save=JSON.stringify(sceneData); sceneData=[{tag:'IMAGE',characters:'JORDAN',resultURL:'u_good',styleQA:{match:true,identityMatch:true}},{tag:'IMAGE',characters:'JORDAN',resultURL:'u_bad',styleQA:{match:false,identityMatch:false}},{tag:'VIDEO',characters:'JORDAN'}]; const v=bestStartFrameFor(2); sceneData=JSON.parse(save); return v}")
            check('audit: a clip never starts from an off-model still', r=='u_good', r)
            # ── API budget trackers ──
            await J(pg,"()=>{localStorage.removeItem('cfa_budget_cfg');localStorage.removeItem('cfa_budget_spent');budgetCfg={};budgetSpent={xai:0,fal:0,eleven:0,openai:0};budgetLive={};}")
            SC['elsub']=None; SC['falbal']='27.0106725'
            r=await J(pg,"async()=>{await refreshLiveBalances(); const f=budgetStatus('fal'),e=budgetStatus('eleven'),x=budgetStatus('xai'); return [f.mode,f.remaining,e.mode,budgetLive.eleven.err||'',x.mode,x.remaining, document.querySelector('#bg-row-fal .bg-mode').textContent, document.querySelector('#bg-row-xai .bg-rem').textContent]}")
            check('budget: fal live balance read from API; ElevenLabs w/o user_read and xAI are not invented', r[0]=='live' and abs(r[1]-27.0106725)<1e-6 and r[2]=='unknown' and 'user_read' in r[3] and r[4]=='unknown' and r[5] is None and r[6]=='LIVE' and r[7]=='not set', r)
            SC['elsub']={'character_count':9000,'character_limit':10000}
            r=await J(pg,"async()=>{await refreshLiveBalances(); const e=budgetStatus('eleven'); return [e.mode,e.remaining,e.threshold,e.low, document.getElementById('budget-badge').style.display]}")
            check('budget: ElevenLabs live quota (chars) with 10% default alert -> low + header badge', r[:4]==['live',1000,1000,True] and r[4]=='', r)
            r=await J(pg,"()=>{document.getElementById('bg-loaded-xai').value='10';document.getElementById('bg-th-xai').value='2';budgetSave('xai'); trackTextSpend(8.5); const x=budgetStatus('xai'); return [x.mode,+x.remaining.toFixed(2),x.low, JSON.parse(localStorage.getItem('cfa_budget_cfg')).xai.loaded, document.getElementById('budget-banner').style.display, document.querySelector('#bg-row-xai .bg-mode').textContent]}")
            check('budget: manual xAI balance tracks tool spend, persists, labelled MANUAL, banner when low', r==['manual',1.5,True,10,'','MANUAL'], r)
            r=await J(pg,"()=>{trackSpend(0.06,'openai'); trackSpend(0.04); return [budgetSpent.openai,budgetSpent.fal]}")
            check('budget: GPT text spend goes to OpenAI, image spend to fal', r==[0.06,0.04], r)
            r,d=await J(pg,"()=>{const oc=window.confirm, D=[]; window.confirm=m=>{D.push(m);return false}; const r=[budgetPreflight('xai',3,'the Grok final edit'), budgetPreflight('fal',1,'x'), budgetPreflight('openai',99,'y')]; window.confirm=oc; return [r,D]}")
            check('budget: pre-flight warns (with reload link) when estimate exceeds what is left; silent when fine or unknown', r==[False,True,True] and len(d)==1 and 'too low' in d[0] and 'console.x.ai' in d[0], (r,d))
            d=await J(pg,"async()=>{const oc=window.confirm, D=[]; window.confirm=m=>{D.push(m);return false}; if(!finalScript) finalScript='x'.repeat(1200); await generateVO(); window.confirm=oc; return D}")
            check('budget: voiceover pre-flight uses the live ElevenLabs character quota', any('ElevenLabs' in x and 'chars' in x for x in d), d)
            await J(pg,"()=>{localStorage.removeItem('cfa_budget_cfg');budgetCfg={};budgetLive={};renderBudgetUI();}")
            await J(pg,"()=>{sceneData[0].resultURL='';}")
            SC['falLog']=[]; SC['vision']=[dict(off),dict(off),dict(off)]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(300)
            check('identity: retry cap holds (3 tries) and the miss is recorded', len([u for u,b in SC['falLog'] if 'upload' not in u])==3 and await J(pg,"()=>sceneData[0].styleQA.identityMatch")==False)
            SC['vision']=[]
            r=await J(pg,"()=>[Object.keys(RECURRING_CAST).join(','),!!RECURRING_CAST.Priya.b64,castInScene({line:'Priya hands over the package.'}).join(',')]")
            check('cast: Priya is a regular with a same-style reference sheet', r==['Dee,Okafor,Priya',True,'Priya'], r)
            await J(pg,"()=>{sceneData=window.__sd;}")
            SC['falLog']=[]
            await J(pg,"()=>{currentScene=2;loadScene(2);}"); await pg.wait_for_timeout(1500)
            await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(1500)
            log=[(u,json.loads(b or '{}')) for u,b in SC['falLog'] if 'upload' not in u]
            ok=len(log)==2 and 'kling-image/o1' in log[0][0] and log[0][1].get('image_urls') and 'image-to-video' in log[1][0]
            check('continuity: Marcus clip with no Marcus still gets a reference start frame, then image-to-video', ok, [u[-40:] for u,_ in log])
            check('continuity: video result stored', await J(pg,"()=>!!sceneData[2].resultURL && sceneData[2].autoStartFrame"))
            # ── clip check: every clip frame-checked, Kling O1 with start+end locked, redo on drift ──
            await J(pg,"()=>{setVideoModel('kling-o1v'); sceneData[2].resultURL=''; sceneData[2].done=false; currentScene=2; loadScene(2);}"); await pg.wait_for_timeout(800)
            SC['falLog']=[]; v0=cnt.get('vision',0)
            drift={'style_score':9,'style_match':True,'has_text':False,'text':[],'identity':[{'name':'Marcus','visible':True,'score':3,'problems':'face turned into a different man'}]}
            SC['vision']=[dict(drift)]
            await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(4000)
            log=[(u,json.loads(b or '{}')) for u,b in SC['falLog'] if 'upload' not in u]
            q=await J(pg,"()=>sceneData[2].clipQA")
            vids=[b for u,b in log if 'o1/image-to-video' in u]
            check('clip: Kling O1 image-to-video is the default, with start AND end frame locked to the still and an identity-lock guard', len(vids)>=1 and vids[0].get('start_image_url') and vids[0].get('end_image_url')==vids[0].get('start_image_url') and 'IDENTITY LOCK' in vids[0]['prompt'], [u[-40:] for u,_ in log])
            check('clip: start, middle and end frames are each style/identity/logic checked (not just the start still)', q and len(q.get('frames',[]))==3 and cnt.get('vision',0)-v0>=6, q)
            check('clip: identity drift mid-clip triggers one redo naming the problem; the passing clip is kept', len(vids)==2 and 'morphed mid-clip' in vids[1]['prompt'] and q['attempts']==2 and q['identityMatch'] is True, (len(vids), q and q.get('attempts')))
            # stray writing in a clip: start still cleaned with GPT, then one redo from the cleaned still
            await J(pg,"()=>{sessionStorage.setItem('cfa_openai_key','sk-test'); sceneData[2].resultURL=''; sceneData[2].done=false; currentScene=2; loadScene(2);}"); await pg.wait_for_timeout(800)
            SC['falLog']=[]; o1=cnt.get('oai',0)
            SC['vision']=[{'style_score':9,'style_match':True,'has_text':True,'text':['OPEN 24H'],'identity':[{'name':'Marcus','visible':True,'score':9}]}]
            await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(5000)
            vids=[json.loads(b) for u,b in SC['falLog'] if 'o1/image-to-video' in u]
            q=await J(pg,"()=>sceneData[2].clipQA")
            check('clip: stray writing -> start still GPT-cleaned, clip regenerated from it, clean clip kept', len(vids)==2 and vids[1]['start_image_url']!=vids[0]['start_image_url'] and 'no text at all' in vids[1]['prompt'] and cnt.get('oai',0)>o1 and q['strayText'] is False and q['cleanedStart'] is True, (len(vids), q and {k:q.get(k) for k in ('strayText','cleanedStart','attempts','checkErr')}))
            lg=await J(pg,"""()=>{ const p=[{logicOk:false,logicProblems:['x']},{logicOk:true},{logicOk:true}]; return [p.filter(f=>!f.logicOk).length<2, STYLE_QA_SYS.includes('tread alone never makes a car tyre')]; }""")
            check('logic: bicycle-tyre guidance in the QA prompt; one odd frame does not fail a clip', lg==[True,True], lg)
            await J(pg,"()=>{sceneData[2].characters='NONE'; sceneData[2].resultURL=''; sceneData[2].savedStartFrameURL=''; sceneData[2].autoStartFrame=false; sceneData.forEach((x,k)=>{ if(k<2){ x._r=x.resultURL; x.resultURL=''; } }); currentScene=2; loadScene(2); sceneRefs['startframe']=null; setDuration(4);}"); await pg.wait_for_timeout(800)
            SC['falLog']=[]; SC['vision']=[]
            await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(4000)
            log=[u for u,b in SC['falLog'] if 'upload' not in u]
            e6=await J(pg,"()=>document.getElementById('e6').textContent")
            bd=[json.loads(b) for u,b in SC['falLog'] if 'o1/image-to-video' in u]
            check('clip: a concept clip with no earlier still gets a style-anchored start frame, then Kling O1 at 5 s (start-only clips must be 5/10 s)', len(log)==2 and 'kling-image/o1' in log[0] and 'o1/image-to-video' in log[1] and 'Duration' not in e6 and bd and bd[0]['duration']=='5' and 'end_image_url' not in bd[0], (log, e6, bd))
            await J(pg,"()=>{sceneData[2].characters='MARCUS'; sceneData.forEach((x,k)=>{ if(k<2) x.resultURL=x._r; });}")
            # ── scene logic ──
            r=await J(pg,"()=>composeScenePrompt({line:'Jordan trues a wheel at the Spoke & Chain workbench.',characters:'JORDAN'},'Jordan at the workbench')")
            check('logic: bike-shop prompts carry the bible prop list and ban car tyres', 'bicycle wheels' in r and 'NEVER SHOW: car tyres' in r and 'SCENE LOGIC' in r, r[:300])
            await J(pg,"()=>{window.__sd2=sceneData; sceneData=[{line:'1. Jordan trues a wheel at the Spoke & Chain workbench.',tag:'IMAGE',characters:'NONE',prompt:'workbench close-up',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''}];}")
            SC['falLog']=[]
            SC['vision']=[{'style_score':9,'style_match':True,'has_text':False,'text':[],'logic_ok':False,'logic_problems':['car tyre on the workbench — should be a bicycle wheel']}]
            await J(pg,"async()=>{await generateAllImages();}"); await pg.wait_for_timeout(400)
            gl=[json.loads(b)['prompt'] for u,b in SC['falLog'] if 'upload' not in u]
            qa=await J(pg,"()=>sceneData[0].styleQA")
            check('logic: a still with car tyres in the bike shop is regenerated with the problem named, then passes', len(gl)==2 and 'car tyre on the workbench' in gl[1] and qa['logicOk'] is True, (len(gl), qa))
            body=SC.get('lastVisionIntro','')
            check('logic: the vision check is told the line, setting and banned props', 'Spoke & Chain' in body and 'car tyres' in body, body[:300])
            await J(pg,"()=>{sceneData=window.__sd2;}")
            r=await J(pg,"""async()=>{finalScript='Jordan sat in the bike shop. Marcus brought a printout.';selId='v02';
              sceneData=[{line:'1. Jordan sat in the bike shop.',tag:'IMAGE',characters:'JORDAN',prompt:'',sceneDesc:'bike shop workbench'},{line:'2. A chart.',tag:'IMAGE',characters:'NONE',prompt:'',sceneDesc:''},{line:'3. Dee laughs.',tag:'IMAGE',characters:'NONE',prompt:'',sceneDesc:''}];
              const n=sceneContextNote(1); const keep=llmComplete; let sent='';
              llmComplete=async(o)=>{sent=o.user; return {text:'Marcus points at a chart on the shop laptop.\\nSCENE: bike shop'}};
              await generatePromptForScene(1); llmComplete=keep;
              return {n, sent, ch:sceneData[1].characters, d:sceneContextNote(2)}}""")
            check('prompts: story context, neighbours, setting and on-screen cast sent with each beat', all(k in r['sent'] for k in ['Story: Jordan sat in the bike shop','Previous beat: 1. Jordan','Next beat: 3. Dee','no Marcus and no Jordan','bike shop workbench']), r['n'])
            check('prompts: concept beat whose prompt shows Marcus switches to his reference', r['ch']=='MARCUS', r['ch'])
            r2=await J(pg,"""()=>[promptOnScreenCast("Dee scrolls while Jordan\u2019s single line is visible."),promptOnScreenCast("A pair of hands, belonging to someone not Marcus or Jordan, turns a page."),promptOnScreenCast("Marcus slides the card to Jordan."),promptOnScreenCast("Jordan's notebook and Marcus's printout on the table.")]""")
            check('prompts: cast guard ignores possessives and negations', r2==['NONE','NONE','BOTH','NONE'], r2)
            check('prompts: recurring cast named in context', 'also Dee' in r['d'], r['d'][-200:])
            check('pace: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            await ctx.close()

        if want('dialogue'):
            for k in SC: SC[k]={'xai':'ok','fal':'ok','el':'ok'}.get(k,0 if k in('delay','falDelay') else None)
            LOCK={'NARRATOR':'pqHfZKP75CvOlQylNhV4','JORDAN':'bIHbv24MWmeRgasZH58o','MARCUS':'nPczCjzI2devNBz1zQrb','DEE':'EXAVITQu4vr4xnSDxMaL','PRIYA':'XrExE9yKIg1WjnnlVkGX','OKAFOR':'JBFqnCBsd6RMkjVDRZzb'}
            # FULL NARRATION (default): Bill voices every line, no lip sync, no ai-avatar calls
            ctx,pg,errs=await newpage(b,pre="localStorage.setItem('cfa_format','dialogue');")
            fn=await J(pg,"""()=>{const S='JORDAN: It is gone. All of it.\\nNARRATOR: Four thousand dollars, and the landlord wanted it by noon.\\nMARCUS: Sure of what?\\nNARRATOR: Jordan held up the phone.\\nNARRATOR: Day one, nothing.\\nNARRATOR: Day two, still nothing.\\nJORDAN: Found it.';
              return {def:narrMode(), full:fullNarr(), talk:talkOn(), rules:/FULL NARRATION/.test(dialogueRules())&&/in medias res/.test(dialogueRules()),
                st:{rules:/STORY STRUCTURE/.test(dialogueRules())&&/Escalate/.test(dialogueRules())&&/discovered at the climax/.test(dialogueRules())&&!dialogueRules().includes('Three days earlier, ...'),
                  fb:['NARRATOR: Three hours earlier, Jordan had been fine.','NARRATOR: Two days before, nobody cared.','NARRATOR: It had started that morning.','NARRATOR: Let me take you back.'].map(l=>structureLint(parseDialogue('JORDAN: It is gone.\\n'+l)).some(x=>/Flashback/.test(x))),
                  ok:structureLint(parseDialogue('JORDAN: It is gone.\\nNARRATOR: Four thousand dollars, due by noon.\\nMARCUS: Who has the key?\\nJORDAN: Nobody.\\nNARRATOR: He tried the bank.\\nJORDAN: Closed.')),
                  nostake:structureLint(parseDialogue('JORDAN: Oh no.\\nNARRATOR: Jordan froze.\\nMARCUS: What?\\nJORDAN: Look.\\nNARRATOR: He pointed.\\nMARCUS: Hm.')).some(x=>/stakes/.test(x)),
                  upfront:structureLint(parseDialogue('JORDAN: It is gone, all $400.\\nMARCUS: A seed phrase is basically when twelve words unlock your wallet.\\nJORDAN: So?\\nNARRATOR: He waited.\\nJORDAN: And?\\nMARCUS: Wait.\\nJORDAN: Fine.\\nNARRATOR: Later.\\nJORDAN: Ok.')).some(x=>/explained up front/.test(x)),
                  laterOk:!structureLint(parseDialogue('JORDAN: Gone, $400.\\nNARRATOR: By noon.\\nMARCUS: Hm.\\nJORDAN: What?\\nNARRATOR: x\\nNARRATOR: y\\nNARRATOR: z\\nNARRATOR: w\\nNARRATOR: Three days earlier was a memory.')).some(x=>/Flashback/.test(x))},
                lint:dialogueLint(S).filter(x=>/cold open|montage|in a row/i.test(x)),
                badCold:dialogueLint('NARRATOR: It was a long day for everyone.\\nJORDAN: hi').some(x=>/Full-narration cold open/.test(x)),
                four:dialogueLint('JORDAN: a\\nNARRATOR: b\\nJORDAN: c\\nMARCUS: d\\nJORDAN: e\\nMARCUS: f').some(x=>/Four character lines/.test(x)),
                noMont:dialogueLint('JORDAN: a\\nNARRATOR: b\\nMARCUS: c').some(x=>/milestone montage/.test(x)),
                fp:dialogueLint('JORDAN: a\\nNARRATOR: I saw it.\\nMARCUS: c').some(x=>/first person/.test(x)),
                opt:[...document.querySelectorAll('#sm-narr option')].map(o=>o.value)}}""")
            check('full narration: default mode, lip sync off, rules in prompt', fn['def']=='full' and fn['full'] and not fn['talk'] and fn['rules'], fn)
            st=fn['st']
            check('structure: rules demand in medias res, escalation, lesson-at-climax; old "Three days earlier" template gone', st['rules'], st)
            check('structure: flashback openers flagged (hours earlier / days before / it had started / take you back)', st['fb']==[True,True,True,True], st['fb'])
            check('structure: forward cold open with concrete stakes passes clean', st['ok']==[], st['ok'])
            check('structure: missing stakes and up-front lesson explainer flagged', st['nostake'] and st['upfront'], st)
            check('structure: a time phrase after the opening lines is not flagged', st['laterOk'], st)
            check('full narration: lint accepts in-media-res cold open + montage', fn['lint']==[], fn['lint'])
            check('full narration: lint flags narrator cold open, 4 unattributed lines, no montage, narrator first person', fn['badCold'] and fn['four'] and fn['noMont'] and fn['fp'], fn)
            check('full narration: Hybrid and Sparse still selectable', fn['opt']==['full','sparse','hybrid'], fn['opt'])
            lk=await J(pg,"""()=>{const r={def:look3d(), ref3d:MARCUS_B64===MARCUS_B64_3D&&DEE_B64===DEE_B64_3D&&RECURRING_CAST.Dee.b64===DEE_B64_3D, qa3:/3D animated/.test(STYLE_QA_SYS)&&!/the same flat 2D cartoon/.test(STYLE_QA_SYS)&&/3D animated/.test(SYS_KLING_VIDEO)&&!/flat 2D cartoon illustration/.test(STYLE_SPEC),
                idw:/Wardrobe and hair/.test(IDENTITY_QA_SYS), dir:/OFF-CENTER/.test(DIRECTOR_RESILIA)&&/in media res/.test(DIRECTOR_RESILIA)&&/hoodie/.test(DIRECTOR_RESILIA)};
              localStorage.setItem('cfa_look','2d'); applyLook(); r.back2d=MARCUS_B64===MARCUS_B64_2D&&/flat 2D cartoon/.test(STYLE_QA_SYS)&&/2D illustrated/.test(SYS_KLING_IMAGE);
              localStorage.removeItem('cfa_look'); applyLook(); r.again3d=MARCUS_B64===MARCUS_B64_3D&&/3D animated/.test(STYLE_QA_SYS);
              r.opts=[...document.querySelectorAll('#sm-look option')].map(o=>o.value); return r}""")
            check('3D look: default, 3D model sheets for all five characters, QA/prompt text swapped', lk['def'] and lk['ref3d'] and lk['qa3'], lk)
            check('3D look: identity QA checks wardrobe/hair; director close-ups, off-centre, in media res, wardrobe lock', lk['idw'] and lk['dir'], lk)
            check('3D look: 2D kept behind the Look setting and switches cleanly both ways', lk['back2d'] and lk['again3d'] and lk['opts']==['3d','2d'], lk)
            script="JORDAN: It's gone. The whole payment.\nNARRATOR: An hour earlier, Jordan had pressed send.\nMARCUS: Sent is not arrived.\nDEE: Nothing on my phone.\nNARRATOR: Ten minutes passed. Then twenty.\nPRIYA: Check the confirmations.\nJORDAN: Twelve confirmations. It's there."
            SC['elCalls']=[]; SC['elReal']=True
            await J(pg,"(t)=>{finalScript=t;segScript=dialogueSegments(t);goVO();}",script)
            await J(pg,"()=>generateVO()")
            await pg.wait_for_function("()=>document.getElementById('s5-result').style.display!=='none'||document.getElementById('e5').textContent",timeout=20000)
            calls=SC['elCalls']
            check('full narration: every line (characters too) voiced by Bill, eleven_v4, slow 0.9', len(calls)==7 and all('/text-to-speech/pqHfZKP75CvOlQylNhV4/' in c[0] and c[1]['model_id']=='eleven_v4' and c[1]['voice_settings']['speed']==0.9 for c in calls), [(c[0].split('/')[-2],c[1]['text'][:16]) for c in calls])
            check('full narration: characters quoted with their exact words', sorted(c[1]['text'] for c in calls)==sorted(l.split(': ',1)[1] for l in script.split('\n')))
            SC['elReal']=False
            await go_scenes(pg)
            cl=await J(pg,"()=>({tags:sceneData.map(s=>s.tag),cast:sceneData.map(s=>s.characters),sum:document.getElementById('s6-class-summary').textContent})")
            check('full narration: no TALK beats, no lip-sync cost', 'TALK' not in cl['tags'] and 'talking' not in cl['sum'], cl)
            check('full narration: character beats still carry their cast for consistency', cl['cast'][0]=='JORDAN' and cl['cast'][2]=='MARCUS', cl['cast'])
            SC['falLog']=[]
            await J(pg,"()=>startSceneGeneration()"); await pg.wait_for_timeout(400)
            for i in (0,2):
                await J(pg,"(i)=>{jumpToScene(i);}",i); await pg.wait_for_timeout(300)
                await J(pg,"()=>generateScene()")
                await pg.wait_for_function("(i)=>sceneData[i].resultURL||document.getElementById('e6').textContent",arg=i,timeout=20000)
            r=await J(pg,"()=>({lip:sceneData.map(s=>!!s.lipsync),e:document.getElementById('e6').textContent})")
            av=[x for x in SC['falLog'] if 'ai-avatar' in x[0]]
            gen=' '.join(x[1] for x in SC['falLog'])
            check('full narration: ZERO calls to fal-ai/kling-video/ai-avatar', not av and not any(r['lip']) and len(SC['falLog'])>0, (len(av),len(SC['falLog']),r))
            check('full narration: shot prompts keep mouths closed (acting shots)', 'mouth closed' in gen or 'mouths closed' in gen, gen[:300])
            await ctx.close()
            ctx,pg,errs=await newpage(b,pre="localStorage.setItem('cfa_format','dialogue');localStorage.setItem('cfa_narr_mode','hybrid');")
            check('dialogue: default format is dialogue', await J(pg,"()=>{localStorage.removeItem('cfa_format');const f=scriptFormat();localStorage.setItem('cfa_format','dialogue');return f}")=='dialogue')
            vl=await J(pg,"()=>Object.fromEntries(Object.entries(voiceLock()).map(([k,v])=>[k,v.voiceId]))")
            check('voice lock: registry map is exactly the locked series voices', vl==LOCK, vl)
            check('voice lock: registry is frozen', await J(pg,"()=>{try{CHARACTER_REGISTRY.speakers.JORDAN.voiceId='x';}catch(e){} return CHARACTER_REGISTRY.speakers.JORDAN.voiceId}")==LOCK['JORDAN'])
            t1=await J(pg,"""()=>{localStorage.setItem('cfa_voice_lock_v1',JSON.stringify({voices:{JORDAN:'AAAAAAAAAAAAAAAAAAAA'}}));const a=voiceLock().JORDAN.voiceId;
              localStorage.setItem('cfa_voice_lock_v1',JSON.stringify({deliberate:true,voices:{JORDAN:'bad id!'}}));const b=voiceLock().JORDAN.voiceId;
              localStorage.setItem('cfa_voice_lock_v1','{not json');const c=voiceLock().JORDAN.voiceId;
              localStorage.setItem('cfa_voice_lock_v1',JSON.stringify({deliberate:true,voices:{JORDAN:'AAAAAAAAAAAAAAAAAAAA'}}));const d=voiceLock().JORDAN.voiceId;
              localStorage.removeItem('cfa_voice_lock_v1');return [a,b,c,d,voiceLock().JORDAN.voiceId]}""")
            check('voice lock: only a deliberate Settings save with a valid id overrides; junk ignored', t1==[LOCK['JORDAN'],LOCK['JORDAN'],LOCK['JORDAN'],'AAAAAAAAAAAAAAAAAAAA',LOCK['JORDAN']], t1)
            await J(pg,"()=>{openSettings();}")
            ui=await J(pg,"()=>({f:document.getElementById('sm-format').value,lock:document.getElementById('sm-voice-lock').textContent,inputs:document.querySelectorAll('#sm-voice-lock input').length})")
            check('voice lock: settings panel shows locked voices read-only until unlocked', ui['f']=='dialogue' and 'Brian' in ui['lock'] and ui['inputs']==0, ui)
            await J(pg,"()=>{document.getElementById('sm-voice-unlock').checked=true;renderVoiceLockUI();}")
            check('voice lock: unlock shows editable ids', await J(pg,"()=>document.querySelectorAll('#sm-voice-lock input').length")==6)
            await J(pg,"()=>{document.getElementById('sm-voice-unlock').checked=false;renderVoiceLockUI();closeSettings&&closeSettings();}")
            # lint
            good="\n".join(["MARCUS: The $400 payment says sent, but Dee has nothing yet.","JORDAN: Wait, so where is it right now?"]+[("JORDAN: " if i%2 else "MARCUS: ")+"word "*13 for i in range(50)]+["NARRATOR: Later that night, the shop was quiet again."])
            li=await J(pg,"(t)=>{localStorage.setItem('cfa_narr_mode','sparse');const r=dialogueLint(t);localStorage.removeItem('cfa_narr_mode');return r}",good)
            check('dialogue lint: clean tagged script passes', li==[], li)
            u=await J(pg,"""()=>{
              const L=t=>parseDialogue(t);
              const narr=voiceLint(L('NARRATOR: I remember when Jordan lost it.\\nJORDAN: Wait. Gone?'));
              const bleed=voiceLint(L('JORDAN: check the network fee first.\\nMARCUS: Always check the network fee first, okay?'));
              const hints=voiceHints(L('JORDAN: So I went to the shop and the card got declined again and again today.\\nJORDAN: Then I tried my other card and it also failed at the register.\\nJORDAN: And I still have no idea what is going on with this.\\nMARCUS: Okay.\\nMARCUS: Fine.\\nMARCUS: Sure.\\nPRIYA: Fees add up.\\nPRIYA: Watch them.'));
              const pr=primerFor('v11');
              const acc=parseAccuracy('{"issues":[{"kind":"stiff","line":"As you know","problem":"both know","fix":"cut"},{"kind":"style","line":"x","problem":"y","fix":"z"}]}');
              return {narr:narr.some(x=>/first person/.test(x)), bleed:bleed.some(x=>/both say/.test(x)), hints:hints.length, hl:hints.join('|'), pr:pr.length>200&&/declined|logic/i.test(pr),
                acc:acc&&acc.length===1&&acc[0].kind==='stiff', wc:wordCount('JORDAN: [sighs] Wait. [short pause] Gone?'),
                tw:stripTagWords([['Wait',0,1],['[sighs]',1,2],['[short',2,3],['pause]',3,4],['ok',4,5]]).map(w=>w[0]).join(' '),
                rules:/SOUNDS LIKE REAL PEOPLE/.test(dialogueRules())&&(()=>{localStorage.setItem('cfa_narr_mode','hybrid');const ok=/HYBRID STRUCTURE/.test(dialogueRules())&&dialogueLint('JORDAN: hi there\\nMARCUS: yo').some(x=>/Hybrid cold open/.test(x));localStorage.setItem('cfa_narr_mode','sparse');const sp=!/HYBRID/.test(dialogueRules());localStorage.removeItem('cfa_narr_mode');return ok&&sp&&/FULL NARRATION/.test(dialogueRules())&&/animated wide/.test(SYS_DIRECTOR);})()&&/stiff/.test(SYS_ACCURACY)&&/ALWAYS MOVING/.test(SYS_DIRECTOR)&&/LISTENER REACTION/.test(SYS_DIRECTOR)};
            }""")
            check('voice lint: narrator first person flagged', u['narr'], u)
            check('voice lint: the same phrase in two characters\' mouths flagged', u['bleed'], u)
            check('voice hints: long Jordan, Marcus never asks back, Priya without numbers', u['hints']>=3, u['hl'])
            check('primer: v11 gets its verified facts + story-logic section', u['pr'], u)
            check('accuracy critic: parses fact/logic/narrator/voice/stiff issues, drops unknown kinds', u['acc'], u)
            check('v4 audio tags: not counted as words, never reach captions', u['wc']==2 and u['tw']=='Wait ok', u)
            check('prompts: natural-dialogue rules, stiff-line critic, always-moving + listener-reaction director rules', u['rules'], u)
            m=await J(pg,"""()=>{
              const keep=sceneData; selId=selId||'v02';
              sceneData=[{line:'1. NARRATOR: The shop was quiet.',tag:'IMAGE',origTag:'IMAGE',sceneDesc:'corner shop'},{line:'2. JORDAN: Wait—',tag:'TALK',sceneDesc:'corner shop'},{line:'3. NARRATOR: Rain hit the window.',tag:'VIDEO',origTag:'VIDEO',sceneDesc:'Corner shop!'},{line:'4. NARRATOR: Later.',tag:'IMAGE',origTag:'IMAGE',sceneDesc:'street'}];
              localStorage.removeItem(motionKey());
              const def=motionMode(); applyMotionMode(); const kbTags=sceneData.map(x=>x.tag).join(',');
              safeSetItem(motionKey(),'full'); applyMotionMode(); const fullTags=sceneData.map(x=>x.tag).join(',');
              const f=motionCostEstimate('full').usd, mx=motionCostEstimate('mixed').usd;
              safeSetItem(motionKey(),'mixed'); applyMotionMode(); const mixTags=sceneData.map(x=>x.tag).join(',');
              const other=(()=>{ const s=selId; selId='v99'; const r=motionMode(); selId=s; return r; })();
              const sp=samePlace(sceneData[0],sceneData[2]) && !samePlace(sceneData[0],sceneData[3]);
              localStorage.removeItem(motionKey()); sceneData=keep;
              return {def,kbTags,fullTags,mixTags,f,mx,other,sp};
            }""")
            check('motion: key-beat default; fully animated makes every non-talking beat a clip', m['def']=='keybeat' and m['fullTags']=='VIDEO,TALK,VIDEO,VIDEO' and m['kbTags'].split(',')[0]=='VIDEO' and m['kbTags'].split(',')[-1]=='VIDEO', m)
            ce=await J(pg,"""()=>{ const keep=sceneData; sceneData=[{line:'1. NARRATOR: a',tag:'IMAGE'},{line:'2. NARRATOR: b',tag:'IMAGE'}];
              const k0=safeGetItem('cfa_style_check'); safeSetItem('cfa_style_check','1'); const on=motionCostEstimate('mixed');
              safeSetItem('cfa_style_check','0'); const off=motionCostEstimate('mixed'); if(k0==null) localStorage.removeItem('cfa_style_check'); else safeSetItem('cfa_style_check',k0);
              sceneData=keep; return {on:on.usd, off:off.usd, per:MODEL_COSTS.image[selectedImageModel]||0.04}; }""")
            check('cost estimate: stills include ~3.3 style-check tries when the style check is on, 1 try when off', abs(ce['on']-round(2*ce['per']*3.3,2))<0.011 and abs(ce['off']-round(2*ce['per'],2))<0.011, ce)
            check('motion: mixed restores the classifier mix', m['mixTags']=='IMAGE,TALK,VIDEO,IMAGE', m)
            check('motion: per-episode choice, full costs more than mixed', m['other']=='keybeat' and m['f']>m['mx']>0, m)
            check('motion: same-place continuity match ignores case/punctuation', m['sp'], m)
            bad="Jordan looked at the screen for a long while and wondered what had gone wrong with it.\nBOB: Hi there.\nNARRATOR: "+("calm "*400)+"\nMARCUS: "+("long "*45)+"\nMARCUS: one\nMARCUS: two"
            li=await J(pg,"(t)=>{localStorage.setItem('cfa_narr_mode','sparse');const r=dialogueLint(t).join(' | ');localStorage.removeItem('cfa_narr_mode');return r}",bad)
            for frag in ['without a speaker tag','Unknown speaker','Too much narration','monologue','Cold open','3 lines in a row','Spoken length']:
                check('dialogue lint flags: '+frag, frag in li, li[:300])
            check('dialogue: word count ignores speaker tags', await J(pg,"()=>wordCount('JORDAN: one two\\nMR. OKAFOR: three')")==3)
            seg=await J(pg,"(t)=>dialogueSegments(t)","JORDAN: Hi.\nMR. OKAFOR: "+"This is a sentence of words. "*10+"\nNARRATOR: End.")
            sl=seg.split('\n')
            check('dialogue segments: one beat per line, long line split, tags kept', len(sl)>=4 and sl[0]=='1. JORDAN: Hi.' and all(re.match(r'^\d+\. (JORDAN|MR\. OKAFOR|NARRATOR): ',l) for l in sl), seg[:300])
            # per-line TTS: every line uses its speaker's locked voice
            await J(pg,"()=>localStorage.setItem('cfa_narr_mode','hybrid')")
            script="NARRATOR: Ten minutes to close.\nJORDAN: I sent it an hour ago!\nMARCUS: Sent is not arrived.\nDEE: Nothing on my phone.\nPRIYA: Check the confirmations.\nMR. OKAFOR: In my day we used cash.\nJORDAN: Twelve confirmations. It's there."
            SC['elCalls']=[]; SC['elReal']=True
            await J(pg,"(t)=>{finalScript=t;segScript=dialogueSegments(t);goVO();}",script)
            await J(pg,"()=>generateVO()")
            await pg.wait_for_function("()=>document.getElementById('s5-result').style.display!=='none'||document.getElementById('e5').textContent",timeout=20000)
            calls=SC['elCalls']; spk=[l.split(':')[0].replace('MR. ','') for l in script.split('\n')]
            ok=len(calls)==7 and all(any(c[0].split('/text-to-speech/')[1].startswith(LOCK[s]) and c[1]['text']==t.split(': ',1)[1] for c in calls) for s,t in zip(spk,script.split('\n')))
            check('LOCKED VOICES: every line voiced with its character\'s locked id', ok, [(c[0].split('/')[-2],c[1]['text'][:20]) for c in calls])
            check('dialogue TTS: eleven_v4, Slow pace (0.9), with-timestamps', all(c[1]['model_id']=='eleven_v4' and c[1]['voice_settings']['speed']==0.9 and c[0].endswith('/with-timestamps') for c in calls))
            vo=await J(pg,"()=>({n:voLines.length,gaps:voLines.map((v,i)=>i?+(v.start-(voLines[i-1].start+voLines[i-1].dur)).toFixed(2):0),mono:voWords.every((w,i)=>!i||w[1]>=voWords[i-1][1]),type:document.getElementById('vo-download').download,ids:voLines.map(v=>v.voiceId),err:document.getElementById('e5').textContent})")
            check('dialogue stitch: WAV with natural gaps (0.6 same / 0.7 change), words monotonic', vo['n']==7 and all(g in (0.6,0.7) for g in vo['gaps'][1:]) and vo['mono'] and vo['type'].endswith('.wav'), vo)
            check('dialogue stitch: stored voice ids match the lock', vo['ids']==[LOCK[s] for s in spk], vo['ids'])
            # a tampered line (voiced with another id) is refused before lip-sync
            # classification → TALK beats, cost estimate, export
            SC['elReal']=False
            await go_scenes(pg)
            cl=await J(pg,"()=>({tags:sceneData.map(s=>s.tag),cast:sceneData.map(s=>s.characters),t:sceneData.map(s=>[s.tStart,s.tEnd]),sum:document.getElementById('s6-class-summary').textContent})")
            check('dialogue: character lines become TALK beats; narrator keeps image/video', cl['tags'][0] in ('IMAGE','VIDEO') and all(t=='TALK' for t in cl['tags'][1:]), cl['tags'])
            check('dialogue: Jordan/Marcus talking shots carry their cast', cl['cast'][1]=='JORDAN' and cl['cast'][2]=='MARCUS', cl['cast'])
            check('dialogue: beat times are the exact line times', all(a is not None and b>a for a,b in cl['t']), cl['t'])
            check('dialogue: lip-sync cost estimate shown', 'talking' in cl['sum'] and '$' in cl['sum'], cl['sum'])
            # talking shot: still + line audio → Kling Avatar v2, identity check
            SC['falLog']=[]
            await J(pg,"()=>startSceneGeneration()"); await pg.wait_for_timeout(400)
            await J(pg,"()=>{jumpToScene(1);}"); await pg.wait_for_timeout(300)
            await J(pg,"()=>generateScene()"); 
            await pg.wait_for_function("()=>sceneData[1].resultURL||document.getElementById('e6').textContent",timeout=20000)
            r=await J(pg,"()=>({url:sceneData[1].resultURL,type:sceneData[1].resultType,lip:sceneData[1].lipsync,still:sceneData[1].talkStill,audio:sceneData[1].lineAudioURL,qa:sceneData[1].clipQA,e:document.getElementById('e6').textContent})")
            av=[x for x in SC['falLog'] if 'ai-avatar' in x[0]]
            avb=json.loads(av[0][1]) if av else {}
            check('lip-sync: Kling AI Avatar v2 called with the character still + this line\'s audio', bool(av) and avb.get('image_url','').startswith('https://') and avb.get('audio_url','').startswith('https://'), (len(av),avb.keys(),r['e']))
            check('lip-sync: result stored as lip-synced video, still kept, identity check recorded', r['type']=='video' and r['lip'] and r['still'] and r['url']!=r['still'] and (r['qa'] or {}).get('kind')=='lipsync', r)
            # tampered audio voice id is refused
            msg=await J(pg,"async()=>{const s=sceneData[2]; voLines[2].voiceId='AAAAAAAAAAAAAAAAAAAA'; s.lineAudioURL=''; try{await talkClip(2,s,'https://v3b.fal.media/files/x.png',()=>{});return 'no error'}catch(e){return e.message}}")
            check('LOCKED VOICES: lip-sync refuses a line voiced with a non-locked id', 'locked voice' in msg, msg)
            await J(pg,"()=>{voLines[2].voiceId='"+LOCK['MARCUS']+"'}")
            # export bundle
            z=await J(pg,"""async()=>{const r=await buildFinalEditZip(()=>{}); if(!r) return null; let s=''; const u=r.zip instanceof Blob?new Uint8Array(await r.zip.arrayBuffer()):r.zip; for(let i=0;i<u.length;i+=8192) s+=String.fromCharCode.apply(null,u.subarray(i,i+8192)); return btoa(s);}""")
            import zipfile, io
            bj=json.loads(zipfile.ZipFile(io.BytesIO(base64.b64decode(z))).read('bundle.json')) if z else {}
            segs=bj.get('segments',[])
            check('bundle: speaker + locked voice_id on every segment', segs and all(g['voice_id']==LOCK[g['speaker']] for g in segs), [(g.get('speaker'),g.get('voice_id')) for g in segs])
            check('bundle: talking shot exported as lipsync, text without tag', segs and segs[1]['mediaType']=='lipsync' and not segs[1]['text'].startswith('JORDAN'), segs[1] if segs else None)
            check('bundle: format, music style and voice lock recorded', bj.get('format_type')=='dialogue' and bj.get('musicStyle')=='cinematic' and bj.get('voiceLock')==LOCK, {k:bj.get(k) for k in ('format_type','musicStyle')})
            check('bundle: segment start = line audio start (lip-sync anchor)', segs and abs(segs[1]['start']-await J(pg,"()=>voLines[1].start"))<1e-6)
            # resume keeps TALK + lip-sync fields + director fields; drops lines with a non-locked voice id
            await J(pg,"()=>{sceneData[0].sfx='door bell';sceneData[0].overlay='Sent is not arrived';saveWorkflowState();}")
            st=await J(pg,"()=>{const s=getSavedWorkflowState();return {tag:s.sceneData[1].tag,lip:s.sceneData[1].lipsync,still:!!s.sceneData[1].talkStill,sfx:s.sceneData[0].sfx,ov:s.sceneData[0].overlay,vl:s.voLines.length}}")
            check('resume: TALK tag, lip-sync, director sfx/overlay and line timings survive', st=={'tag':'TALK','lip':True,'still':True,'sfx':'door bell','ov':'Sent is not arrived','vl':7}, st)
            st2=await J(pg,"()=>{const raw=JSON.parse(localStorage.getItem(WORKFLOW_STATE_KEY));raw.voLines[1].voiceId='AAAAAAAAAAAAAAAAAAAA';raw.sceneData[0].tag='TALK';localStorage.setItem(WORKFLOW_STATE_KEY,JSON.stringify(raw));const s=getSavedWorkflowState();return {vl:s.voLines.length,t0:s.sceneData[0].tag}}")
            check('resume: a line with a non-locked voice id is dropped; narrator can\'t be TALK', st2['vl']==6 and st2['t0']=='IMAGE', st2)
            # narration format unchanged
            await J(pg,"()=>localStorage.setItem('cfa_format','narration')")
            check('narration format: prompts unchanged, no dialogue rules', await J(pg,"()=>fmtSys('X')==='X' && !/speaker tag/.test(JSON.stringify(scriptLint('A calm story.')))"))
            check("dialogue: no page errors", not [e for e in errs if "favicon" not in e and "Failed to load resource" not in e], errs[:5])
            await ctx.close()
        if want('feedback'):
            import subprocess, tempfile
            fbd=tempfile.mkdtemp(prefix='cfa-fb-'); tok=os.path.join(fbd,'tok'); open(tok,'w').write('fbtest'); os.chmod(tok,0o600)
            env=dict(os.environ, CFA_RENDER_DATA=os.path.join(fbd,'data'), CFA_RENDER_TOKEN_FILE=tok, CFA_RENDER_PORT='8798', CFA_ALLOWED_ORIGINS=_ORIGIN.rstrip('/'))
            svc=subprocess.Popen(['python3',os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','tools','render','service.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            await asyncio.sleep(1.2)
            try:
                ctx,pg,errs=await newpage(b,pre="sessionStorage.setItem('cfa_render_url','http://127.0.0.1:8798');sessionStorage.setItem('cfa_render_token','fbtest');")
                await ctx.route(re.compile(r'http://127\.0\.0\.1:8798/.*'),lambda r: asyncio.ensure_future(r.continue_()))
                st=await J(pg,"()=>{fbOpen();return {n:document.getElementById('fb-step').options.length,step:document.getElementById('fb-step').value,kinds:[...document.getElementById('fb-kind').options].map(o=>o.value)}}")
                check('feedback: box covers all 11 steps, defaults to the current step, both kinds', st=={'n':11,'step':'research','kinds':['episode','tool']}, st)
                fs=await J(pg,"()=>{const o=[...document.getElementById('fb-step').options];const r={full:o.map(x=>x.value),lab:o.find(x=>x.value==='voices').textContent};fbToggle(false);const t0=window.talkOn;window.talkOn=()=>true;fbOpen();r.hyb=[...document.getElementById('fb-step').options].map(x=>x.value);fbToggle(false);window.talkOn=t0;fbOpen();r.back=[...document.getElementById('fb-step').options].map(x=>x.value);return r}")
                check('feedback: full narration shows a Narration step (no Lip-sync) and Bill voice; Hybrid restores Lip-sync', 'narration' in fs['full'] and 'lipsync' not in fs['full'] and 'Bill' in fs['lab'] and 'lipsync' in fs['hyb'] and 'narration' not in fs['hyb'] and fs['back']==fs['full'], fs)
                rb=await J(pg,"()=>{const g='chosenfewacademy.github.io';return [renderUrlBlocked('http://127.0.0.1:8787',g),renderUrlBlocked('http://localhost:8787/',g),renderUrlBlocked('http://192.168.1.5:8787',g),renderUrlBlocked('https://x.ngrok-free.dev',g),renderUrlBlocked('http://127.0.0.1:8787','127.0.0.1'),renderUrlBlocked('not a url',g)]}")
                check('feedback/render: loopback/LAN render URL is refused from github.io (Chrome PNA), tunnel URL and local dev allowed', rb==[True,True,True,False,False,False], rb)
                mp=await J(pg,"()=>{const o={};const c=curScreen;for(const n of [1,2,3,4,5]){curScreen=n;o[n]=fbCurrentStep();}curScreen=c;return o}")
                check('feedback: each screen maps to its step', mp=={'1':'research','2':'script','3':'script','4':'shotlist','5':'voices'}, mp)
                await J(pg,"()=>{document.getElementById('fb-comment').value='';return fbSubmit()}")
                check('feedback: empty comment is refused', 'comment' in await J(pg,"()=>document.getElementById('fb-err').textContent"))
                await J(pg,"""()=>{document.getElementById('fb-step').value='script';document.getElementById('fb-kind').value='tool';fbRating=4;document.getElementById('fb-comment').value='Hooks should name the stakes in line 1 <img src=x onerror=window.__x=1>';return fbSubmit()}""")
                await pg.wait_for_timeout(300)
                st=await J(pg,"()=>({th:document.getElementById('fb-thanks').textContent,vis:document.getElementById('fb-thanks').style.display,items:fbItems().map(i=>[i.step,i.kind,i.rating,i.status]),list:document.getElementById('fb-list').textContent,x:!!window.__x,imgs:document.querySelectorAll('#fb-list img').length})")
                check('feedback: thank-you message exactly as specified', st['th']=="Thanks Chris, your feedback was received. Changes may take up to 24 hours. You'll see a Changes ready notice here when they're live." and st['vis']=='block', st)
                check('feedback: item saved with status Submitted', st['items']==[['script','tool',4,'submitted']] and 'Submitted' in st['list'], st)
                check('feedback: comment rendered as text (no injection)', not st['x'] and st['imgs']==0, st)
                inbox=[json.loads(l) for l in open(os.path.join(fbd,'data','feedback','inbox.jsonl'))]
                check('feedback: written to inbox.jsonl and the item file', len(inbox)==1 and inbox[0]['comment'].startswith('Hooks') and inbox[0]['reviewer']=='Chris' and os.path.exists(os.path.join(fbd,'data','feedback','items',inbox[0]['id']+'.json')), inbox)
                fid=inbox[0]['id']
                r=subprocess.run(['python3',os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','tools','render','fb.py'),'set',fid,'in_progress','--resolution','Looking at it'],env=env,capture_output=True,text=True)
                await J(pg,"()=>fbPoll()"); await pg.wait_for_timeout(300)
                check('feedback: routine can mark in progress; tool shows it', r.returncode==0 and await J(pg,"()=>fbItems()[0].status")=='in_progress' and 'In progress' in await J(pg,"()=>document.getElementById('fb-list').textContent"), r.stderr[-300:])
                await J(pg,"()=>fbToggle(false)")
                r=subprocess.run(['python3',os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','tools','render','fb.py'),'set',fid,'ready','--accept','--resolution','Hook rule added','--rule','Name the stakes in the first line.'],env=env,capture_output=True,text=True)
                await J(pg,"()=>fbPoll()"); await pg.wait_for_timeout(300)
                st=await J(pg,"()=>({b:document.getElementById('fb-banner').style.display,bt:document.getElementById('fb-banner-text').textContent,badge:document.getElementById('fb-badge').textContent,bv:document.getElementById('fb-badge').style.display,st:fbItems()[0].status})")
                check('feedback: ready -> Changes ready banner + badge', st['b']=='block' and st['badge']=='1 ready' and st['bv']=='inline-block' and st['st']=='ready', st)
                st=await J(pg,"()=>({s:fmtSys('X').includes('Name the stakes in the first line.'),i:fbBlock(['stills']).includes('Name the stakes')})")
                check('feedback: accepted suggestion enters feedback memory and the script prompts (not unrelated steps)', st=={'s':True,'i':False}, st)
                await J(pg,"()=>{fbOpen()}")
                check('feedback: opening the panel clears the badge', await J(pg,"()=>document.getElementById('fb-badge').style.display")=='none')
                # episode feedback on the script: regenerated with the note
                SC['script']=None
                await J(pg,"""()=>{genScript='Jordan waits. Marcus helps.';document.getElementById('txed').value=genScript;document.getElementById('fb-step').value='script';document.getElementById('fb-kind').value='episode';document.getElementById('fb-comment').value='Make Jordan more anxious';return fbSubmit()}""")
                await pg.wait_for_timeout(2500)
                st=await J(pg,"()=>({items:fbItems().map(i=>i.status),note:fbBlock(['script']).includes('Make Jordan more anxious'),img:fbBlock(['stills']).includes('anxious')})")
                srv=json.load(open(os.path.join(fbd,'data','feedback','items',[json.loads(l) for l in open(os.path.join(fbd,'data','feedback','inbox.jsonl'))][1]['id']+'.json')))
                check('feedback: episode note goes into that step\'s prompts only', st['note'] and not st['img'], st)
                check('feedback: episode item is processed (server status moved past submitted)', srv['status'] in ('in_progress','ready') and len(srv['history'])>=2, srv['history'])
                # live "apply now": timer, before/after toggle, revert puts the old script back in place
                lv=await J(pg,"()=>({shown:document.getElementById('fb-live').style.display,act:document.getElementById('fb-live-actions').style.display,timer:document.getElementById('fb-live-timer').textContent,after:document.getElementById('txed').value,view:document.getElementById('fb-live-view').textContent})")
                check('feedback live: progress panel with timer, result shown in place with before/after + accept/revert', lv['shown']=='block' and lv['act']=='flex' and ':' in lv['timer'] and 'AFTER' in lv['view'] and lv['after']!='Jordan waits. Marcus helps.', lv)
                await J(pg,"()=>fbLiveToggle()")
                check('feedback live: "Show before" swaps the old version back in place', await J(pg,"()=>document.getElementById('txed').value")=='Jordan waits. Marcus helps.' and 'BEFORE' in await J(pg,"()=>document.getElementById('fb-live-view').textContent"))
                await J(pg,"()=>fbLiveToggle()")
                await J(pg,"()=>fbLiveDecide(false)")
                await pg.wait_for_timeout(400)
                st=await J(pg,"()=>({ed:document.getElementById('txed').value,g:genScript,status:fbItems().slice(-1)[0].status,note:fbBlock(['script']).includes('Make Jordan more anxious')})")
                check('feedback live: Revert restores the previous script, marks the item reverted and drops the note', st=={'ed':'Jordan waits. Marcus helps.','g':'Jordan waits. Marcus helps.','status':'reverted','note':False}, st)
                lab=await J(pg,"()=>[...document.getElementById('fb-kind').options].map(o=>o.textContent)")
                check('feedback: the two kinds are clearly labelled', lab[0].startswith('Apply to this episode now') and lab[1].startswith('Suggest a tool improvement'), lab)
                cs=await J(pg,"()=>{document.getElementById('fb-kind').value='episode';document.getElementById('fb-step').value='script';fbKindUI();return [document.getElementById('fb-cost').textContent,document.getElementById('fb-submit').textContent]}")
                check('feedback: apply-now shows its cost estimate before running', 'estimated cost' in cs[0] and cs[1]=='Apply to this episode now', cs)
                bp=await J(pg,"()=>{let asked=0;const o=window.budgetPreflight;window.budgetPreflight=()=>{asked++;return false};document.getElementById('fb-step').value='script';document.getElementById('fb-comment').value='shorter';const n=fbItems().length;return fbSubmit().then(()=>{window.budgetPreflight=o;return [asked,fbItems().length-n]})}")
                check('feedback: apply-now runs the budget pre-check and stops when declined', bp==[1,0], bp)
                # episode feedback when the step has no output yet: kept for the next generation
                await J(pg,"()=>{document.getElementById('fb-step').value='music';document.getElementById('fb-kind').value='episode';document.getElementById('fb-comment').value='Softer score';return fbSubmit()}")
                await pg.wait_for_timeout(500)
                check('feedback: no output yet -> in progress, note kept for next run', await J(pg,"()=>fbItems().slice(-1)[0].status")=='in_progress' and 'next time' in await J(pg,"()=>fbItems().slice(-1)[0].resolution"))
                # wrong key
                await J(pg,"()=>{sessionStorage.setItem('cfa_render_token','nope');document.getElementById('fb-kind').value='tool';document.getElementById('fb-comment').value='x';return fbSubmit()}")
                check('feedback: wrong access key shows an error, nothing saved locally', 'access token' in await J(pg,"()=>document.getElementById('fb-err').textContent") and await J(pg,"()=>fbItems().length")==3, await J(pg,"()=>fbItems().length"))
                await J(pg,"()=>{sessionStorage.removeItem('cfa_render_url');document.getElementById('fb-comment').value='x';return fbSubmit()}")
                check('feedback: no render service -> asks to connect it', 'Settings' in await J(pg,"()=>document.getElementById('fb-err').textContent"))
                SC['script']=None
                ol=await J(pg,"()=>{genScript='Jordan waits.';document.getElementById('txed').value=genScript;document.getElementById('fb-err').textContent='';document.getElementById('fb-step').value='script';document.getElementById('fb-kind').value='episode';document.getElementById('fb-comment').value='Add a reaction';return fbSubmit().then(()=>new Promise(r=>setTimeout(r,2500))).then(()=>({err:document.getElementById('fb-err').textContent,local:!!fbItems().slice(-1)[0].local,act:document.getElementById('fb-live-actions').style.display}))}")
                check('feedback: apply-now works in the browser without the render service', ol['err']=='' and ol['local'] and ol['act']=='flex', ol)
                check('feedback: no page errors', not [e for e in errs if 'pageerror' in e], errs[:5])
                await ctx.close()
            finally:
                svc.terminate()
        if want('stress'):
            for k in SC: SC[k]={'xai':'ok','fal':'ok','el':'ok'}.get(k,0 if k in('delay','falDelay') else None)
            ctx,pg,errs=await newpage(b,pre="localStorage.setItem('cfa_format','dialogue');")
            def mk(n_words, speakers=('JORDAN','MARCUS'), per=10):
                lines=['MARCUS: Sent is not the same as arrived.']; left=n_words-7; i=0
                while left>0:
                    k=min(per,left); lines.append(speakers[i%len(speakers)]+': '+' '.join(['word']*k)); left-=k; i+=1
                return '\n'.join(lines)
            for n,ok in ((650,True),(900,True),(649,False),(901,False)):
                li=await J(pg,"(t)=>{localStorage.setItem('cfa_narr_mode','sparse');const r=dialogueLint(t);localStorage.removeItem('cfa_narr_mode');return r}",mk(n))
                check(f'stress: {n}-word script {"passes" if ok else "flagged"} length lint', (not [x for x in li if 'Spoken length' in x])==ok, li)
            six=mk(700,('JORDAN','MARCUS','DEE','PRIYA','MR. OKAFOR','NARRATOR'))
            li=await J(pg,"(t)=>{localStorage.setItem('cfa_narr_mode','sparse');const r=dialogueLint(t);localStorage.removeItem('cfa_narr_mode');return r}",six)
            check('stress: 6-speaker script lints clean', [x for x in li if 'concrete stakes' not in x]==[], li)  # synthetic filler has no story stakes
            v=await J(pg,"(t)=>parseDialogue(t).map(x=>lockedVoice(x.speaker).voiceId)",six)
            check('stress: all 6 speakers resolve to locked voices', len(set(v))==6, sorted(set(v)))
            mono="NARRATOR: The wallet opened.\nMARCUS: "+"This is how a ledger keeps every record honest and visible. "*8
            li=' | '.join(await J(pg,"(t)=>{localStorage.setItem('cfa_narr_mode','sparse');const r=dialogueLint(t);localStorage.removeItem('cfa_narr_mode');return r}",mono))
            check('stress: monologue flagged (one speaker, over-long line)', 'at least two speaking characters' in li and 'monologue' in li, li)
            sl=(await J(pg,"(t)=>dialogueSegments(t)",mono)).split('\n')
            check('stress: monologue line split into beats of <=35 words', len(sl)>=3 and all(len(l.split(': ',1)[1].split())<=35 for l in sl), [len(l.split()) for l in sl])
            rapid='\n'.join(['MARCUS: Wait.']+[('JORDAN: ' if i%2 else 'MARCUS: ')+['Sent?','Not yet.','Now?','Check it.','Twelve.','There.'][i%6] for i in range(40)])
            SC['elCalls']=[]; SC['elReal']=True; SC['elFailN']=2; SC['elFails']=0
            await J(pg,"(t)=>{finalScript=t;segScript=dialogueSegments(t);goVO();}",rapid)
            await J(pg,"()=>generateVO()")
            await pg.wait_for_function("()=>document.getElementById('s5-result').style.display!=='none'||document.getElementById('e5').textContent",timeout=60000)
            vo=await J(pg,"()=>({n:voLines.length,err:document.getElementById('e5').textContent,mono:voWords.every((w,i)=>!i||w[1]>=voWords[i-1][1])})")
            check('stress: rapid exchange (41 short lines) voiced line-by-line, timings monotonic', vo['n']==41 and not vo['err'] and vo['mono'], vo)
            check('stress: ElevenLabs 503s retried then succeed', SC['elFails']==2 and len(SC['elCalls'])==41, (SC['elFails'],len(SC['elCalls'])))
            # Whisper re-voice: only the flagged line is re-generated, everything else reused
            SC['elFailN']=0; SC['elCalls']=[]
            r=await J(pg,"""()=>{const keep=sceneData; const t=dlgLast.lines[2].text;
              sceneData=[{line:'1. '+dlgLast.lines[0].speaker+': '+dlgLast.lines[0].text},{line:'2. x'},{line:'3. '+dlgLast.lines[2].speaker+': '+t}];
              const rep={whisper:{final_pass:{lines:[{index:3,speaker:dlgLast.lines[2].speaker,matched:0.4,flag:true,missing:['x']},{index:1,matched:1}]}}};
              showWhisperFlags(rep); const idx=JSON.parse(document.getElementById('rs-whisper').dataset.idx||'[]');
              const btn=!!document.getElementById('btn-revoice'); sceneData=keep; return {idx,btn,n:whisperFlagged(rep).length}}""")
            check('stress: Whisper flags map to the right voiceover line + re-voice button', r['idx']==[2] and r['btn'] and r['n']==1, r)
            n=await J(pg,"()=>revoiceFlagged([2])")
            check('stress: re-voice calls ElevenLabs for the flagged line only (1 call, not 41)', n==1 and len(SC['elCalls'])==1, (n,len(SC['elCalls'])))
            SC['elFailN']=10; SC['elCalls']=[]
            await J(pg,"()=>{regenerateVO();generateVO();}")
            await pg.wait_for_function("()=>document.getElementById('e5').textContent",timeout=60000)
            e=await J(pg,"()=>document.getElementById('e5').textContent")
            check('stress: persistent API failure -> clear error after 3 tries, no half voiceover', 'after 3 tries' in e and await J(pg,"()=>document.getElementById('s5-result').style.display")=='none', e)
            SC['elFailN']=0; SC['el']='401'
            await J(pg,"()=>{regenerateVO();generateVO();}")
            await pg.wait_for_function("()=>document.getElementById('e5').textContent",timeout=20000)
            check('stress: bad ElevenLabs key -> no retry storm, key message', 'Invalid API key' in await J(pg,"()=>document.getElementById('e5').textContent"))
            SC['el']='ok'; SC['elReal']=False
            # render service down
            await J(pg,"()=>{sessionStorage.setItem('cfa_render_url','http://127.0.0.1:9');sessionStorage.setItem('cfa_render_token','t');}")
            SC['downHits']=[]
            await J(pg,"()=>fbPoll()")
            sy=await J(pg,"()=>{const e=document.getElementById('fb-sync');return e?e.textContent:null}")
            check('stress: render service down -> feedback sync shows failure, no crash', sy is not None and 'sync failed' in sy and any(h.startswith('GET /feedback?since=') for h in SC['downHits']), (sy,SC['downHits']))
            SC['downHits']=[]
            await J(pg,"()=>{fbOpen();document.getElementById('fb-comment').value='x';return fbSubmit()}")
            check('stress: render service down -> feedback submit shows an error, nothing saved', 'Could not send' in await J(pg,"()=>document.getElementById('fb-err').textContent") and await J(pg,"()=>fbItems().length")==0 and 'POST /feedback' in SC['downHits'], SC['downHits'])
            check('stress: no page errors', not [x for x in errs if 'pageerror' in x], errs[:5])
            await ctx.close()
        if want('export'):
            ctx,pg,errs=await newpage(b)
            await J(pg,"""()=>{selId='v07';finalScript='Jordan waits. Marcus says crypto is a ledger.';
              segScript='1. Jordan waits.\\n2. Marcus says crypto is a ledger.\\n3. Done.';
              voWords=[['Jordan',0,0.4],['waits.',0.45,0.9],['Marcus',1.2,1.6],['says',1.65,1.9],['crypto',1.95,2.4],['is',2.45,2.6],['a',2.62,2.7],['ledger.',2.75,3.3],['Done.',3.6,4.0]];
              sceneData=[{line:'1. Jordan waits.',tag:'IMAGE',characters:'JORDAN',resultURL:'https://v3b.fal.media/files/a.png',resultType:'image',resultModel:'Kling o1',done:true},
                         {line:'2. Marcus says crypto is a ledger.',tag:'VIDEO',characters:'MARCUS',resultURL:'https://v3b.fal.media/files/b.mp4',resultType:'video',resultModel:'Kling v1.6 Pro',done:true},
                         {line:'3. Done.',tag:'IMAGE',characters:'NONE',resultURL:'',resultType:'',done:false}];
              voAudioURL=null; document.getElementById('settings-modal').classList.remove('open');}""")
            await J(pg,"()=>exportFinalEditBundle()")
            check('export: no voiceover in memory asks for the MP3', 'voiceover' in await J(pg,"()=>document.getElementById('fe-status').textContent") and await J(pg,"()=>document.getElementById('fe-vo-pick').style.display")=='')
            await J(pg,"()=>{voAudioURL=URL.createObjectURL(new Blob([new Uint8Array([73,68,51,4,0,0,0,0,0,0])],{type:'audio/mpeg'}));}")
            async with pg.expect_download(timeout=15000) as dl:
                await J(pg,"()=>exportFinalEditBundle()")
            d=await dl.value; zp=await d.path()
            import zipfile as _zf
            z=_zf.ZipFile(zp); names=z.namelist()
            check('export: zip valid (CRCs ok)', z.testzip() is None, names)
            check('export: zip contents', all(n in names for n in ['bundle.json','media/scene_001.png','media/scene_002.mp4','voiceover.mp3','script.txt','segments.txt','beats.srt']), names)
            bj=json.loads(z.read('bundle.json'))
            check('export: bundle metadata', bj['format']=='cfa-final-edit-bundle' and bj['episode']==7 and bj['title'] and len(bj['segments'])==3 and bj['voicePace']['pace'] in ('slow','normal','expressive') and bj['segments'][1]['start']==1.2 and bj['segments'][2]['media'] is None, bj['segments'])
            check('export: srt has timed beats', '00:00:01,200 --> 00:00:03,300' in z.read('beats.srt').decode())
            check('export: filename', d.suggested_filename.startswith('CFA_FinalEdit_EP07_'), d.suggested_filename)
            check('export: status reports missing media', 'scenes without media: 3' in await J(pg,"()=>document.getElementById('fe-status').textContent"))
            check('export: no page errors', not [e for e in errs if 'pageerror' in e], errs)
            n=await J(pg,"""()=>{sceneData[1].resultURL='https://v3b.fal.media/files/b.png'; sceneData[1].resultType='image'; let asked=''; const oc=window.confirm; window.confirm=m=>{asked=m; return false;}; exportFinalEditBundle(); window.confirm=oc; currentScene=1; renderResultMedia(sceneData[1].resultURL,'image'); return [clipBeatsHoldingStills(), asked, !!document.querySelector('.clip-still-warn')]}""")
            check('clip beat holding a still is flagged (list, confirm, warning)', n[0]==[2] and 'holds a still' in n[1] and n[2], n)
            await ctx.close()

        await b.close()
        f=[r for r in results if not r[1]]
        print(f'\n{len(results)-len(f)}/{len(results)} passed')
asyncio.run(main())
