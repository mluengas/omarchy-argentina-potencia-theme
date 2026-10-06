# scripts/

Builder tooling for the Argentina Potencia theme. All paths are relative to the
repo root. `work/` is gitignored (downloads, generated images, contact sheets).

## `fetch.py`

Downloads candidates from `research/candidates.json` into
`work/candidates/<id>.<ext>`, skipping files that already exist. Sends a
descriptive `User-Agent` (required by Wikimedia). Verifies each image is
≥3840×2160 and croppable to 16:9 without upscaling, and that its license is in
the SPEC allowlist (PD, CC0, CC BY, CC BY-SA, Unsplash). Writes
`work/candidates/report.json` with `{id, pass, reason}` per candidate.

```sh
python3 scripts/fetch.py                 # uses research/candidates.json
python3 scripts/fetch.py work/test.json  # custom input (testing)
```

## `contact.sh`

Builds `work/contact/sheet.jpg`: a labeled grid of every passing candidate plus
everything in `work/generated/`. Tiles ~640px wide, ≤4 columns, total width
≤2600px, id printed under each tile.

```sh
bash scripts/contact.sh
```

## `finalize.py`

For each chosen id (in order), smart-crops to 16:9 (center by default), resizes
to 3840×2160 with Lanczos, converts to sRGB JPEG q90, strips metadata, and
writes `backgrounds/NN-<id>.jpg`. Regenerates `CREDITS.md` from
`research/candidates.json`; generated images are credited as "Generated for this
theme".

Optional per-id crop gravity: put `{ "<id>": "North" }` in
`scripts/gravity_overrides.json` (valid: NorthWest, North, NorthEast, West,
Center, East, SouthWest, South, SouthEast).

```sh
python3 scripts/finalize.py fitzroy-sunrise perito-moreno jacaranda-skyline
```

## `generate.py`

Generates the two stylized wallpapers via OpenRouter. Picks the best available
image-output model (prefers Google Gemini image / Nano Banana Pro = Gemini 3 Pro
Image), names exact palette hex colors in the prompts (`#74acdf`, `#ffffff`,
`#f6b40e`, `#0e1a2b`), forbids text/watermarks/flags-with-text, and
crops/upscales to 3840×2160. Saves to `work/generated/<slug>.png` and logs the
per-call cost from the response `usage`. Hard cap: stops above $2.00 cumulative.

Requires `pi auth print-api-key --provider openrouter`.

```sh
python3 scripts/generate.py
```
