#!/usr/bin/env python3
"""fetch.py — Download candidate images and verify they meet SPEC requirements.

Reads a candidates JSON file (default: research/candidates.json).
For each candidate, downloads the original_url into work/candidates/<id>.<ext>,
skipping existing files.  Verifies the downloaded image meets the minimum
resolution requirement (>=3840×2160, croppable to 16:9 without upscaling)
and that the license is in the SPEC allowlist.  Writes a pass/fail report
to work/candidates/report.json.

For testing, pass a path to a different JSON file as the first argument.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from io import BytesIO

# ── Configuration ────────────────────────────────────────────────────────────

# SPEC-allowed license substrings (case-insensitive matching)
ALLOWED_LICENSES = [
    "pd",
    "public domain",
    "cc0",
    "cc by",       # covers "CC BY 4.0", "CC BY 2.0", etc.
    "cc-by",       # hyphenated variant
    "cc by-sa",    # covers "CC BY-SA 4.0", etc.
    "cc-by-sa",
    "unsplash",
]

# Minimum dimensions: 3840×2160, croppable to 16:9 without upscaling.
# This is equivalent to width >= 3840 and height >= 2160.
MIN_WIDTH = 3840
MIN_HEIGHT = 2160

# User-Agent required by Wikimedia (and polite for all servers)
USER_AGENT = (
    "ArgentinaPotenciaThemeBuilder/1.0 "
    "(https://github.com/omarchy/argentina-potencia-theme; "
    "research bot gathering CC-licensed imagery for an open-source desktop theme)"
)

# Repository root (parent of scripts/)
ROOT = Path(__file__).resolve().parent.parent

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_image_dimensions(filepath: Path) -> tuple[int, int] | None:
    """Return (width, height) by reading just the image header, or None on failure.
    Supports JPEG, PNG, WebP, GIF, BMP.  Does not load the full image into RAM."""
    try:
        with open(filepath, "rb") as f:
            header = f.read(64)  # enough for PNG/GIF/BMP/WebP signatures
    except OSError:
        return None

    # JPEG: walk segment markers by seeking (SOF can be past large EXIF blocks)
    if header[:2] == b"\xff\xd8":
        try:
            with open(filepath, "rb") as f:
                f.seek(2)
                while True:
                    b = f.read(1)
                    if not b:
                        return None
                    if b != b"\xff":
                        continue
                    # skip fill bytes
                    marker = f.read(1)
                    while marker == b"\xff":
                        marker = f.read(1)
                    if not marker:
                        return None
                    m = marker[0]
                    # Standalone markers with no length payload
                    if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                        continue
                    seg_len_bytes = f.read(2)
                    if len(seg_len_bytes) < 2:
                        return None
                    seg_len = int.from_bytes(seg_len_bytes, "big")
                    # SOF0..SOF15 (excluding DHT/DAC/RST) carry frame size
                    if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                             0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        # skip precision(1), then height(2), width(2)
                        f.read(1)
                        dims = f.read(4)
                        if len(dims) < 4:
                            return None
                        h = int.from_bytes(dims[0:2], "big")
                        w = int.from_bytes(dims[2:4], "big")
                        return (w, h)
                    # SOS starts compressed data; stop scanning
                    if m == 0xDA:
                        return None
                    # Advance past this segment's payload
                    f.seek(seg_len - 2, 1)
        except OSError:
            return None

    # PNG: IHDR at offset 16 (8-byte sig + 4 len + 4 'IHDR')
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(header[16:20], "big")
        h = int.from_bytes(header[20:24], "big")
        return (w, h)

    # WebP: RIFF....WEBP
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        # VP8X chunk has width/height at offset 24 (with 24-bit encoding)
        if header[12:16] == b"VP8X":
            # Extended format: 3 bytes each for width+1, height+1 (little-endian 24-bit)
            raw = header[24:30]
            w = (raw[0] | (raw[1] << 8) | (raw[2] << 16)) + 1
            h = (raw[3] | (raw[4] << 8) | (raw[5] << 16)) + 1
            return (w, h)
        # Lossy VP8 at offset 30
        if header[20:24] == b"VP8 ":
            w = int.from_bytes(header[26:28], "little") & 0x3FFF
            h = int.from_bytes(header[28:30], "little") & 0x3FFF
            return (w, h)
        # Lossless VP8L at offset 25
        if header[20:24] == b"VP8L":
            raw = header[25:30]
            w = (raw[0] | (raw[1] << 8) | ((raw[2] & 0x3F) << 16)) + 1
            h = ((raw[2] >> 6) | (raw[3] << 2) | ((raw[4] & 0x0F) << 10)) + 1
            return (w, h)
        return None

    # GIF
    if header[:4] in (b"GIF8",):
        w = int.from_bytes(header[6:8], "little")
        h = int.from_bytes(header[8:10], "little")
        return (w, h)

    # BMP
    if header[:2] == b"BM":
        w = int.from_bytes(header[18:22], "little")
        h = abs(int.from_bytes(header[22:26], "little", signed=True))
        return (w, h)

    # Try Pillow-style fallback — only if it looks like an image
    return None


def check_resolution(width: int, height: int) -> bool:
    """Return True if dimensions are >=3840x2160 croppable to 16:9."""
    if width < MIN_WIDTH:
        return False
    if height < MIN_HEIGHT:
        return False
    # Both conditions above are sufficient: see script header comment for proof.
    return True


def check_license(license_str: str) -> bool:
    """Return True if license_str matches an allowed license in the SPEC."""
    lower = license_str.lower().strip()
    for allowed in ALLOWED_LICENSES:
        if allowed in lower:
            return True
    return False


def extract_extension(url: str) -> str:
    """Best-effort extension from URL, defaulting to .jpg."""
    # Strip query and fragment
    path = url.split("?")[0].split("#")[0]
    _, dot_ext = os.path.splitext(path)
    dot_ext = dot_ext.lower()
    valid = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
    if dot_ext in valid:
        return dot_ext
    # Some Wikimedia URLs are like .../File:Foo.jpg/revision/latest
    # Try finding an extension further in
    parts = path.split("/")
    for part in parts:
        _, e = os.path.splitext(part.lower())
        if e in valid:
            return e
    return ".jpg"


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Accept an optional path argument for testing
    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "research" / "candidates.json"

    if not json_path.exists():
        print(f"Error: {json_path} not found", file=sys.stderr)
        sys.exit(1)

    candidates = json.loads(json_path.read_text())
    print(f"Loaded {len(candidates)} candidates from {json_path}")

    candidates_dir = ROOT / "work" / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    report = []

    for entry in candidates:
        cid = entry["id"]
        url = entry.get("original_url") or entry.get("url", "")
        if not url:
            report.append({"id": cid, "pass": False, "reason": "missing original_url"})
            continue

        ext = extract_extension(url)
        out_path = candidates_dir / f"{cid}{ext}"

        if out_path.exists():
            print(f"[{cid}] already downloaded, verifying...")
        else:
            print(f"[{cid}] downloading {url} ...")
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = resp.read()
                out_path.write_bytes(data)
                print(f"[{cid}]  -> {out_path} ({len(data)} bytes)")
            except urllib.error.HTTPError as e:
                report.append({"id": cid, "pass": False, "reason": f"HTTP {e.code}: {e.reason}"})
                continue
            except Exception as e:
                report.append({"id": cid, "pass": False, "reason": f"download error: {e}"})
                continue
            # Be nice to servers
            time.sleep(0.5)

        # ── Check dimensions ──────────────────────────────────────────────
        dims = get_image_dimensions(out_path)
        if dims is None:
            report.append({"id": cid, "pass": False, "reason": "could not read image dimensions"})
            continue
        w, h = dims
        print(f"[{cid}] dimensions: {w}x{h}")

        if not check_resolution(w, h):
            report.append({
                "id": cid,
                "pass": False,
                "reason": f"resolution {w}x{h} too small (need >=3840x2160 croppable to 16:9)"
            })
            continue

        # ── Check license ─────────────────────────────────────────────────
        license_str = entry.get("license", "")
        if not check_license(license_str):
            report.append({
                "id": cid,
                "pass": False,
                "reason": f"license '{license_str}' not in allowlist ({', '.join(ALLOWED_LICENSES)})"
            })
            continue

        # All checks passed
        report.append({"id": cid, "pass": True, "reason": f"{w}x{h}, license OK"})

    # Write report
    report_path = candidates_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2))
    passed = sum(1 for r in report if r["pass"])
    print(f"\nDone. {passed}/{len(report)} passed. Report written to {report_path}")


if __name__ == "__main__":
    main()