# Designed Living

Turn a house into a designed home: start from **room photos**, a **floor plan** (picture or PDF) or a **Sweet Home 3D
OBJ**, choose from 14 styles (whole house or room by room), get a photo-real mood board per room, and export an
offline 3D walkthrough website and a mood board PDF.

It runs on your own PC, in your browser, with your own Gemini and Anthropic keys. No installs beyond Python.

## Install on Windows (once)

1. Python 3.11 or newer from python.org (tick "Add python.exe to PATH").
2. In a terminal:

   ```
   git clone https://github.com/FaiekA/house-build C:\DesignedLiving
   ```

3. Double-click `C:\DesignedLiving\start.bat` (or run `py app.py` in that folder). Your browser opens at
   http://127.0.0.1:4800.
4. Open **Settings**, paste your Gemini key (aistudio.google.com) and, for better plan reading, your Anthropic key
   (console.anthropic.com), press Save keys, then Test both keys.

To update later: `cd C:\DesignedLiving` then `git pull`.

## The three ways in

| Start from | What happens | Needs |
| --- | --- | --- |
| Room photos | Each photo is one room. Nano Banana restyles it in the style you pick, keeping the room's shape, windows and doors. Mood board PDF with before and after. | Gemini key |
| Floor plan | Claude and Gemini read the plan together into rooms, walls, doors and windows. Fix anything with the Walls and Doors tools. Then design, furnish, walkthrough website, mood board. | Gemini key, Anthropic key recommended |
| OBJ model | A Sweet Home 3D export (OBJ, or a zip with its MTL and pictures). Cut into a plan, then as above. | Gemini key for the design |

## Where things are kept

- Houses: `C:\DesignedLiving\Houses\<client name>\` (or the folder set in Settings). Each holds the uploads in
  `model\`, the room photos in `design\`, the walkthrough website and the mood board PDF.
- Keys: `config.json` beside the app. Never served to a page, never written into an exported website.
- Costs: `.usage.json`, shown on the Settings page.

## For developers

See `CLAUDE.md`. `py app.py --selftest` runs the offline checks (no model calls).
