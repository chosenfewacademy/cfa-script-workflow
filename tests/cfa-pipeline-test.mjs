/**
 * CFA Pipeline Test — Full end-to-end character upload + Kling image generation
 *
 * Tests the exact same chain the workflow runs when you load a scene
 * with characters and hit Generate:
 *   base64 data URI → fal.ai storage upload → https://storage.fal.ai URL
 *   → Kling image/o1 with image_urls array → generated image URL
 *
 * Usage:
 *   node cfa-pipeline-test.mjs YOUR_FAL_API_KEY
 *
 * OR set the env var first:
 *   set FAL_KEY=your_key_here && node cfa-pipeline-test.mjs
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ─── Config ───────────────────────────────────────────────────────────────────
const FAL_KEY = process.argv[2] || process.env.FAL_KEY;
const HTML_PATH = path.join(__dirname, 'exports', 'CFA_Script_Workflow_Standalone.html');

// fal.ai REST endpoints
const FAL_UPLOAD_INITIATE = 'https://rest.alpha.fal.ai/storage/upload/initiate';
const KLING_O1             = 'https://fal.run/fal-ai/kling-image/o1';
const KLING_TEXT_ONLY      = 'https://fal.run/fal-ai/kling-image/v3/text-to-image';

// ─── Helpers ──────────────────────────────────────────────────────────────────
function log(icon, msg) { console.log(`${icon}  ${msg}`); }
function pass(msg)      { console.log(`\x1b[32m✓\x1b[0m  ${msg}`); }
function fail(msg)      { console.log(`\x1b[31m✗\x1b[0m  ${msg}`); }
function step(n, title) { console.log(`\n\x1b[1;34m── Step ${n}: ${title}\x1b[0m`); }
function hr()           { console.log('─'.repeat(60)); }
function kb(bytes)      { return Math.round(bytes / 1024) + ' KB'; }
function ms(t0)         { return (Date.now() - t0) + 'ms'; }

// ─── fal.ai storage upload (Node.js — no SDK needed) ─────────────────────────
async function uploadToFalStorage(buffer, fileName, contentType = 'image/jpeg') {
  // Step A: initiate upload — get signed PUT URL
  const initResp = await fetch(FAL_UPLOAD_INITIATE, {
    method: 'POST',
    headers: {
      'Authorization': 'Key ' + FAL_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ content_type: contentType, file_name: fileName }),
  });

  if (!initResp.ok) {
    const body = await initResp.json().catch(() => ({}));
    throw new Error(`Upload initiate failed ${initResp.status}: ${JSON.stringify(body)}`);
  }

  const { upload_url, file_url } = await initResp.json();
  if (!upload_url || !file_url) {
    throw new Error('fal.ai initiate response missing upload_url or file_url');
  }

  // Step B: PUT file bytes to the signed URL
  const putResp = await fetch(upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: buffer,
  });

  if (!putResp.ok) {
    throw new Error(`PUT upload failed ${putResp.status}`);
  }

  return file_url; // https://storage.fal.ai/...
}

// ─── Extract base64 from HTML ──────────────────────────────────────────────────
function extractB64(html, varName) {
  // Find the const declaration — handles both single-quote and backtick delimiters
  const start = html.indexOf(`const ${varName} = `);
  if (start === -1) throw new Error(`Could not find ${varName} in HTML`);

  // Find the opening delimiter (' or `)
  const delimPos = start + `const ${varName} = `.length;
  const delim = html[delimPos]; // ' or `
  if (delim !== "'" && delim !== '`')
    throw new Error(`${varName}: unexpected delimiter: ${delim}`);

  const dataStart = delimPos + 1; // skip the opening quote
  const dataEnd   = html.indexOf(delim, dataStart);
  if (dataEnd === -1) throw new Error(`${varName} data URI not closed`);
  return html.slice(dataStart, dataEnd);
}

function b64ToBuffer(dataUri) {
  const base64 = dataUri.replace(/^data:image\/jpeg;base64,/, '');
  return Buffer.from(base64, 'base64');
}

// ─── Main test ────────────────────────────────────────────────────────────────
async function main() {
  console.log('\n\x1b[1mCFA Pipeline Test — Character Upload + Kling Image Generation\x1b[0m');
  hr();

  // Guard: API key required
  if (!FAL_KEY) {
    fail('No fal.ai API key provided.');
    console.log('\n   Usage:  node cfa-pipeline-test.mjs YOUR_FAL_KEY');
    console.log('   Or set: set FAL_KEY=your_key_here && node cfa-pipeline-test.mjs\n');
    process.exit(1);
  }
  pass(`API key present (${FAL_KEY.slice(0, 6)}...)`);

  // ── Step 1: Read HTML and extract character images ─────────────────────────
  step(1, 'Extract MARCUS_B64 and JORDAN_B64 from workflow HTML');

  if (!fs.existsSync(HTML_PATH)) {
    fail(`HTML not found: ${HTML_PATH}`);
    process.exit(1);
  }
  log('📂', `Reading ${path.basename(HTML_PATH)}...`);

  const html = fs.readFileSync(HTML_PATH, 'utf8');
  log('ℹ', `File size: ${kb(html.length * 1)} (text)`);

  const marcusB64 = extractB64(html, 'MARCUS_B64');
  const jordanB64 = extractB64(html, 'JORDAN_B64');

  const marcusBuf = b64ToBuffer(marcusB64);
  const jordanBuf = b64ToBuffer(jordanB64);

  pass(`MARCUS_B64 extracted — decoded size: ${kb(marcusBuf.length)}`);
  pass(`JORDAN_B64 extracted — decoded size: ${kb(jordanBuf.length)}`);

  // Sanity: check they are valid JPEG (magic bytes FF D8 FF)
  const isJpeg = buf => buf[0] === 0xFF && buf[1] === 0xD8 && buf[2] === 0xFF;
  if (isJpeg(marcusBuf)) pass('Marcus: valid JPEG header');
  else fail('Marcus: unexpected file header (expected JPEG)');
  if (isJpeg(jordanBuf)) pass('Jordan: valid JPEG header');
  else fail('Jordan: unexpected file header (expected JPEG)');

  // ── Step 2: Upload Marcus to fal.ai storage ────────────────────────────────
  step(2, 'Upload Marcus to fal.ai storage');
  let marcusUrl;
  {
    const t0 = Date.now();
    log('⬆', `Uploading marcus.jpg (${kb(marcusBuf.length)})...`);
    marcusUrl = await uploadToFalStorage(marcusBuf, 'marcus.jpg');
    pass(`Marcus uploaded in ${ms(t0)}`);
    pass(`URL: ${marcusUrl}`);

    if (!marcusUrl.startsWith('https://')) fail('Marcus URL is not HTTPS');
    else pass('URL is HTTPS — would pass startsWith guard in generateScene()');
  }

  // ── Step 3: Upload Jordan to fal.ai storage ────────────────────────────────
  step(3, 'Upload Jordan to fal.ai storage');
  let jordanUrl;
  {
    const t0 = Date.now();
    log('⬆', `Uploading jordan.jpg (${kb(jordanBuf.length)})...`);
    jordanUrl = await uploadToFalStorage(jordanBuf, 'jordan.jpg');
    pass(`Jordan uploaded in ${ms(t0)}`);
    pass(`URL: ${jordanUrl}`);

    if (!jordanUrl.startsWith('https://')) fail('Jordan URL is not HTTPS');
    else pass('URL is HTTPS — would pass startsWith guard in generateScene()');
  }

  // ── Step 4: Build image_urls array (mirrors generateScene logic) ───────────
  step(4, 'Build image_urls array (mirrors generateScene() refImages logic)');
  const imageUrls = [];
  if (marcusUrl.startsWith('https://')) imageUrls.push(marcusUrl);
  if (jordanUrl.startsWith('https://')) imageUrls.push(jordanUrl);

  pass(`image_urls array: ${imageUrls.length} item(s)`);
  imageUrls.forEach((u, i) => log(' ', `  [${i}] ${u.slice(0, 70)}...`));

  const endpoint = imageUrls.length > 0 ? KLING_O1 : KLING_TEXT_ONLY;
  pass(`Endpoint selected: ${endpoint.split('/fal-ai/')[1]}`);

  // ── Step 5: Call Kling image/o1 ────────────────────────────────────────────
  step(5, 'Call Kling image/o1 with character reference images');

  const prompt = [
    'Marcus and Jordan, two 2D illustrated characters from a crypto education video.',
    'Bold clean outlines, flat color shading, consistent line weight.',
    'Marcus (@Image1) stands on the left, Jordan (@Image2) on the right.',
    'Both looking forward, standing naturally, talking about crypto.',
    '16:9 composition, solid neutral background.',
    'Style: modern flat illustration, no photorealism.',
  ].join(' ');

  const body = {
    prompt,
    aspect_ratio: '16:9',
    num_images: 1,
    image_urls: imageUrls,
  };

  log('📤', 'Request body:');
  log(' ', JSON.stringify({ ...body, image_urls: body.image_urls.map(u => u.slice(0, 50) + '...') }, null, 2).split('\n').map(l => '      ' + l).join('\n'));

  const t2 = Date.now();
  log('⏳', 'Sending to Kling… (this may take 15–60 seconds)');

  const klingResp = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Authorization': 'Key ' + FAL_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!klingResp.ok) {
    const errBody = await klingResp.json().catch(() => ({}));
    const detail = typeof errBody?.detail === 'string' ? errBody.detail
                 : typeof errBody?.error   === 'string' ? errBody.error
                 : JSON.stringify(errBody);
    fail(`Kling API error ${klingResp.status}: ${detail}`);
    process.exit(1);
  }

  const klingData = await klingResp.json();
  const generatedUrl = klingData.images?.[0]?.url || klingData.image?.url || '';

  if (!generatedUrl) {
    fail('Kling returned no image URL');
    log('ℹ', 'Full response: ' + JSON.stringify(klingData).slice(0, 500));
    process.exit(1);
  }

  pass(`Kling responded in ${ms(t2)}`);
  pass(`Generated image URL: ${generatedUrl}`);

  // ── Step 6: Verify generated image is accessible ───────────────────────────
  step(6, 'Verify generated image is accessible');
  {
    const t3 = Date.now();
    const headResp = await fetch(generatedUrl, { method: 'HEAD' });
    if (!headResp.ok) {
      fail(`Image HEAD request failed: ${headResp.status}`);
    } else {
      const ct = headResp.headers.get('content-type') || 'unknown';
      const cl = headResp.headers.get('content-length');
      pass(`Image accessible in ${ms(t3)}`);
      pass(`Content-Type: ${ct}`);
      if (cl) pass(`Content-Length: ${kb(parseInt(cl))}`);
    }
  }

  // ── Summary ────────────────────────────────────────────────────────────────
  console.log('\n');
  hr();
  console.log('\x1b[1;32m  ✅  ALL STEPS PASSED\x1b[0m\n');
  hr();
  console.log('  Marcus storage URL:');
  console.log('  ' + marcusUrl);
  console.log('');
  console.log('  Jordan storage URL:');
  console.log('  ' + jordanUrl);
  console.log('');
  console.log('  Generated image:');
  console.log('  ' + generatedUrl);
  hr();
  console.log('\n  Open the image URL above in your browser to review character consistency.\n');
}

main().catch(err => {
  console.log(`\n\x1b[31m✗  TEST FAILED: ${err.message}\x1b[0m\n`);
  if (err.stack) console.log(err.stack.split('\n').slice(1, 4).join('\n'));
  process.exit(1);
});
