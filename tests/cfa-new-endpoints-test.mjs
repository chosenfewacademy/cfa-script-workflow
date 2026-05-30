/**
 * CFA New-Endpoints Smoke Test
 * ─────────────────────────────────────────────────────────────────────────────
 * Tests the THREE new endpoints added in the model selector build:
 *
 *   GEMINI-1   Gemini 3 Pro Edit       — image with character ref     (~$0.05)
 *   IMAGEN-1   Imagen 4 Ultra          — text-only image              (~$0.02)
 *   VEO-1      Veo 3.1 image-to-video  — start frame + 4s duration    (~$0.45)
 *
 *   Total estimated cost: ~$0.52 from the fal.ai budget
 *
 * The body shapes used here MIRROR EXACTLY what the workflow's dispatcher
 * (generateScene → _runImageGen / _runVideoGen path) sends to fal.ai. If
 * fal.ai changes a schema or rejects a field, this test catches it BEFORE
 * Chris hits it during live work.
 *
 * Usage:
 *   node cfa-new-endpoints-test.mjs YOUR_FAL_KEY
 *   set FAL_KEY=... && node cfa-new-endpoints-test.mjs
 *
 * Output: all 3 generated assets saved to ./test-output/new-endpoints/
 */

import fs   from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FAL_KEY   = process.argv[2] || process.env.FAL_KEY;
const OUT_DIR   = path.join(__dirname, 'test-output', 'new-endpoints');

if (!FAL_KEY) {
  console.error('\n✗  No fal.ai API key.\n   Usage: node cfa-new-endpoints-test.mjs YOUR_FAL_KEY\n');
  process.exit(1);
}
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

// ─── Endpoints (mirrors generateScene dispatcher) ─────────────────────────────
const FAL_UPLOAD_INIT = 'https://rest.alpha.fal.ai/storage/upload/initiate';
const GEMINI_3_PRO    = 'https://fal.run/fal-ai/gemini-3-pro-image-preview/edit';
const IMAGEN_4_ULTRA  = 'https://fal.run/fal-ai/imagen4/preview/ultra';
const VEO_3_1         = 'https://fal.run/fal-ai/veo3.1/image-to-video';

// ─── Pretty printing ──────────────────────────────────────────────────────────
const C = {
  reset:  '\x1b[0m',  bold:   '\x1b[1m',
  green:  '\x1b[32m', red:    '\x1b[31m', yellow: '\x1b[33m',
  cyan:   '\x1b[36m', blue:   '\x1b[34m', dim:    '\x1b[2m',
};
const pass  = (msg) => console.log(`${C.green}✓${C.reset}  ${msg}`);
const fail  = (msg) => console.log(`${C.red}✗${C.reset}  ${msg}`);
const info  = (msg) => console.log(`${C.dim}ℹ${C.reset}  ${msg}`);
const head  = (msg) => console.log(`\n${C.bold}${C.blue}── ${msg}${C.reset}`);
const t_ms  = (t0)  => `${Date.now() - t0}ms`;
const kb    = (n)   => `${Math.round(n / 1024)}KB`;
const hr    = ()    => console.log('─'.repeat(70));

// ─── fal.ai storage upload (same protocol as workflow) ────────────────────────
async function uploadToFal(buffer, fileName) {
  const initResp = await fetch(FAL_UPLOAD_INIT, {
    method: 'POST',
    headers: { 'Authorization': 'Key ' + FAL_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ content_type: 'image/jpeg', file_name: fileName }),
  });
  if (!initResp.ok) throw new Error(`Upload initiate ${initResp.status}: ${await initResp.text()}`);
  const { upload_url, file_url } = await initResp.json();
  const putResp = await fetch(upload_url, {
    method: 'PUT', headers: { 'Content-Type': 'image/jpeg' }, body: buffer,
  });
  if (!putResp.ok) throw new Error(`PUT ${putResp.status}`);
  return file_url;
}

// ─── Extract base64 from HTML (same as pipeline test) ─────────────────────────
function extractB64(html, varName) {
  const start    = html.indexOf(`const ${varName} = `);
  if (start === -1) throw new Error(`${varName} not found`);
  const delimPos = start + `const ${varName} = `.length;
  const delim    = html[delimPos];
  const dataEnd  = html.indexOf(delim, delimPos + 1);
  return html.slice(delimPos + 1, dataEnd);
}

function b64ToBuffer(dataUri) {
  return Buffer.from(dataUri.replace(/^data:image\/jpeg;base64,/, ''), 'base64');
}

// ─── HTTP helpers ─────────────────────────────────────────────────────────────
async function postJson(endpoint, body, label) {
  const t0 = Date.now();
  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Authorization': 'Key ' + FAL_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const elapsed = t_ms(t0);
  if (!resp.ok) {
    const e = await resp.json().catch(() => ({}));
    const m = e?.detail || e?.error || e?.message || JSON.stringify(e) || `HTTP ${resp.status}`;
    throw new Error(`[${label}] ${resp.status} after ${elapsed}: ${typeof m === 'string' ? m : JSON.stringify(m)}`);
  }
  const data = await resp.json();
  return { data, elapsed };
}

async function saveBlobFromUrl(url, filename) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HEAD ${resp.status}`);
  const buf = await resp.arrayBuffer();
  const fp  = path.join(OUT_DIR, filename);
  fs.writeFileSync(fp, Buffer.from(buf));
  return { fp, size: buf.byteLength };
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────
async function main() {
  console.log(`\n${C.bold}CFA New-Endpoints Smoke Test${C.reset}`);
  info(`Output: ${OUT_DIR}`);
  info(`Estimated cost: ~$0.52`);
  hr();

  // ── SETUP: extract Marcus + upload ───────────────────────────────────────
  head('SETUP — Extract Marcus from HTML and upload to fal.ai');

  const htmlPath = path.join(__dirname, 'exports', 'CFA_Script_Workflow_Standalone.html');
  if (!fs.existsSync(htmlPath)) { fail(`HTML not found at ${htmlPath}`); process.exit(1); }
  const html = fs.readFileSync(htmlPath, 'utf8');

  let marcusBuf;
  try {
    marcusBuf = b64ToBuffer(extractB64(html, 'MARCUS_B64'));
    pass(`MARCUS_B64 extracted (${kb(marcusBuf.length)})`);
  } catch (e) {
    fail(`Could not extract MARCUS_B64: ${e.message}`);
    process.exit(1);
  }

  let marcusUrl;
  try {
    const t0 = Date.now();
    marcusUrl = await uploadToFal(marcusBuf, 'marcus.jpg');
    pass(`Uploaded Marcus to ${marcusUrl} (${t_ms(t0)})`);
  } catch (e) {
    fail(`Upload failed: ${e.message}`);
    process.exit(1);
  }

  const RESULTS = {};

  // ── TEST 1: GEMINI 3 PRO ─────────────────────────────────────────────────
  head('TEST 1 — Gemini 3 Pro Edit (image with character reference)');
  info('Body shape mirrors generateScene() → gemini-3pro branch');

  const geminiBody = {
    prompt: 'Marcus stands in a modern office, smiling confidently at the camera. Looking forward, natural pose, talking about cryptocurrency.',
    aspect_ratio: '16:9',
    num_images: 1,
    image_urls: [marcusUrl],
    resolution: '2K',
    system_prompt: '2D illustrated style. Bold clean outlines, flat color shading, consistent line weight throughout. No photorealism.'
  };

  try {
    info('Sending to Gemini 3 Pro… (15-30 seconds)');
    const { data, elapsed } = await postJson(GEMINI_3_PRO, geminiBody, 'GEMINI');
    const url = data.images?.[0]?.url || data.image?.url || '';
    if (!url) throw new Error('No image URL in response: ' + JSON.stringify(data).slice(0, 200));
    pass(`Gemini 3 Pro responded in ${elapsed}`);
    pass(`URL: ${url}`);
    RESULTS['GEMINI-1'] = { status: 'pass', url, ms: elapsed };

    // Save for visual review
    try {
      const { size } = await saveBlobFromUrl(url, 'GEMINI-1_marcus_with_ref.png');
      pass(`Saved (${kb(size)})`);
    } catch (e) { info(`Could not save: ${e.message}`); }
  } catch (e) {
    fail(`Gemini 3 Pro FAILED: ${e.message}`);
    RESULTS['GEMINI-1'] = { status: 'fail', err: e.message };
  }

  // ── TEST 2: IMAGEN 4 ULTRA ───────────────────────────────────────────────
  head('TEST 2 — Imagen 4 Ultra (text-only, no reference image)');
  info('Body shape mirrors generateScene() → imagen4 branch');

  const imagenBody = {
    prompt: 'A modern home office workspace with warm lighting, a wooden desk with a laptop showing a green crypto chart, and a small orange ceramic mug. Empty office, no people. 2D illustrated style. Bold clean outlines, flat color shading. No photorealism.',
    aspect_ratio: '16:9',
    num_images: 1,
  };

  try {
    info('Sending to Imagen 4 Ultra… (10-20 seconds)');
    const { data, elapsed } = await postJson(IMAGEN_4_ULTRA, imagenBody, 'IMAGEN');
    const url = data.images?.[0]?.url || data.image?.url || '';
    if (!url) throw new Error('No image URL in response: ' + JSON.stringify(data).slice(0, 200));
    pass(`Imagen 4 Ultra responded in ${elapsed}`);
    pass(`URL: ${url}`);
    RESULTS['IMAGEN-1'] = { status: 'pass', url, ms: elapsed };

    try {
      const { size } = await saveBlobFromUrl(url, 'IMAGEN-1_office_concept.png');
      pass(`Saved (${kb(size)})`);
    } catch (e) { info(`Could not save: ${e.message}`); }
  } catch (e) {
    fail(`Imagen 4 Ultra FAILED: ${e.message}`);
    RESULTS['IMAGEN-1'] = { status: 'fail', err: e.message };
  }

  // ── TEST 3: VEO 3.1 ──────────────────────────────────────────────────────
  head('TEST 3 — Veo 3.1 image-to-video (start frame + 4s duration)');
  info('Body shape mirrors generateScene() → veo31 branch');
  info('Uses Marcus character image as the start frame');

  // Use Marcus URL as start frame (not ideal for video — normally would be
  // a generated scene image — but functionally exercises the schema)
  const veoBody = {
    prompt: 'Marcus slowly turns his head toward the camera with a confident smile. Subtle hand movement. 2D illustrated style throughout.',
    image_url: marcusUrl,
    duration: '4s',                // <- NEW: string enum, not integer
    aspect_ratio: '16:9',
    generate_audio: false,
  };

  try {
    info('Sending to Veo 3.1… (60-120 seconds — videos take longer)');
    const { data, elapsed } = await postJson(VEO_3_1, veoBody, 'VEO');
    const url = data.video?.url || data.url || '';
    if (!url) throw new Error('No video URL in response: ' + JSON.stringify(data).slice(0, 300));
    pass(`Veo 3.1 responded in ${elapsed}`);
    pass(`Video URL: ${url}`);
    RESULTS['VEO-1'] = { status: 'pass', url, ms: elapsed };

    try {
      const { size } = await saveBlobFromUrl(url, 'VEO-1_marcus_4s.mp4');
      pass(`Saved (${kb(size)})`);
    } catch (e) { info(`Could not save: ${e.message}`); }
  } catch (e) {
    fail(`Veo 3.1 FAILED: ${e.message}`);
    RESULTS['VEO-1'] = { status: 'fail', err: e.message };
  }

  // ── SUMMARY ──────────────────────────────────────────────────────────────
  console.log(`\n\n${C.bold}${'─'.repeat(70)}${C.reset}`);
  console.log(`${C.bold}  NEW-ENDPOINTS SMOKE TEST RESULTS${C.reset}`);
  console.log(`${'─'.repeat(70)}\n`);

  const tests = [
    ['GEMINI-1', 'Gemini 3 Pro    (image + ref)'],
    ['IMAGEN-1', 'Imagen 4 Ultra  (text-only)  '],
    ['VEO-1',    'Veo 3.1         (start frame + 4s duration)'],
  ];

  let passed = 0, failed = 0;
  for (const [id, label] of tests) {
    const r = RESULTS[id];
    if (!r) { console.log(`  ${C.dim}NORUN${C.reset}  ${id.padEnd(10)} ${label}`); continue; }
    const ok = r.status === 'pass';
    if (ok) passed++; else failed++;
    const badge = ok ? `${C.green}PASS${C.reset}` : `${C.red}FAIL${C.reset}`;
    const detail = ok
      ? `${r.ms} → ${r.url.slice(0, 55)}...`
      : (r.err || '').slice(0, 80);
    console.log(`  ${badge}  ${id.padEnd(10)} ${label}  ${detail}`);
  }

  console.log(`\n  Passed: ${C.green}${passed}${C.reset}   Failed: ${failed > 0 ? C.red : ''}${failed}${C.reset}`);
  console.log(`${'─'.repeat(70)}\n`);

  if (failed > 0) {
    console.log(`${C.red}${C.bold}  ⚠  AT LEAST ONE NEW ENDPOINT IS BROKEN.${C.reset}`);
    console.log(`${C.red}     Do not ship to Chris until each endpoint passes.${C.reset}\n`);
    process.exit(1);
  } else {
    console.log(`${C.green}${C.bold}  ✓ ALL NEW ENDPOINTS WORKING. Schemas verified live against fal.ai.${C.reset}`);
    console.log(`     Generated assets saved to: ${OUT_DIR}\n`);
  }
}

main().catch(err => {
  console.error(`\n${C.red}✗  FATAL: ${err.message}${C.reset}\n`);
  if (err.stack) console.error(err.stack.split('\n').slice(1, 4).join('\n'));
  process.exit(1);
});
