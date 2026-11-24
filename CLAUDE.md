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
- The walkthrough shows furniture as pictures cut out of each room's designed photo (`housedesign.cut_photo`: Gemini
  boxes + masks, kept in `design/<room>.cuts.json`; `houseplan/engine/src/cutouts.js` turns them into upright cards
  that face you). Drawn blocks only where a room has no photo or a piece has no cut-out. `/api/gallery` lists every
  designed photo; the launch screen, start page and style cards show those real pictures.
- The white model (plan and model houses): `/api/preview?snap=1` draws the walkthrough in plain white with its furniture
  and photographs each room from its tour stop (`SHOTS` in main.js); the editor saves each as `snaps/<room>.jpg` with
  its camera (`view`). The design run then makes that room's photo from its snapshot (`housedesign.snapshot_prompt` +
  `restyle_photo`) and the tour stops at that camera. A snapshot counts only while `houseplan.shape_key` matches.
- Every Claude or Gemini call records its usage. Claude is called over raw HTTPS with streaming (no SDK).
- `py app.py --selftest` must pass before calling a change done; it makes no model calls.
