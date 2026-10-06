#!/usr/bin/env python3
"""finalize.py — Smart-crop, resize, and finalize chosen candidate images.

Usage: finalize.py <id> [<id>...]

For each given id (in order), finds the downloaded candidate in
work/candidates/<id>.*, smart-crops it to 16:9 aspect ratio, resizes to
3840×2160 with Lanczos, converts to sRGB JPEG q90 with metadata stripped,
and writes backgrounds/NN-<id>.jpg (NN = 01, 02, ...).

Optional gravity overrides can be specified via scripts/gravity_overrides.json:
  { "id": "northwest" }
  Valid gravities: NorthWest, North, NorthEast, West, Center, East,
  SouthWest, South, SouthEast (ImageMagick gravity names).

After finalizing, regenerates CREDITS.md from research/candidates.json.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_DIR = ROOT / "work" / "candidates"
BACKGROUNDS_DIR = ROOT / "backgrounds"
GRAVITY_OVERRIDES_PATH = ROOT / "scripts" / "gravity_overrides.json"
CANDIDATES_JSON = ROOT / "research" / "candidates.json"

# Final output specs
TARGET_WIDTH = 3840
TARGET_HEIGHT = 2160
JPEG_QUALITY = 90

# These are the generated image slugs (images in work/generated/)
GENERATED_SLUGS = {"sol-de-mayo", "jacaranda-skyline"}


def load_gravity_overrides() -> dict[str, str]:
    if GRAVITY_OVERRIDES_PATH.exists():
        return json.loads(GRAVITY_OVERRIDES_PATH.read_text())
    return {}


def find_candidate_file(cid: str) -> Path | None:
    """Find the downloaded file for a given candidate id."""
    for f in sorted(CANDIDATES_DIR.glob(f"{cid}.*")):
        if f.is_file():
            return f
    return None


def crop_resize_convert(src: Path, dst: Path, gravity: str = "Center"):
    """Smart-crop to 16:9, resize with Lanczos, sRGB, JPEG q90, strip metadata."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "magick",
        str(src),
        "-gravity", gravity,
        "-crop", "16:9",             # largest 16:9 region at chosen gravity
        "+repage",
        "-filter", "Lanczos",
        "-resize", f"{TARGET_WIDTH}x{TARGET_HEIGHT}!",  # force exact output size
        "-colorspace", "sRGB",
        "-quality", str(JPEG_QUALITY),
        "-strip",
        "-interlace", "JPEG",
        str(dst),
    ]
    subprocess.run(cmd, check=True)
    print(f"  -> {dst}")


def regenerate_credits(finalized_ids: list[tuple[str, str]]):
    """Rebuild CREDITS.md from candidates.json and generated image info.

    finalized_ids: list of (id, nn) tuples in final order.
    """
    candidates = []
    if CANDIDATES_JSON.exists():
        candidates = json.loads(CANDIDATES_JSON.read_text())

    candidates_by_id = {c["id"]: c for c in candidates}

    lines = [
        "# Credits",
        "",
        "Background images used in Argentina Potencia Omarchy theme.",
        "",
    ]

    for cid, nn in finalized_ids:
        if cid in GENERATED_SLUGS:
            lines.append(f"## {nn}-{cid}.jpg")
            lines.append("")
            lines.append("Generated for this theme using AI image generation.")
            lines.append("")
            continue

        entry = candidates_by_id.get(cid)
        if entry is None:
            lines.append(f"## {nn}-{cid}.jpg")
            lines.append("")
            lines.append("Source information unavailable.")
            lines.append("")
            continue

        title = entry.get("title", cid)
        author = entry.get("author", "Unknown")
        license_str = entry.get("license", "Unknown")
        license_url = entry.get("license_url", "")
        page_url = entry.get("page_url", "")
        # If original_url looks like a direct file, link to page_url instead
        source_link = page_url or entry.get("original_url", "")

        lines.append(f"## {nn}-{cid}.jpg — {title}")
        lines.append("")
        lines.append(f"- **Author:** {author}")
        lines.append(f"- **License:** {license_str}" + (f" ({license_url})" if license_url else ""))
        if source_link:
            lines.append(f"- **Source:** {source_link}")
        lines.append("")

    credits_path = ROOT / "CREDITS.md"
    credits_path.write_text("\n".join(lines))
    print(f"CREDITS.md written to {credits_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: finalize.py <id> [<id>...]", file=sys.stderr)
        sys.exit(1)

    chosen_ids = sys.argv[1:]
    gravity_overrides = load_gravity_overrides()

    finalized = []

    for i, cid in enumerate(chosen_ids, start=1):
        nn = f"{i:02d}"
        gravity = gravity_overrides.get(cid, "Center")

        # Check if it's a generated image
        if cid in GENERATED_SLUGS:
            gen_path = ROOT / "work" / "generated" / f"{cid}.png"
            if not gen_path.exists():
                gen_path = ROOT / "work" / "generated" / f"{cid}.jpg"
            if gen_path.exists():
                print(f"[{nn}] generated/{cid} (gravity={gravity})")
                dst = BACKGROUNDS_DIR / f"{nn}-{cid}.jpg"
                crop_resize_convert(gen_path, dst, gravity)
                finalized.append((cid, nn))
            else:
                print(f"[{nn}] {cid}: generated file not found in work/generated/, skipping")
            continue

        # Find downloaded candidate
        src = find_candidate_file(cid)
        if src is None:
            print(f"[{nn}] {cid}: not found in work/candidates/, skipping")
            continue

        print(f"[{nn}] {cid} ({src.name}) gravity={gravity}")
        dst = BACKGROUNDS_DIR / f"{nn}-{cid}.jpg"
        crop_resize_convert(src, dst, gravity)
        finalized.append((cid, nn))

    print(f"\nFinalized {len(finalized)} images.")
    regenerate_credits(finalized)


if __name__ == "__main__":
    main()