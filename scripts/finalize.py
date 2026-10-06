#!/usr/bin/env python3
"""finalize.py — Smart-crop, resize, and finalize chosen candidate images.

Usage: finalize.py <id> [<id>...]

For each given id (in order), finds the downloaded candidate in
work/candidates/<id>.*, smart-crops it to 16:9 aspect ratio, resizes to
3840×2160 with Lanczos, converts to sRGB JPEG q90 with metadata stripped,
and writes backgrounds/NN-<id>.jpg (NN = 01, 02, ...).

Upscaling is refused for real photographs: if the largest 16:9 crop of the
source would be narrower than 3840px or shorter than 2160px, the image is
skipped. Generated images (work/generated/<slug>.png) are allowed to be
upscaled if necessary.

Optional per-id gravity overrides live in scripts/gravity_overrides.json:
  { "fitzroy-sunset": "North" }
Valid gravities: NorthWest, North, NorthEast, West, Center, East,
SouthWest, South, SouthEast (ImageMagick gravity names).

After finalizing, regenerates CREDITS.md from research/candidates.json.
"""

import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_DIR = ROOT / "work" / "candidates"
GENERATED_DIR = ROOT / "work" / "generated"
BACKGROUNDS_DIR = ROOT / "backgrounds"
GRAVITY_OVERRIDES_PATH = ROOT / "scripts" / "gravity_overrides.json"
CANDIDATES_JSON = ROOT / "research" / "candidates.json"

TARGET_WIDTH = 3840
TARGET_HEIGHT = 2160
JPEG_QUALITY = 90

# Generated-image slugs (live in work/generated/) and their credit line.
GENERATED_SLUGS = {"sol-de-mayo", "jacaranda-skyline"}
GENERATED_CREDIT = "Generated for this theme with Google Nano Banana Pro"


# ── Helpers ──────────────────────────────────────────────────────────────────

def strip_html(value: str) -> str:
    """Remove HTML tags and decode entities (e.g. Wikimedia Artist fields)."""
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def image_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["magick", "identify", "-format", "%w %h", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    w, h = out.split()
    return int(w), int(h)


def croppable_size(w: int, h: int) -> tuple[int, int]:
    """Largest 16:9 crop of a w×h image."""
    if w / h >= 16 / 9:
        return int(round(h * 16 / 9)), h
    return w, int(round(w * 9 / 16))


def load_gravity_overrides() -> dict[str, str]:
    if GRAVITY_OVERRIDES_PATH.exists():
        return json.loads(GRAVITY_OVERRIDES_PATH.read_text())
    return {}


def find_candidate_file(cid: str) -> Path | None:
    for f in sorted(CANDIDATES_DIR.glob(f"{cid}.*")):
        if f.is_file():
            return f
    return None


def crop_resize_convert(src: Path, dst: Path, gravity: str = "Center"):
    """Smart-crop to 16:9, Lanczos resize, sRGB, JPEG q90, strip metadata."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "magick", str(src),
        "-gravity", gravity,
        "-crop", "16:9",
        "+repage",
        "-filter", "Lanczos",
        "-resize", f"{TARGET_WIDTH}x{TARGET_HEIGHT}!",
        "-colorspace", "sRGB",
        "-quality", str(JPEG_QUALITY),
        "-strip",
        "-interlace", "JPEG",
        str(dst),
    ], check=True)
    print(f"  -> {dst}")


def regenerate_credits(finalized_ids: list[tuple[str, str]]):
    """Rebuild CREDITS.md from candidates.json + generated-image credits."""
    candidates = []
    if CANDIDATES_JSON.exists():
        candidates = json.loads(CANDIDATES_JSON.read_text())
    by_id = {c["id"]: c for c in candidates}

    lines = [
        "# Credits",
        "",
        "Background images for the **Argentina Potencia** Omarchy theme.",
        "",
        "Each photograph remains under its own license, listed below. Images "
        "under CC BY-SA or other share-alike licenses remain share-alike: any "
        "reuse or adaptation must keep the same license and give the same "
        "attribution. The two AI-generated backgrounds were produced "
        "specifically for this theme and carry the repository's MIT license.",
        "",
        "All photographs were modified for this theme: cropped to 16:9, resized "
        "to 3840×2160 and re-encoded as JPEG. No other edits were made.",
        "",
        "---",
        "",
    ]

    for cid, nn in finalized_ids:
        fname = f"{nn}-{cid}.jpg"

        if cid in GENERATED_SLUGS:
            lines += [f"## {fname}", "", GENERATED_CREDIT, ""]
            continue

        entry = by_id.get(cid)
        if entry is None:
            lines += [f"## {fname}", "",
                      "Source information unavailable.", ""]
            continue

        title = strip_html(entry.get("title", cid)) or cid
        author = strip_html(entry.get("author", "")) or "Unknown"
        lic = strip_html(entry.get("license", "Unknown"))
        lic_url = entry.get("license_url", "").strip()
        page_url = entry.get("page_url", "").strip()
        source = page_url or entry.get("original_url", "").strip()

        lic_line = f"{lic} — {lic_url}" if lic_url else lic
        lines.append(f"## {fname} — {title}")
        lines.append("")
        lines.append(f"- **Author:** {author}")
        lines.append(f"- **License:** {lic_line}")
        if source:
            lines.append(f"- **Source:** {source}")
        lines.append("")

    (ROOT / "CREDITS.md").write_text("\n".join(lines))
    print(f"CREDITS.md written ({len(finalized_ids)} entries)")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: finalize.py <id> [<id>...]", file=sys.stderr)
        sys.exit(1)

    chosen_ids = sys.argv[1:]
    overrides = load_gravity_overrides()

    # backgrounds/ must hold exactly the chosen set — drop stale NN-*.jpg.
    for stale in BACKGROUNDS_DIR.glob("[0-9][0-9]-*.jpg"):
        stale.unlink()

    finalized: list[tuple[str, str]] = []
    skipped: list[str] = []

    for i, cid in enumerate(chosen_ids, start=1):
        nn = f"{i:02d}"
        gravity = overrides.get(cid, "Center")
        is_generated = cid in GENERATED_SLUGS

        if is_generated:
            src = GENERATED_DIR / f"{cid}.png"
            if not src.exists():
                src = GENERATED_DIR / f"{cid}.jpg"
            if not src.exists():
                print(f"[{nn}] {cid}: generated file missing — skipped")
                skipped.append(cid)
                continue
        else:
            src = find_candidate_file(cid)
            if src is None:
                print(f"[{nn}] {cid}: no candidate file — skipped")
                skipped.append(cid)
                continue

        w, h = image_size(src)
        cw, ch = croppable_size(w, h)

        # Never upscale a real photograph.
        if not is_generated and (cw < TARGET_WIDTH or ch < TARGET_HEIGHT):
            print(f"[{nn}] {cid}: 16:9 crop is {cw}x{ch} (< 3840x2160); "
                  f"refusing to upscale — skipped")
            skipped.append(cid)
            continue

        kind = "generated" if is_generated else "photo"
        print(f"[{nn}] {cid} [{kind}] {src.name} {w}x{h} "
              f"-> crop {cw}x{ch}, gravity={gravity}")
        crop_resize_convert(src, BACKGROUNDS_DIR / f"{nn}-{cid}.jpg", gravity)
        finalized.append((cid, nn))

    print(f"\nFinalized {len(finalized)}/{len(chosen_ids)} images.")
    if skipped:
        print(f"Skipped: {', '.join(skipped)}")
    regenerate_credits(finalized)


if __name__ == "__main__":
    main()
