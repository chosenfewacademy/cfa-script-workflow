# Guide for Chris (reviewer)

## Open the tool
- Go to https://chosenfewacademy.github.io/cfa-script-workflow/CFA_Script_Workflow.html in Chrome.
- In **Settings**, enter the renderer URL (the public ngrok address, not 127.0.0.1) and your access key.

### Get your own access key (first time only)
1. In **⚙ Settings → Grok Bot render service**, paste the renderer URL.
2. Click **🔑 Get my access key**, type your first name (`chris`) and click **Get key**.
3. Your key appears **once**. Click **Copy** and save it somewhere private (a password manager). The tool also fills it in for this tab, so you can start right away.
- Next time, paste the URL and your saved key into the two fields and click **Save**.
- The offer works once and expires after 7 days. If you see "already collected" or "expired", or you lose the key, ask the owner to open a new one.
- Nobody else ever sees your key: the renderer keeps only a scrambled fingerprint (hash) of it.
  - For safety, the URL, the token and any API keys are kept only for this browser tab (session storage). Enter them again after you close the tab.
- Paste or write the script, then follow the steps. Full narration is on: Bill narrates and quotes the characters, with no lip-sync.

## v8 look (locked)
Every render follows the v8 standard in `docs/V8_LOCKED_STYLE.md`:
- 2K stills with crisp props;
- one character and one phone per shot;
- slow camera moves that aim at what the narration names;
- the script-fidelity check (each shot must act out its own line).

## Giving feedback
- Each step has a feedback box. In full narration the lip-sync step is called "Narration (Bill quoting characters)".
- Rate the step, write what to change, then send it with **Suggest a tool improvement**.
- Or use **Apply to this episode now**, which changes only the current episode.
- You'll see a "Changes may take up to 24 hours" notice. A **Changes ready** notice appears when a suggestion is live.
- Accepted suggestions become standing rules ("memory") that later generations follow.

## Changing things yourself
- **In the tool:** model choice, video format and still checks are saved in this browser (local storage); the renderer URL, token and API keys last for the tab only. Use "Apply to this episode now" for per-episode changes.
- **In the code:** you need collaborator access to `chosenfewacademy/cfa-script-workflow`. Every change goes through a pull request and must pass the test suites:
  - `tools/render/test_*.py`
  - `tests/cfa-adversarial-mock-test.py`
- **Quality check:** `tools/render/baseline_check.py` compares any render against v8.

## Access keys (owner)
- Chris has his **own** renderer key, separate from the owner's.
  - The renderer stores only a SHA-256 hash of it, in `/home/box/secrets/cfa_render_keys.json` (mode 0600, outside the repo). You can point it elsewhere with `CFA_RENDER_KEYS_FILE`.
  - The owner's token (`CFA_RENDER_TOKEN_FILE`) keeps working.
- **Let someone collect their own key in the tool (recommended):** `python3 ~/cfa-render/keys.py open-claim NAME [DAYS]` (default 7 days, max 30). NAME can then click **Get my access key** in Settings once. Nothing secret has to be relayed.
  - Claiming replaces any older key for that NAME, so the old one stops working.
  - Safety: only the tool's own page (`https://chosenfewacademy.github.io`) may claim; other sites and scripts get 403. Attempts are rate-limited (5 per person, 30 total per 10 minutes). A slot works once, then locks.
  - **Reopen** (lost key, or someone else claimed it): run `open-claim NAME` again. Their new key replaces the old one when claimed. To cut access right away, `revoke NAME` first.
  - **Close an unused slot:** `python3 ~/cfa-render/keys.py close-claim NAME`.
  - Slots live in `/home/box/secrets/cfa_render_claims.json` (0600, no keys in it; override with `CFA_RENDER_CLAIMS_FILE`).
- **Add a key:** `python3 ~/cfa-render/keys.py add NAME /path/to/key.txt`. The key is written only to that file (mode 0600) and is never printed. Hand it over privately.
- **Revoke a key:** `python3 ~/cfa-render/keys.py revoke NAME`. The key stops working on the next request, with no restart. You can also delete the name from the keys file.
- **List keys:** `python3 ~/cfa-render/keys.py list` shows names and claim slots (open / claimed / expired), never keys.
