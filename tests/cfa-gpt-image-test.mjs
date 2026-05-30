/**
 * CFA GPT Image Enhancement — Live Model Test
 * ─────────────────────────────────────────────────────────────────────────────
 * Mirrors the workflow's enhanceWithGPT() path EXACTLY:
 *   fetch image → send to OpenAI /v1/images/edits → save corrected result
 *
 * Tests multiple candidate model strings so we know which one is live BEFORE
 * Chris uses it. Whichever passes is the one that should be in the HTML.
 *
 * Usage:  node cfa-gpt-image-test.mjs YOUR_OPENAI_KEY
 */

import fs   from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OAI_KEY   = process.argv[2] || process.env.OPENAI_KEY;
const OUT_DIR   = path.join(__dirname, 'test-output', 'gpt-image');
const IN_IMAGE  = path.join(__dirname, 'test-output', 'IMG-4_marcus-with-ref.png');

const CANDIDATES = ['gpt-image-2', 'gpt-image-2-2026-04-21', 'gpt-image-1.5', 'gpt-image-1'];

const PROMPT =
  'TEXT AND LANGUAGE CORRECTION ONLY. ' +
  'This is a finished 2D illustrated educational video scene. ' +
  'Your ONLY task is to find and fix any text, words, letters, labels, or written language in the image that are: ' +
  'misspelled, garbled, illegible, wrong characters, hieroglyphic-looking, or unclear. ' +
  'Correct them to proper readable English while keeping the font style, size, and position identical. ' +
  'DO NOT change anything else — not the characters, not their faces, expressions, clothing, or positions. ' +
  'NOT the colors, NOT the composition, NOT the background, NOT the art style, NOT the lighting. ' +
  'The 2D illustrated style, every character appearance, and every visual element must remain pixel-for-pixel identical. ' +
  'If there is no text in the image, output it completely unchanged.';

const C = { reset:'\x1b[0m', bold:'\x1b[1m', green:'\x1b[32m', red:'\x1b[31m', dim:'\x1b[2m', cyan:'\x1b[36m' };
const pass = m => console.log(`${C.green}✓${C.reset} ${m}`);
const fail = m => console.log(`${C.red}✗${C.reset} ${m}`);
const info = m => console.log(`${C.dim}ℹ${C.reset} ${m}`);

if (!OAI_KEY) { fail('No OpenAI key. Usage: node cfa-gpt-image-test.mjs YOUR_KEY'); process.exit(1); }
if (!fs.existsSync(IN_IMAGE)) { fail(`Input image not found: ${IN_IMAGE}`); process.exit(1); }
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

async function testModel(model) {
  const t0 = Date.now();
  const buf  = fs.readFileSync(IN_IMAGE);
  const blob = new Blob([buf], { type: 'image/png' });

  const form = new FormData();
  form.append('image', blob, 'scene.png');
  form.append('model', model);
  form.append('n', '1');
  form.append('size', '1536x1024');
  form.append('prompt', PROMPT);

  const resp = await fetch('https://api.openai.com/v1/images/edits', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + OAI_KEY },
    body: form,
  });

  const elapsed = `${((Date.now() - t0) / 1000).toFixed(1)}s`;
  if (!resp.ok) {
    const e = await resp.json().catch(() => ({}));
    const msg = e?.error?.message || JSON.stringify(e);
    return { model, ok: false, msg: `HTTP ${resp.status}: ${msg}`, elapsed };
  }
  const data = await resp.json();
  const b64  = data?.data?.[0]?.b64_json;
  if (!b64) return { model, ok: false, msg: 'No b64_json in response', elapsed };

  const out = path.join(OUT_DIR, `${model}_corrected.png`);
  fs.writeFileSync(out, Buffer.from(b64, 'base64'));
  return { model, ok: true, msg: `saved ${Math.round(b64.length * 0.75 / 1024)}KB → ${out}`, elapsed };
}

(async () => {
  console.log(`\n${C.bold}CFA GPT Image Enhancement — Live Model Test${C.reset}`);
  info(`Input:  ${IN_IMAGE}`);
  info(`Output: ${OUT_DIR}`);
  info(`Testing ${CANDIDATES.length} candidate model strings against /v1/images/edits\n`);

  const results = [];
  for (const model of CANDIDATES) {
    info(`Testing ${C.cyan}${model}${C.reset}… (10-40s)`);
    try {
      const r = await testModel(model);
      results.push(r);
      r.ok ? pass(`${model} — WORKS (${r.elapsed}) — ${r.msg}`)
           : fail(`${model} — ${r.msg}`);
    } catch (err) {
      results.push({ model, ok: false, msg: err.message });
      fail(`${model} — ${err.message}`);
    }
    console.log('');
  }

  console.log(`${C.bold}${'─'.repeat(64)}${C.reset}`);
  const working = results.filter(r => r.ok).map(r => r.model);
  if (working.length) {
    pass(`Working model(s): ${working.join(', ')}`);
    console.log(`${C.bold}  → Use "${working[0]}" in the workflow.${C.reset}`);
    console.log(`  Open the saved PNG(s) to confirm text was corrected & scene unchanged.\n`);
  } else {
    fail('No candidate model worked — see errors above.\n');
    process.exit(1);
  }
})();
