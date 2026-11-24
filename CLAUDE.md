# Designed Living: working notes for Claude

Taken out of Jarvis 2.0's House Plan Build on 2026-11-24 (Faiek). Its own app, its own repo (FaiekA/house-build),
installed at `C:\DesignedLiving` on Faiek's PCs.

## Architecture rules
- Standard-library Python only, no compiled dependency (Smart App Control is on: never ask to turn it off). No pip.
- `app.py` is the server: ThreadingHTTPServer on 127.0.0.1:4800, serves only `web/` and `/api/*`. Every request is
  refused unless the Host is its own (DNS rebinding); every POST also needs its own Origin and a JSON body (uploads:
  raw bytes + `X-Filename`).
- Keys live in `config.json` (git-ignored, mode 600, atomic write). `GET /api/settings` shows "set, ending abcd",
  never the key. `export` refuses a website holding any config secret (`secrets`, `houseplan.no_secrets`).
- The walkthrough preview is served with a CSP and shown in a `sandbox="allow-scripts"` frame: it can never call the app.
- Pages (`web/`): `index.html` (launch screen + start page), `house.html` (the editor), `styles.html` (the 14
  styles, whole house or per room), `settings.html` (keys, models, costs). Shared `app.css`. No framework, no bundler;
  only Google Fonts from outside.
- The walkthrough engine is `houseplan/walkthrough-template.html`, BUILT in the cloud from `houseplan/engine/`
  (three, GSAP, Lenis, esbuild; `./build.sh`) and committed. npm never runs on the PC.
- Modules: `houseplan.py` (houses, plan, export, mood board PDF), `housedesign.py` (styles + `STYLE_NOTES`, Gemini
  photo/read/locate, Claude plan rules, furnishing), `photorooms.py` (the room-photos route), `printing.py` (PDF by
  hand), `usage.py` (costs, features plan/design/photos), `recycle.py` (delete = Recycle Bin).
- Every Claude or Gemini call records its usage. Claude is called over raw HTTPS with streaming (no SDK).
- `py app.py --selftest` must pass before calling a change done; it makes no model calls.
