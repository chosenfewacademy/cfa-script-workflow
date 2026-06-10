/**
 * CFA Character Isolation — Live Test
 * ─────────────────────────────────────────────────────────────────────────────
 * Verifies the workflow's character logic end-to-end with REAL Kling/Imagen
 * generations, mirroring generateScene() exactly:
 *   - Marcus reference is used ONLY for Marcus
 *   - Jordan reference is used ONLY for Jordan
 *   - A secondary character (banker, woman, etc.) is generated as a DISTINCT
 *     person, NOT in Marcus/Jordan likeness, via the guard appended to the prompt
 *   - NONE scenes (no main char) generate a generic character via Imagen 4
 *
 * Usage:  node cfa-character-isolation-test.mjs YOUR_FAL_KEY
 * Output: ./test-output/character-isolation/
 */

import fs   from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FAL_KEY   = process.argv[2] || process.env.FAL_KEY;
const OUT_DIR   = path.join(__dirname, 'test-output', 'character-isolation');
const HTML_PATH = path.join(__dirname, 'exports', 'CFA_Script_Workflow_Standalone.html');

const C = { reset:'\x1b[0m', bold:'\x1b[1m', green:'\x1b[32m', red:'\x1b[31m', dim:'\x1b[2m', cyan:'\x1b[36m', yellow:'\x1b[33m' };
const pass = m => console.log(`${C.green}PASS${C.reset} ${m}`);
const fail = m => console.log(`${C.red}FAIL${C.reset} ${m}`);
const info = m => console.log(`${C.dim}  ${m}${C.reset}`);
const head = m => console.log(`\n${C.bold}${C.cyan}== ${m} ==${C.reset}`);

if (!FAL_KEY) { fail('No fal.ai key. Usage: node cfa-character-isolation-test.mjs YOUR_FAL_KEY'); process.exit(1); }
if (!fs.existsSync(HTML_PATH)) { fail(`HTML not found: ${HTML_PATH}`); process.exit(1); }
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

const html = fs.readFileSync(HTML_PATH, 'utf8');

// ─── Mirror detectCharacters() from the workflow ──────────────────────────────
function detectCharacters(line){
  const text = line.toLowerCase();
  const hasMarcus = text.includes('marcus');
  const hasJordan = text.includes('jordan');
  if(hasMarcus && hasJordan) return text.indexOf('jordan') < text.indexOf('marcus') ? 'BOTH_JM' : 'BOTH';
  if(hasMarcus) return 'MARCUS';
  if(hasJordan) return 'JORDAN';
  return 'NONE';
}

// ─── Mirror detectSecondaryChar() from the workflow ───────────────────────────
function detectSecondaryChar(line){
  const text = line.toLowerCase();
  const hasMarcus = text.includes('marcus');
  const hasJordan = text.includes('jordan');
  if(!hasMarcus && !hasJordan) return null;
  const terms = ['banker','investor','advisor','broker','trader','analyst','executive',
    'director','manager','officer','client','customer','employee','boss',
    'teacher','professor','coach','mentor','expert','speaker','presenter',
    'colleague','friend','partner','stranger','person','figure',
    'woman','man','girl','boy','lady','gentleman',
    'him','her','them','someone','somebody','another'];
  return terms.find(t => new RegExp('\\b' + t + '\\b').test(text)) || null;
}

// ─── Extract embedded base64 character images from the HTML ────────────────────
function extractB64(varName){
  const start = html.indexOf(`const ${varName} = `);
  if(start === -1) throw new Error(`${varName} not found in HTML`);
  const delimPos = start + `const ${varName} = `.length;
  const delim = html[delimPos];
  const dataEnd = html.indexOf(delim, delimPos + 1);
  return html.slice(delimPos + 1, dataEnd);
}
function b64ToBuffer(dataUri){
  return Buffer.from(dataUri.replace(/^data:image\/jpeg;base64,/, '').replace(/^data:image\/png;base64,/, ''), 'base64');
}

// ─── fal.ai storage upload (initiate + PUT) ───────────────────────────────────
async function uploadToFal(buffer, fileName){
  const initResp = await fetch('https://rest.alpha.fal.ai/storage/upload/initiate', {
    method:'POST',
    headers:{ 'Authorization':'Key '+FAL_KEY, 'Content-Type':'application/json' },
    body: JSON.stringify({ content_type:'image/jpeg', file_name:fileName }),
  });
  if(!initResp.ok) throw new Error(`upload initiate ${initResp.status}: ${await initResp.text()}`);
  const { upload_url, file_url } = await initResp.json();
  const put = await fetch(upload_url, { method:'PUT', headers:{ 'Content-Type':'image/jpeg' }, body: buffer });
  if(!put.ok) throw new Error(`PUT ${put.status}`);
  return file_url;
}

async function saveFromUrl(url, filename){
  const resp = await fetch(url);
  if(!resp.ok) throw new Error(`download ${resp.status}`);
  const buf = Buffer.from(await resp.arrayBuffer());
  fs.writeFileSync(path.join(OUT_DIR, filename), buf);
  return buf.length;
}

// ─── Build finalPrompt EXACTLY like generateScene() ───────────────────────────
function buildFinalPrompt(basePrompt, line, characters){
  let finalPrompt = basePrompt;
  const secondary = detectSecondaryChar(line);
  if(secondary && characters !== 'NONE'){
    const mainChar = (characters === 'BOTH' || characters === 'BOTH_JM') ? 'Marcus and Jordan'
                   : characters === 'MARCUS' ? 'Marcus' : 'Jordan';
    finalPrompt += ` [Reference image is ONLY for ${mainChar}. The ${secondary} in this scene is a completely different person — distinct appearance, different skin tone and build, does not resemble ${mainChar} in any way.]`;
  }
  return { finalPrompt, secondary };
}

// ─── Test cases ───────────────────────────────────────────────────────────────
const CASES = [
  { id:'1_marcus_solo',     line:'Marcus explains Bitcoin basics at his desk, pointing at a chart.' },
  { id:'2_jordan_solo',     line:'Jordan looks confused while staring at her phone screen.' },
  { id:'3_marcus_banker',   line:'Marcus shakes hands with a banker in a grey suit at a bank counter.' },
  { id:'4_jordan_investor', line:'Jordan sits across the table from a female investor reviewing documents.' },
  { id:'5_banker_only',     line:'A nervous banker reviews stacks of paperwork alone in an office.' },
  { id:'6_both',            line:'Marcus and Jordan discuss the price chart together on a laptop.' },
];

async function main(){
  console.log(`\n${C.bold}CFA Character Isolation — Live Test${C.reset}`);
  info(`Output: ${OUT_DIR}`);

  // Upload character refs once
  head('SETUP — upload Marcus & Jordan references');
  let marcusUrl, jordanUrl;
  try {
    marcusUrl = await uploadToFal(b64ToBuffer(extractB64('MARCUS_B64')), 'marcus.jpg');
    pass(`Marcus uploaded`);
    jordanUrl = await uploadToFal(b64ToBuffer(extractB64('JORDAN_B64')), 'jordan.jpg');
    pass(`Jordan uploaded`);
  } catch(e){ fail(`setup: ${e.message}`); process.exit(1); }

  const results = [];

  for(const tc of CASES){
    head(`CASE ${tc.id}`);
    info(`line: "${tc.line}"`);
    const characters = detectCharacters(tc.line);
    const secondary  = detectSecondaryChar(tc.line);
    info(`detectCharacters → ${C.yellow}${characters}${C.reset}   detectSecondaryChar → ${C.yellow}${secondary || 'none'}${C.reset}`);

    // Assemble character ref images per workflow autoPopulate logic
    const refs = [];
    if(characters === 'MARCUS') refs.push(marcusUrl);
    else if(characters === 'JORDAN') refs.push(jordanUrl);
    else if(characters === 'BOTH') { refs.push(marcusUrl, jordanUrl); }
    else if(characters === 'BOTH_JM') { refs.push(jordanUrl, marcusUrl); }
    // NONE → no refs (Imagen path)

    const { finalPrompt } = buildFinalPrompt(tc.line, tc.line, characters);
    info(`refs used: ${refs.length === 0 ? 'NONE (Imagen 4 text-only)' : refs.length + ' (' + characters + ')'}`);
    if(finalPrompt !== tc.line) info(`guard appended: ${C.dim}${finalPrompt.slice(tc.line.length).trim()}${C.reset}`);

    try {
      let url, model;
      if(refs.length === 0){
        // NONE → Imagen 4 Ultra text-only (matches workflow)
        const body = { prompt: finalPrompt + '  2D illustrated style. Bold clean outlines, flat color shading. No photorealism.', aspect_ratio:'16:9', num_images:1 };
        const r = await fetch('https://fal.run/fal-ai/imagen4/preview/ultra', { method:'POST', headers:{'Authorization':'Key '+FAL_KEY,'Content-Type':'application/json'}, body: JSON.stringify(body) });
        if(!r.ok) throw new Error(`imagen ${r.status}: ${await r.text()}`);
        const d = await r.json();
        url = d.images?.[0]?.url; model = 'Imagen 4 Ultra';
      } else {
        // Kling o1 with character refs (matches workflow)
        const body = { prompt: finalPrompt, aspect_ratio:'16:9', num_images:1, image_urls: refs };
        const r = await fetch('https://fal.run/fal-ai/kling-image/o1', { method:'POST', headers:{'Authorization':'Key '+FAL_KEY,'Content-Type':'application/json'}, body: JSON.stringify(body) });
        if(!r.ok) throw new Error(`kling ${r.status}: ${await r.text()}`);
        const d = await r.json();
        url = d.images?.[0]?.url; model = 'Kling o1';
      }
      if(!url) throw new Error('no image url');
      const kb = Math.round(await saveFromUrl(url, `${tc.id}.png`) / 1024);
      pass(`${model} → ${tc.id}.png (${kb}KB)`);
      results.push({ ...tc, characters, secondary, model, ok:true });
    } catch(e){
      fail(`${tc.id}: ${e.message}`);
      results.push({ ...tc, characters, secondary, ok:false, err:e.message });
    }
  }

  // Summary
  head('SUMMARY');
  let ok=0;
  for(const r of results){
    const line = `${r.id.padEnd(18)} chars=${(r.characters||'').padEnd(8)} secondary=${(r.secondary||'none').padEnd(10)} ${r.ok?'OK':'FAIL'}`;
    r.ok ? (ok++, pass(line)) : fail(line + ' — ' + r.err);
  }
  console.log(`\n${C.bold}${ok}/${results.length} generated.${C.reset} Inspect images in ${OUT_DIR}`);
  console.log(`${C.dim}Manual visual check: 1=Marcus, 2=Jordan, 3=Marcus+distinct banker, 4=Jordan+distinct investor, 5=generic banker (no Marcus/Jordan), 6=Marcus & Jordan together.${C.reset}`);
  if(ok < results.length) process.exit(1);
}

main().catch(e => { fail('FATAL: ' + e.message); process.exit(1); });
