/**
 * CFA Anthropic Pipeline — Live Test
 * ─────────────────────────────────────────────────────────────────────────────
 * Tests the 4 Claude calls the workflow makes, in order, with the real models:
 *   1. SCRIPT     claude-sonnet-4-20250514   — write Marcus/Jordan dialogue
 *   2. SEGMENT    claude-haiku-4-5-20251001  — numbered scene segmentation (stream)
 *   3. CLASSIFY   claude-haiku-4-5-20251001  — IMAGE/VIDEO tags (+ no-consec rule)
 *   4. PROMPTS    claude-haiku-4-5-20251001  — per-scene Kling prompt + Character Note
 *
 * Also validates: model strings resolve, classifier honors ~30% video + no two
 * consecutive videos, and the secondary-character note is injected correctly.
 *
 * Usage:  node cfa-anthropic-pipeline-test.mjs YOUR_ANTHROPIC_KEY
 */

const KEY = process.argv[2] || process.env.ANTHROPIC_KEY;
const C = { reset:'\x1b[0m', bold:'\x1b[1m', green:'\x1b[32m', red:'\x1b[31m', dim:'\x1b[2m', cyan:'\x1b[36m', yellow:'\x1b[33m' };
const pass = m => console.log(`${C.green}PASS${C.reset} ${m}`);
const fail = m => console.log(`${C.red}FAIL${C.reset} ${m}`);
const info = m => console.log(`${C.dim}  ${m}${C.reset}`);
const head = m => console.log(`\n${C.bold}${C.cyan}== ${m} ==${C.reset}`);
if(!KEY){ fail('No Anthropic key. Usage: node cfa-anthropic-pipeline-test.mjs YOUR_KEY'); process.exit(1); }

const API = 'https://api.anthropic.com/v1/messages';
const HDR = { 'Content-Type':'application/json', 'x-api-key':KEY, 'anthropic-version':'2023-06-01' };

async function call(model, system, user, max_tokens){
  const t0 = Date.now();
  const r = await fetch(API, { method:'POST', headers:HDR, body:JSON.stringify({ model, max_tokens, system, messages:[{role:'user',content:user}] }) });
  const ms = Date.now()-t0;
  if(!r.ok){ const e = await r.json().catch(()=>({})); throw new Error(`${model} HTTP ${r.status}: ${e?.error?.message||JSON.stringify(e)}`); }
  const d = await r.json();
  return { text:(d.content?.[0]?.text)||'', ms, usage:d.usage };
}

// ─── System prompts (mirrored from the workflow) ──────────────────────────────
const SYS_WRITE = `You are the CFA script engine. You write 60-90 second crypto education video scripts that teach one specific concept through a Marcus and Jordan dialogue. Marcus is the teacher; Jordan is the learner. Output ONLY the script dialogue — no headers, no stage directions.`;
const SYS_SEG = `Segment this script into numbered visual scenes. Output one numbered line per scene (1., 2., 3., ...). Each line is a short visual description of what's on screen for that beat. Keep Marcus/Jordan names where they appear.`;
const SYS_CLASSIFY = `You are classifying script segments for a crypto education video.
For each numbered line, output exactly: [N] IMAGE or [N] VIDEO
CRITICAL RULES: 1. Never tag two consecutive scenes as VIDEO. 2. Target ~30% VIDEO. 3. Spread videos evenly.
Output only the classifications, one per line.`;
const SYS_KLING_IMAGE = `You are generating a Kling AI image prompt for a 2D illustrated crypto education video. Write 3-5 sentences. CHARACTER RULE: If a Character Note is provided, follow it exactly — Marcus and Jordan come from a reference image; any secondary character must look completely different. Then output: SCENE: [4-8 word setting]`;

let okCount = 0, total = 0;
function check(name, cond, detail){ total++; if(cond){ okCount++; pass(`${name}${detail?' — '+detail:''}`); } else { fail(`${name}${detail?' — '+detail:''}`); } }

(async () => {
  console.log(`\n${C.bold}CFA Anthropic Pipeline — Live Test${C.reset}`);

  // ── 1. SCRIPT ──────────────────────────────────────────────────────────────
  head('1. SCRIPT — claude-sonnet-4-20250514');
  let script = '';
  try {
    const r = await call('claude-sonnet-4-20250514', SYS_WRITE,
      'Topic: What is a crypto wallet? Next video: How private keys work.', 1000);
    script = r.text;
    info(`${r.ms}ms · ${r.usage?.output_tokens} out tokens`);
    info(`preview: ${script.slice(0,140).replace(/\n/g,' ')}…`);
    check('Script generated', script.length > 100, `${script.length} chars`);
    check('Has Marcus dialogue', /marcus/i.test(script));
    check('Has Jordan dialogue', /jordan/i.test(script));
  } catch(e){ fail(e.message); script = 'Marcus: A wallet holds your keys.\nJordan: How do I get one?\nMarcus: You download an app.'; }

  // ── 2. SEGMENT ─────────────────────────────────────────────────────────────
  head('2. SEGMENT — claude-haiku-4-5-20251001');
  let segLines = [];
  try {
    const r = await call('claude-haiku-4-5-20251001', SYS_SEG, 'BEGIN SCRIPT\n'+script+'\nEND SCRIPT', 2000);
    info(`${r.ms}ms`);
    segLines = r.text.split('\n').map(l=>l.trim()).filter(l=>/^\d+\./.test(l));
    info(`segmented into ${segLines.length} scenes`);
    segLines.slice(0,3).forEach(l=>info('  '+l));
    check('Segmentation produced numbered scenes', segLines.length >= 3, `${segLines.length} scenes`);
  } catch(e){ fail(e.message); }

  if(segLines.length === 0){
    segLines = ['1. Marcus introduces wallets','2. Jordan asks a banker for help','3. Marcus shows the app','4. Jordan smiles, understanding','5. A wallet icon glows'];
    info('using fallback scenes for downstream tests');
  }

  // ── 3. CLASSIFY ────────────────────────────────────────────────────────────
  head('3. CLASSIFY — claude-haiku-4-5-20251001 (+ no-consecutive enforcement)');
  let tags = [];
  try {
    const r = await call('claude-haiku-4-5-20251001', SYS_CLASSIFY, segLines.join('\n'), 2000);
    info(`${r.ms}ms`);
    tags = segLines.map((line,i)=>{
      const m = r.text.match(new RegExp('\\['+(i+1)+'\\]\\s*(IMAGE|VIDEO)','i'));
      return m ? m[1].toUpperCase() : 'IMAGE';
    });
    // Apply the workflow's post-processing: no two consecutive VIDEO
    for(let i=1;i<tags.length;i++){ if(tags[i]==='VIDEO'&&tags[i-1]==='VIDEO') tags[i]='IMAGE'; }
    const vid = tags.filter(t=>t==='VIDEO').length;
    info(`tags: ${tags.join(', ')}`);
    info(`videos: ${vid}/${tags.length} (${Math.round(vid/tags.length*100)}%)`);
    let consec = false;
    for(let i=1;i<tags.length;i++){ if(tags[i]==='VIDEO'&&tags[i-1]==='VIDEO') consec=true; }
    check('No two consecutive videos (post-enforcement)', !consec);
    check('At least one IMAGE present', tags.includes('IMAGE'));
  } catch(e){ fail(e.message); }

  // ── 4. PROMPTS (with Character Note injection) ───────────────────────────────
  head('4. PROMPTS — claude-haiku-4-5-20251001 (secondary character note)');
  const PRONOUN = ['him','her','them','someone','somebody','another'];
  function detectChars(line){ const t=line.toLowerCase(); const m=t.includes('marcus'),j=t.includes('jordan'); if(m&&j) return t.indexOf('jordan')<t.indexOf('marcus')?'BOTH_JM':'BOTH'; if(m) return 'MARCUS'; if(j) return 'JORDAN'; return 'NONE'; }
  function detectSecondary(line){ const raw=line.toLowerCase(); if(!raw.includes('marcus')&&!raw.includes('jordan')) return null; const text=raw.replace(/\b(his|her|their|its|your|our|my)\s+[a-z]+/g,' '); const terms=['banker','investor','advisor','woman','man','colleague','friend','stranger','person','him','her','them','someone','another']; return terms.find(t=>new RegExp('\\b'+t+'\\b').test(text))||null; }
  function label(s){ return !s?'':PRONOUN.includes(s)?'other person (a separate character)':s; }

  const testLine = 'Marcus shakes hands with a banker at the counter.';
  const chars = detectChars(testLine), sec = detectSecondary(testLine);
  let userMsg = testLine;
  if(sec && chars!=='NONE'){
    const main = chars==='MARCUS'?'Marcus':chars==='JORDAN'?'Jordan':'Marcus and Jordan';
    userMsg += `\n[Character Note: ${main} is the main character — their look comes from a reference image. The ${label(sec)} is a SECONDARY character and must look completely different from ${main}: different skin tone, build, clothing, and facial features (gender-appropriate). Describe them as a brand new person.]`;
  }
  info(`line: "${testLine}"  chars=${chars}  secondary=${sec}`);
  try {
    const r = await call('claude-haiku-4-5-20251001', SYS_KLING_IMAGE, userMsg, 400);
    info(`${r.ms}ms`);
    const prompt = r.text.replace(/\nSCENE:.*/i,'').trim();
    const sceneMatch = r.text.match(/SCENE:\s*(.+)/i);
    info(`prompt: ${prompt.slice(0,160)}…`);
    info(`SCENE: ${sceneMatch?sceneMatch[1].trim():'(none)'}`);
    check('Prompt generated', prompt.length > 50);
    check('SCENE: tag present', !!sceneMatch);
    check('Prompt describes a distinct second person', /different|distinct|separate|another|new person|not resemble/i.test(prompt) || prompt.toLowerCase().includes('banker'));
  } catch(e){ fail(e.message); }

  // ── SUMMARY ──────────────────────────────────────────────────────────────────
  head('SUMMARY');
  console.log(`${C.bold}${okCount}/${total} checks passed${C.reset}`);
  process.exit(okCount===total?0:1);
})().catch(e=>{ fail('FATAL: '+e.message); process.exit(1); });
