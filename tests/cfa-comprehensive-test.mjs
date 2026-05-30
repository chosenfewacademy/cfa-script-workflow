/**
 * CFA Comprehensive Pipeline Test
 * ─────────────────────────────────────────────────────────────────────────────
 * Runs 12 tests across all character / reference / media-type combinations:
 *
 *   IMAGE TESTS
 *   IMG-1  Marcus  — text-only       → kling-image/v3/text-to-image
 *   IMG-2  Jordan  — text-only       → kling-image/v3/text-to-image
 *   IMG-3  Both    — text-only       → kling-image/v3/text-to-image
 *   IMG-4  Marcus  — with ref        → kling-image/o1  (@Image1 = marcus)
 *   IMG-5  Jordan  — with ref        → kling-image/o1  (@Image1 = jordan)
 *   IMG-6  Both    — with refs       → kling-image/o1  (@Image1 = marcus, @Image2 = jordan)
 *
 *   VIDEO TESTS
 *   VID-1  Marcus  — text-to-video   (no start frame, no subject ref)
 *   VID-2  Jordan  — text-to-video   (no start frame, no subject ref)
 *   VID-3  Both    — text-to-video   (no start frame, no subject ref)
 *   VID-4  Marcus  — image-to-video  (start frame = IMG-4 result, subject_ref = marcus)
 *   VID-5  Jordan  — image-to-video  (start frame = IMG-5 result, subject_ref = jordan)
 *   VID-6  Both    — image-to-video  (start frame = IMG-6 result, subject_ref = marcus)
 *
 * Usage:
 *   node cfa-comprehensive-test.mjs YOUR_FAL_KEY
 *   set FAL_KEY=... && node cfa-comprehensive-test.mjs
 *
 * All generated images are saved to ./test-output/ for visual review.
 */

import fs   from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FAL_KEY   = process.argv[2] || process.env.FAL_KEY;
const OUT_DIR   = path.join(__dirname, 'test-output');

if (!FAL_KEY) {
  console.error('\n✗  No fal.ai API key.\n   Usage: node cfa-comprehensive-test.mjs YOUR_FAL_KEY\n');
  process.exit(1);
}
if (!fs.existsSync(OUT_DIR)) fs.mkdirSync(OUT_DIR, { recursive: true });

// ─── Endpoints ────────────────────────────────────────────────────────────────
const KLING_IMG_TEXT  = 'https://fal.run/fal-ai/kling-image/v3/text-to-image';
const KLING_IMG_O1    = 'https://fal.run/fal-ai/kling-image/o1';
const KLING_VID       = 'https://fal.run/fal-ai/kling-video/v1.6/pro/image-to-video';
const FAL_UPLOAD_INIT = 'https://rest.alpha.fal.ai/storage/upload/initiate';

// ─── Colours ──────────────────────────────────────────────────────────────────
const C = {
  reset:  '\x1b[0m',  bold:   '\x1b[1m',
  green:  '\x1b[32m', red:    '\x1b[31m', yellow: '\x1b[33m',
  cyan:   '\x1b[36m', blue:   '\x1b[34m', dim:    '\x1b[2m',
};
const pass  = (msg) => console.log(`${C.green}✓${C.reset}  ${msg}`);
const fail  = (msg) => console.log(`${C.red}✗${C.reset}  ${msg}`);
const info  = (msg) => console.log(`${C.dim}ℹ${C.reset}  ${msg}`);
const warn  = (msg) => console.log(`${C.yellow}⚠${C.reset}  ${msg}`);
const head  = (msg) => console.log(`\n${C.bold}${C.blue}── ${msg}${C.reset}`);
const timer = (t0)  => `${Date.now() - t0}ms`;
const kb    = (n)   => `${Math.round(n / 1024)}KB`;
const hr    = ()    => console.log('─'.repeat(70));

// ─── Tracking ─────────────────────────────────────────────────────────────────
const RESULTS = {};
const T_START = Date.now();

function record(id, status, data) {
  RESULTS[id] = { id, status, ...data, at: Date.now() - T_START };
}

// ─── fal.ai storage upload ────────────────────────────────────────────────────
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

// ─── Extract base64 from HTML ─────────────────────────────────────────────────
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

// ─── fal.ai call helpers ──────────────────────────────────────────────────────
async function falImage(endpoint, body) {
  const t0   = Date.now();
  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Authorization': 'Key ' + FAL_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const e = await resp.json().catch(() => ({}));
    const m = e?.detail || e?.error || e?.message || JSON.stringify(e) || `HTTP ${resp.status}`;
    throw new Error(`${resp.status}: ${m}`);
  }
  const data = await resp.json();
  const url  = data.images?.[0]?.url || data.image?.url || '';
  if (!url) throw new Error('No image URL in response: ' + JSON.stringify(data).slice(0, 200));
  return { url, ms: Date.now() - t0 };
}

async function falVideo(body) {
  const t0   = Date.now();
  const resp = await fetch(KLING_VID, {
    method: 'POST',
    headers: { 'Authorization': 'Key ' + FAL_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const e = await resp.json().catch(() => ({}));
    const m = e?.detail || e?.error || e?.message || JSON.stringify(e) || `HTTP ${resp.status}`;
    throw new Error(`${resp.status}: ${m}`);
  }
  const data = await resp.json();
  const url  = data.video?.url || data.url || '';
  if (!url) throw new Error('No video URL in response: ' + JSON.stringify(data).slice(0, 200));
  return { url, ms: Date.now() - t0 };
}

// ─── Download and save ────────────────────────────────────────────────────────
async function saveImage(url, filename) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HEAD ${resp.status}`);
  const buf = await resp.arrayBuffer();
  const fp  = path.join(OUT_DIR, filename);
  fs.writeFileSync(fp, Buffer.from(buf));
  return { fp, size: buf.byteLength };
}

// ─────────────────────────────────────────────────────────────────────────────
//  PROMPTS  (written to match SYS_KLING_IMAGE + SYS_KLING_VIDEO styles)
// ─────────────────────────────────────────────────────────────────────────────

// IMAGE prompts — no style directives, no "2D/cartoon" language per SYS_KLING_IMAGE
const IMG_PROMPTS = {

  // Text-only: describe scene + character from scratch (Kling infers style from training)
  marcusText: `Marcus sits at a wooden desk in a warmly lit home office, leaning forward with focused attention toward a monitor displaying a green crypto price chart. His right hand rests on an open notebook filled with hand-drawn calculations. A small orange ceramic mug steams beside a stack of financial books. His expression is calm and certain, brow gently furrowed in concentration.`,

  jordanText: `Jordan stands in a clean modern workspace, one hand raised mid-gesture as if making a key point, expression animated and confident. Behind him a whiteboard shows a simple supply-demand curve. An orange sticky note is pinned to the upper corner of the board. Natural daylight streams evenly through tall windows behind him.`,

  bothText:   `Marcus and Jordan sit across from each other at a round table in a bright collaborative studio. Marcus has a laptop open showing a cryptocurrency portfolio graph, Jordan holds a pen over a printed earnings report. An orange highlighter lies between them on the table surface. Both carry relaxed, engaged expressions — mid-conversation.`,

  // Ref-based: explicitly reference uploaded character images using @Image tags
  marcusRef:  `@Image1 Marcus leans back slightly in a leather chair with arms crossed, a quiet confident smile forming as he considers the question. Behind him on a wooden shelf sits a small orange trophy beside framed certificates. His notebook is open on the desk beside him with a pen clipped to the page.`,

  jordanRef:  `@Image1 Jordan stands at a glass presentation screen, right hand pointing to a clean rising line chart. His expression is assured and engaged, eyebrows slightly raised as he addresses the viewer. An orange laser pointer is in his other hand, and a glass of water sits at the edge of the podium below the screen.`,

  bothRef:    `@Image1 Marcus and @Image2 Jordan stand side by side in a modern studio, both looking directly at the camera with composed, grounded expressions. Marcus has his arms crossed, Jordan holds a tablet in both hands. On a small table between them sits an open orange notebook with a Bitcoin logo embossed on the cover.`,
};

// VIDEO prompts — follow SYS_KLING_VIDEO exactly:
//   lead with character action, specific movements, one micro-expression,
//   camera language, lighting mood, explicit 2D illustrated style note
const VID_PROMPTS = {

  marcusTextVid: `Marcus slowly nods his head as his eyes track left across the screen in front of him, brow gently furrowing then releasing as understanding settles. His right hand rises and extends toward camera in a deliberate pointing gesture — index finger extended, elbow bent. 2D illustrated style with bold clean outlines and flat color shading holds throughout the motion. Camera static medium shot, warm amber room light from the left, soft shadow falling across the right side of frame.`,

  jordanTextVid: `Jordan leans forward from a standing position, one hand pressing flat on the desk as he emphasizes a point, lips parting into a half-smile just as the phrase resolves. His eyes flick downward for a beat then snap directly back to camera — a quick, sharp recalibration. 2D illustrated style with bold clean outlines and flat color shading holds throughout the motion. Camera pushes in slowly from medium shot to medium-close, cold blue studio lighting from above, clean neutral background behind him.`,

  bothTextVid:   `Marcus turns his head to look at Jordan who answers with a slow confirming nod, then both pivot forward to face the viewer together in a moment of shared certainty. Jordan's left shoulder lifts briefly with a quiet exhale, the edge of a genuine smile crossing his face. 2D illustrated style with bold clean outlines and flat color shading holds throughout the motion. Camera pans slightly right then locks static in a two-shot, soft natural window light, warm and even across both figures.`,

  marcusImgVid:  `Marcus lifts his chin slowly and exhales, eyes closing for half a second then reopening with a fresh, settled focus as his right hand reaches out to pick up the orange mug beside him. His fingers curl around the handle and he draws it toward himself without disrupting the calm deliberate energy of the scene. 2D illustrated style with bold clean outlines and flat color shading holds throughout the motion. Camera holds static medium, warm amber lighting unchanged, no camera movement.`,

  jordanImgVid:  `Jordan's pointing hand lowers smoothly as he shifts his weight from right foot to left, landing in a more relaxed, open stance with both hands loose at his sides. His expression transitions out of presentation mode into a quieter, conversational look — mouth softening from a wide gesture into a gentle half-smile. 2D illustrated style with bold clean outlines and flat color shading holds throughout the motion. Camera static, daylight unchanged, subtle fabric movement from ambient air.`,

  bothImgVid:    `Marcus uncrosses his arms and leans slightly toward camera, placing both hands open on his knees in a grounded, settled gesture. Jordan simultaneously turns a quarter step toward Marcus, eyebrows lifting once in acknowledgment, then both settle back into a composed, forward-facing two-shot. 2D illustrated style with bold clean outlines and flat color shading holds throughout the motion. Camera holds static wide, clean even lighting, no camera movement throughout the clip.`,
};

// ─────────────────────────────────────────────────────────────────────────────
//  MAIN
// ─────────────────────────────────────────────────────────────────────────────
async function main() {
  console.log(`\n${C.bold}CFA Comprehensive Pipeline Test — 12 Tests${C.reset}`);
  info(`Output directory: ${OUT_DIR}`);
  hr();

  // ── SETUP: Extract + upload character images ──────────────────────────────
  head('SETUP — Extract characters from HTML + upload to fal.ai storage');

  const htmlPath = path.join(__dirname, 'exports', 'CFA_Script_Workflow_Standalone.html');
  const html     = fs.readFileSync(htmlPath, 'utf8');

  const marcusBuf = b64ToBuffer(extractB64(html, 'MARCUS_B64'));
  const jordanBuf = b64ToBuffer(extractB64(html, 'JORDAN_B64'));
  pass(`MARCUS_B64 extracted (${kb(marcusBuf.length)}, JPEG)`);
  pass(`JORDAN_B64 extracted (${kb(jordanBuf.length)}, JPEG)`);

  info('Uploading both characters in parallel…');
  const t0 = Date.now();
  const [marcusUrl, jordanUrl] = await Promise.all([
    uploadToFal(marcusBuf, 'marcus.jpg'),
    uploadToFal(jordanBuf, 'jordan.jpg'),
  ]);
  pass(`Marcus storage URL: ${marcusUrl} (${timer(t0)})`);
  pass(`Jordan storage URL: ${jordanUrl}`);

  // ── PHASE 1: Run IMAGE tests + text-to-video simultaneously ──────────────
  head('PHASE 1 — All 6 image tests + 3 text-to-video tests (9 simultaneous)');
  info('Launching 9 requests in parallel… stand by.\n');

  const [
    r_img1, r_img2, r_img3,   // text-only images
    r_img4, r_img5, r_img6,   // ref-based images
    r_vid1, r_vid2, r_vid3,   // text-to-video
  ] = await Promise.allSettled([

    // IMG-1: Marcus text-only
    falImage(KLING_IMG_TEXT, {
      prompt: IMG_PROMPTS.marcusText,
      aspect_ratio: '16:9', num_images: 1,
    }).then(r => { pass(`IMG-1 ✓ Marcus text-only — ${r.ms}ms`); return r; }),

    // IMG-2: Jordan text-only
    falImage(KLING_IMG_TEXT, {
      prompt: IMG_PROMPTS.jordanText,
      aspect_ratio: '16:9', num_images: 1,
    }).then(r => { pass(`IMG-2 ✓ Jordan text-only — ${r.ms}ms`); return r; }),

    // IMG-3: Both text-only
    falImage(KLING_IMG_TEXT, {
      prompt: IMG_PROMPTS.bothText,
      aspect_ratio: '16:9', num_images: 1,
    }).then(r => { pass(`IMG-3 ✓ Both text-only — ${r.ms}ms`); return r; }),

    // IMG-4: Marcus with ref
    falImage(KLING_IMG_O1, {
      prompt: IMG_PROMPTS.marcusRef,
      aspect_ratio: '16:9', num_images: 1,
      image_urls: [marcusUrl],
    }).then(r => { pass(`IMG-4 ✓ Marcus with ref — ${r.ms}ms`); return r; }),

    // IMG-5: Jordan with ref
    falImage(KLING_IMG_O1, {
      prompt: IMG_PROMPTS.jordanRef,
      aspect_ratio: '16:9', num_images: 1,
      image_urls: [jordanUrl],
    }).then(r => { pass(`IMG-5 ✓ Jordan with ref — ${r.ms}ms`); return r; }),

    // IMG-6: Both with refs
    falImage(KLING_IMG_O1, {
      prompt: IMG_PROMPTS.bothRef,
      aspect_ratio: '16:9', num_images: 1,
      image_urls: [marcusUrl, jordanUrl],
    }).then(r => { pass(`IMG-6 ✓ Both with refs — ${r.ms}ms`); return r; }),

    // VID-1: Marcus text-to-video (no start frame)
    falVideo({
      prompt: VID_PROMPTS.marcusTextVid,
      duration: 5, aspect_ratio: '16:9',
    }).then(r => { pass(`VID-1 ✓ Marcus text-to-video — ${r.ms}ms`); return r; }),

    // VID-2: Jordan text-to-video (no start frame)
    falVideo({
      prompt: VID_PROMPTS.jordanTextVid,
      duration: 5, aspect_ratio: '16:9',
    }).then(r => { pass(`VID-2 ✓ Jordan text-to-video — ${r.ms}ms`); return r; }),

    // VID-3: Both text-to-video (no start frame)
    falVideo({
      prompt: VID_PROMPTS.bothTextVid,
      duration: 5, aspect_ratio: '16:9',
    }).then(r => { pass(`VID-3 ✓ Both text-to-video — ${r.ms}ms`); return r; }),

  ]);

  // Collect image URLs needed for Phase 2 video tests
  const img4Url = r_img4.status === 'fulfilled' ? r_img4.value.url : null;
  const img5Url = r_img5.status === 'fulfilled' ? r_img5.value.url : null;
  const img6Url = r_img6.status === 'fulfilled' ? r_img6.value.url : null;

  // Report Phase 1 failures
  [[r_img1,'IMG-1'],[r_img2,'IMG-2'],[r_img3,'IMG-3'],
   [r_img4,'IMG-4'],[r_img5,'IMG-5'],[r_img6,'IMG-6'],
   [r_vid1,'VID-1'],[r_vid2,'VID-2'],[r_vid3,'VID-3']].forEach(([r,id]) => {
    if (r.status === 'rejected') fail(`${id} FAILED: ${r.reason?.message || r.reason}`);
  });

  // ── PHASE 2: image-to-video using Phase 1 generated images ───────────────
  head('PHASE 2 — 3 image-to-video tests (using Phase 1 generated images as start frames)');

  if (!img4Url && !img5Url && !img6Url) {
    warn('All ref-based images failed — skipping image-to-video tests');
  } else {
    info('Launching 3 image-to-video requests in parallel…\n');

    const buildVideoBody = (prompt, imageUrl, subjectRefUrl) => {
      const body = { prompt, duration: 5, aspect_ratio: '16:9' };
      if (imageUrl)      body.image_url = imageUrl;
      if (subjectRefUrl) body.subject_reference_image_url = subjectRefUrl;
      return body;
    };

    const [r_vid4, r_vid5, r_vid6] = await Promise.allSettled([

      // VID-4: Marcus image-to-video
      img4Url
        ? falVideo(buildVideoBody(VID_PROMPTS.marcusImgVid, img4Url, marcusUrl))
            .then(r => { pass(`VID-4 ✓ Marcus image-to-video — ${r.ms}ms`); return r; })
        : Promise.reject(new Error('IMG-4 unavailable')),

      // VID-5: Jordan image-to-video
      img5Url
        ? falVideo(buildVideoBody(VID_PROMPTS.jordanImgVid, img5Url, jordanUrl))
            .then(r => { pass(`VID-5 ✓ Jordan image-to-video — ${r.ms}ms`); return r; })
        : Promise.reject(new Error('IMG-5 unavailable')),

      // VID-6: Both image-to-video
      img6Url
        ? falVideo(buildVideoBody(VID_PROMPTS.bothImgVid, img6Url, marcusUrl))
            .then(r => { pass(`VID-6 ✓ Both image-to-video — ${r.ms}ms`); return r; })
        : Promise.reject(new Error('IMG-6 unavailable')),

    ]);

    [[r_vid4,'VID-4'],[r_vid5,'VID-5'],[r_vid6,'VID-6']].forEach(([r,id]) => {
      if (r.status === 'rejected') fail(`${id} FAILED: ${r.reason?.message || r.reason}`);
    });

    // Attach video results for summary
    Object.assign(RESULTS, {
      'VID-4': r_vid4.status === 'fulfilled' ? { status: 'pass', ...r_vid4.value } : { status: 'fail', err: r_vid4.reason?.message },
      'VID-5': r_vid5.status === 'fulfilled' ? { status: 'pass', ...r_vid5.value } : { status: 'fail', err: r_vid5.reason?.message },
      'VID-6': r_vid6.status === 'fulfilled' ? { status: 'pass', ...r_vid6.value } : { status: 'fail', err: r_vid6.reason?.message },
    });
  }

  // ── Save all generated images locally ─────────────────────────────────────
  head('Saving generated images to ./test-output/');

  const imageTests = [
    [r_img1, 'IMG-1_marcus-text-only.png'],
    [r_img2, 'IMG-2_jordan-text-only.png'],
    [r_img3, 'IMG-3_both-text-only.png'],
    [r_img4, 'IMG-4_marcus-with-ref.png'],
    [r_img5, 'IMG-5_jordan-with-ref.png'],
    [r_img6, 'IMG-6_both-with-refs.png'],
  ];

  await Promise.allSettled(imageTests.map(async ([r, fname]) => {
    if (r.status !== 'fulfilled') return;
    try {
      const { size } = await saveImage(r.value.url, fname);
      pass(`Saved ${fname} (${kb(size)})`);
    } catch(e) {
      warn(`Could not save ${fname}: ${e.message}`);
    }
  }));

  // ── Final summary ─────────────────────────────────────────────────────────
  const totalMs = Date.now() - T_START;

  console.log(`\n\n${C.bold}${'─'.repeat(70)}${C.reset}`);
  console.log(`${C.bold}  COMPREHENSIVE TEST RESULTS${C.reset}`);
  console.log(`${'─'.repeat(70)}\n`);

  const all = [
    ['IMG-1', 'Marcus  text-only image',    r_img1],
    ['IMG-2', 'Jordan  text-only image',    r_img2],
    ['IMG-3', 'Both    text-only image',    r_img3],
    ['IMG-4', 'Marcus  ref-based image',    r_img4],
    ['IMG-5', 'Jordan  ref-based image',    r_img5],
    ['IMG-6', 'Both    ref-based image',    r_img6],
    ['VID-1', 'Marcus  text-to-video',      r_vid1],
    ['VID-2', 'Jordan  text-to-video',      r_vid2],
    ['VID-3', 'Both    text-to-video',      r_vid3],
  ];

  // Add Phase 2 video results if they exist
  const vid4 = RESULTS['VID-4'];
  const vid5 = RESULTS['VID-5'];
  const vid6 = RESULTS['VID-6'];

  let passed = 0, failed = 0;

  for (const [id, label, r] of all) {
    const ok = r.status === 'fulfilled';
    if (ok) passed++; else failed++;
    const badge = ok ? `${C.green}PASS${C.reset}` : `${C.red}FAIL${C.reset}`;
    const detail = ok
      ? `${r.value.ms}ms → ${r.value.url.slice(0, 60)}...`
      : r.reason?.message?.slice(0, 80);
    console.log(`  ${badge}  ${id.padEnd(6)} ${label.padEnd(28)} ${detail}`);
  }

  for (const [id, label, r] of [
    ['VID-4', 'Marcus  image-to-video', vid4],
    ['VID-5', 'Jordan  image-to-video', vid5],
    ['VID-6', 'Both    image-to-video', vid6],
  ]) {
    if (!r) { console.log(`  ${C.dim}SKIP   ${id}     ${label}${C.reset}`); continue; }
    const ok = r.status === 'pass';
    if (ok) passed++; else failed++;
    const badge  = ok ? `${C.green}PASS${C.reset}` : `${C.red}FAIL${C.reset}`;
    const detail = ok ? `${r.ms}ms → ${r.url.slice(0, 60)}...` : r.err?.slice(0, 80);
    console.log(`  ${badge}  ${id.padEnd(6)} ${label.padEnd(28)} ${detail}`);
  }

  console.log(`\n  Total time: ${Math.round(totalMs/1000)}s   Passed: ${C.green}${passed}${C.reset}   Failed: ${failed > 0 ? C.red : ''}${failed}${C.reset}`);
  console.log(`${'─'.repeat(70)}\n`);

  // Full URL dump for browser review
  console.log(`${C.bold}  GENERATED ASSET URLs (open each in browser to inspect):${C.reset}\n`);
  for (const [id, label, r] of all) {
    if (r.status === 'fulfilled') console.log(`  ${id}  ${label}\n      ${r.value.url}\n`);
  }
  for (const [id, label, r] of [
    ['VID-4', 'Marcus  image-to-video', vid4],
    ['VID-5', 'Jordan  image-to-video', vid5],
    ['VID-6', 'Both    image-to-video', vid6],
  ]) {
    if (r?.status === 'pass') console.log(`  ${id}  ${label}\n      ${r.url}\n`);
  }

  console.log(`  Generated images also saved to:\n  ${OUT_DIR}\n`);
  console.log(`${'─'.repeat(70)}\n`);
}

main().catch(err => {
  console.error(`\n${C.red}✗  FATAL: ${err.message}${C.reset}\n`);
  if (err.stack) console.error(err.stack.split('\n').slice(1,4).join('\n'));
  process.exit(1);
});
