# Guide for Chris (reviewer)

## Open the tool
- Go to https://chosenfewacademy.github.io/cfa-script-workflow/CFA_Script_Workflow.html in Chrome.
- In **Settings**, enter the renderer URL (the public ngrok address, not 127.0.0.1) and your access token.
  - You get the token privately from the owner. It never goes in the repo or in chat.
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
- **Add a key:** `python3 ~/cfa-render/keys.py add NAME /path/to/key.txt`. The key is written only to that file (mode 0600) and is never printed. Hand it over privately.
- **Revoke a key:** `python3 ~/cfa-render/keys.py revoke NAME`. The key stops working on the next request, with no restart. You can also delete the name from the keys file.
- **List keys:** `python3 ~/cfa-render/keys.py list` shows names only.
