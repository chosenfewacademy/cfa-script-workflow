# Headless adversarial test: every external API (xAI, fal, ElevenLabs) is mocked via request
# interception, so it costs $0. Run: pip install playwright && python3 tests/cfa-adversarial-mock-test.py [group ...]
# Groups: happy xaierr nokey abort trunc xss inputs prompts fal vo storage reload settings timing batch (default all)
# Optional: CHROME=/usr/bin/google-chrome to use a system Chrome.
import asyncio, json, re, base64, sys
from playwright.async_api import async_playwright
import os
URL='file://'+os.path.abspath(os.path.join(os.path.dirname(__file__),'..','CFA_Script_Workflow.html'))
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
    sysmsg=body['messages'][0]['content']; user=body['messages'][1]['content']
    if 'story editor' in sysmsg and 'senior' not in sysmsg:
        cnt['plan']=cnt.get('plan',0)+1
        text='PREMISE: Jordan at the bus stop\nDETAILS: $212.40, 4 minutes'
    elif 'senior script editor' in sysmsg:
        cnt['revise']=cnt.get('revise',0)+1
        SC['lastRevise']=user
        draft=user.split('DRAFT SCRIPT:\n',1)[1] if 'DRAFT SCRIPT:\n' in user else ''
        text=SC.get('reviseOut') if SC.get('reviseOut') is not None else draft+'\n\nRevised.'
    elif 'narrative architect' in sysmsg:
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
        if mode=='promptfail' and 'Marcus' in user: return await route.fulfill(status=500,content_type='application/json',body='{}')
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
    if 'fal.media' in u: return await route.fulfill(status=200,content_type='image/png',body=PNG)
    cnt['falgen']+=1
    if SC['delay']: await asyncio.sleep(SC['delay'])
    m=SC['fal']
    if m in('429','500','422','401'):
        st=int(m); b={'detail':[{'msg':'field required','loc':['body','prompt']}]} if st==422 else ({'detail':'Invalid key'} if st==401 else {})
        return await route.fulfill(status=st,content_type='application/json',body=json.dumps(b))
    if m=='empty': return await route.fulfill(status=200,content_type='application/json',body='{}')
    n=cnt['falgen']
    if 'video' in u: return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'video':{'url':f'https://v3b.fal.media/files/v{n}.mp4'}}))
    return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'images':[{'url':f'https://v3b.fal.media/files/g{n}.png'}]}))
async def el_route(route):
    m=SC['el']
    if m in('401','429'): return await route.fulfill(status=int(m),content_type='application/json',body=json.dumps({'detail':{'message':'nope'}}))
    if m=='empty': return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'audio_base64':'','alignment':None}))
    body=json.loads(route.request.post_data or '{}'); text=body.get('text','')
    assert route.request.url.endswith('/with-timestamps'), route.request.url
    chars=list(text); st=[round(i*0.06,3) for i in range(len(chars))]; en=[round(x+0.06,3) for x in st]
    return await route.fulfill(status=200,content_type='application/json',body=json.dumps({'audio_base64':base64.b64encode(b'ID3fakeaudio').decode(),'alignment':{'characters':chars,'character_start_times_seconds':st,'character_end_times_seconds':en}}))
async def other_route(route):
    u=route.request.url
    if u.startswith(('file:','data:','blob:')): return await route.continue_()
    print('UNEXPECTED REQUEST',u); return await route.abort()

async def newpage(b, keys=True, pre=None):
    ctx=await b.new_context(accept_downloads=True)
    pg=await ctx.new_page()
    errs=[]
    pg.on('pageerror',lambda e: errs.append('pageerror: '+str(e)))
    pg.on('console',lambda m: errs.append(m.type+': '+m.text) if m.type=='error' else None)
    pg.on('dialog',lambda d: asyncio.ensure_future(d.accept()))
    await ctx.route('**/*',other_route)
    await ctx.route('https://api.x.ai/**',xai_route)
    await ctx.route(re.compile(r'https://(fal\.run|rest\.alpha\.fal\.ai|upload\.mock|v3b\.fal\.media)/.*'),fal_route)
    await ctx.route('https://api.elevenlabs.io/**',el_route)
    if pre: await ctx.add_init_script(pre)
    if keys:
        await ctx.add_init_script("sessionStorage.setItem('cfa_xai_key','xai-test');sessionStorage.setItem('cfa_fal_key','fal-test');sessionStorage.setItem('cfa_el_key','el-test');localStorage.setItem('cfa_onboarded','1');")
    await pg.goto(URL); await pg.wait_for_timeout(300)
    return ctx,pg,errs
J=lambda pg,js,*a: pg.evaluate(js,*a)
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
            check('happy: text spend tracked (plan 0.0005 + draft 0.005 + revise 0.005)', abs(await J(pg,'()=>textSpend')-0.0105)<1e-6, await J(pg,'()=>textSpend'))
            await go_seg(pg); check('happy: segments', await J(pg,"()=>(segScript.match(/^\\d+\\./gm)||[]).length")>=3)
            await go_scenes(pg)
            st=await J(pg,"()=>({n:sceneData.length,consec:sceneData.some((s,i)=>i&&s.tag==='VIDEO'&&sceneData[i-1].tag==='VIDEO'),prompts:sceneData.every(s=>s.prompt)})")
            check('happy: classified+prompts', st['n']>=3 and st['prompts'] and not st['consec'], st)
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
            check('garbage classification: all IMAGE', await J(pg,"()=>sceneData.every(s=>s.tag==='IMAGE')"))
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
              {line:'2. Jordan sends.',tag:'VIDEO',characters:'JORDAN',prompt:'p',sceneDesc:'',done:false,resultURL:'',resultType:'',resultModel:'',savedStartFrameURL:''},
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
            for k in ['Marcus','Jordan']: await J(pg,f"()=>{{delete charUploadCache['{k}']}}")
            await J(pg,"()=>{for(const i of [1,0,3,2,1,0,3]){currentScene=i;loadScene(i);}}")
            await pg.wait_for_timeout(2500)
            st=await J(pg,"()=>({cur:currentScene,subj:document.querySelector('#slot-subject img')?.alt||'',co:document.querySelector('#slot-cosubject img')?.alt||'',subjUrl:!!sceneRefs.subject?.url?.startsWith('https'),coUrl:!!sceneRefs.cosubject?.url?.startsWith('https'),uploading:!!document.getElementById('slot-subject').dataset.uploading})")
            check('rapid switching: BOTH scene has Marcus+Jordan refs', st['cur']==3 and st['subj']=='Marcus' and st['co']=='Jordan' and st['subjUrl'] and st['coUrl'] and not st['uploading'], st)
            check('character uploads deduped (2 uploads for 7 rapid scene loads)', cnt['upload']-up0==2, cnt['upload']-up0)
            SC['falDelay']=0
            # Upload failure path
            SC['fal']='uploadfail'
            for k in ['Marcus','Jordan']: await J(pg,f"()=>{{delete charUploadCache['{k}']}}")
            await J(pg,"()=>{currentScene=0;loadScene(0);}"); await pg.wait_for_timeout(500)
            await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(300)
            check('upload fail: generation blocked with message', 'uploading' in (await J(pg,"()=>document.getElementById('e6').textContent")).lower() or 'character' in (await J(pg,"()=>document.getElementById('e6').textContent")).lower(), await J(pg,"()=>document.getElementById('e6').textContent"))
            SC['fal']='ok'
            for k in ['Marcus','Jordan']: await J(pg,f"()=>{{delete charUploadCache['{k}']}}")
            # Generate scene 0, switch away mid-flight
            SC['delay']=0.8
            await J(pg,"()=>{currentScene=0;loadScene(0);}"); await pg.wait_for_timeout(400)
            await J(pg,"()=>{generateScene(); setTimeout(()=>jumpToScene(2),200);}"); await pg.wait_for_timeout(1500)
            st=await J(pg,"()=>({r0:!!sceneData[0].resultURL,r2:!!sceneData[2].resultURL,sf1:sceneData[1].savedStartFrameURL===sceneData[0].resultURL,shown:!!document.querySelector('#s6-result-content img')})")
            check('switch mid-gen: result on scene 1 only + start frame for scene 2', st['r0'] and not st['r2'] and st['sf1'] and not st['shown'], st)
            SC['delay']=0
            # Veo without start frame
            await J(pg,"()=>{sceneData[1].savedStartFrameURL='';sceneData[0].resultURL='';jumpToScene(1);setVideoModel('veo31');}")
            await pg.wait_for_timeout(300); await J(pg,"()=>generateScene()"); await pg.wait_for_timeout(200)
            check('veo without start frame: blocked', 'start frame' in (await J(pg,"()=>document.getElementById('e6').textContent")).lower())
            check('fal: no page errors', not [e for e in errs if 'pageerror' in e], errs)
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
            before=await J(pg,"()=>({n:sceneData.length,cur:currentScene,r:sceneData[0].resultURL})")
            await pg.reload(); await pg.wait_for_timeout(500)
            check('reload: banner', await J(pg,"()=>document.getElementById('resume-banner').style.display!=='none'"))
            await J(pg,"()=>resumeSavedSession()"); await pg.wait_for_timeout(500)
            after=await J(pg,"()=>({n:sceneData.length,cur:currentScene,r:sceneData[0].resultURL})")
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
            st=await J(pg,"()=>sceneData.map(s=>[s.tag,s.tStart,s.tEnd])")
            check('timing: every scene timed, monotonic', all(x[1] is not None for x in st) and all(st[i][1]>=st[i-1][2]-1e-6 for i in range(1,len(st))), st)
            await J(pg,"()=>{sceneData[1].tStart=0;sceneData[1].tEnd=7.3;startSceneGeneration();}"); await pg.wait_for_timeout(300)
            await J(pg,"()=>jumpToScene(1)"); await pg.wait_for_timeout(200)
            d=await J(pg,"()=>({d:sceneDuration,hint:document.getElementById('dur-hint').textContent})")
            check('timing: auto 10s for 7.3s beat (Kling)', d['d']==10 and 'auto 10s' in d['hint'], d)
            await J(pg,"()=>setVideoModel('veo31')"); await J(pg,"()=>jumpToScene(0)"); await J(pg,"()=>jumpToScene(1)")
            check('timing: Veo picks 8s', await J(pg,'()=>sceneDuration')==8)
            await J(pg,"()=>setDuration(4)"); await J(pg,"()=>jumpToScene(0)"); await J(pg,"()=>jumpToScene(1)")
            check('timing: manual pick sticks per scene', await J(pg,'()=>sceneDuration')==4 and 'you picked 4s' in await J(pg,"()=>document.getElementById('dur-hint').textContent"))
            await pg.reload(); await pg.wait_for_timeout(400); await J(pg,"()=>resumeSavedSession()"); await pg.wait_for_timeout(400)
            check('timing: survives reload', await J(pg,"()=>voWords.length>5 && sceneData[1].videoDur===4 && sceneData[0].tEnd>0"))
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
            check('batch: NONE→Nano Banana, chars→Kling o1', st['models'][2]=='Nano Banana' and st['models'][0]=='Kling o1', st['models'])
            SC['fal']='500'; await J(pg,"()=>{sceneData[0].resultURL='';sceneData[1].resultURL='';renderSceneDots();generateAllImages();}"); await pg.wait_for_timeout(800)
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
            check('writing: plan passed to draft privately', 'PRIVATE BEAT PLAN' in SC.get('lastDraftUser','') and '$212.40' in SC['lastDraftUser'])
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

        await b.close()
        f=[r for r in results if not r[1]]
        print(f'\n{len(results)-len(f)}/{len(results)} passed')
asyncio.run(main())
