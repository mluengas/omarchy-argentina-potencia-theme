#!/usr/bin/env python3
"""generate.py — Generate 2 stylized wallpapers via OpenRouter image generation.

Finds the best available image-output model on OpenRouter (preferring Google
Gemini image models / "Nano Banana Pro"), then generates two 3840×2160 wallpapers
matching the Argentina Potencia palette.

Prompts reference exact hex colors from colors.toml:
  - celeste (accent): #74acdf
  - white: #ffffff
  - Sol de Mayo gold (yellow): #f6b40e
  - night background: #0e1a2b

Images are saved to work/generated/<slug>.png.  Per-call cost is read from the
response usage and logged.  Hard cap: stop if cumulative cost exceeds $2.00 USD.

Requires `pi auth print-api-key --provider openrouter` for the API key.

OpenRouter image-generation response shape (verified):
  choices[0].message.images = [
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
  ]
  usage = {"prompt_tokens": ..., "completion_tokens": ..., "cost": 0.0387, ...}
"""

import base64
import json
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = ROOT / "work" / "generated"

MAX_COST = 2.00  # USD hard cap
TARGET_W, TARGET_H = 3840, 2160

# ── Image generation prompts ─────────────────────────────────────────────────
# Exact hex colors from colors.toml.  No text / watermark / flags-with-text.

IMAGE_SPECS = [
    {
        "slug": "sol-de-mayo",
        "prompt": (
            "Create a minimalist flat-vector desktop wallpaper, 16:9, 3840x2160. "
            "Concept: the Sol de Mayo (Sun of May) rising over a flat geometric "
            "silhouette of the Andes mountains. "
            "Palette (use these exact hex colors): night-sky background #0e1a2b; "
            "celeste blue #74acdf for the sky gradient near the horizon; "
            "Sol de Mayo gold #f6b40e for the sun and its rays; white #ffffff for "
            "snow caps and subtle light. Dark, calm, suitable behind a dark UI. "
            "Clean geometric shapes, crisp vector edges, high detail. "
            "No text, no letters, no numbers, no watermark, no signature, "
            "no flags, no flag-like emblems with text. Just the landscape."
        ),
        "description": "Minimalist Sol de Mayo rising over Andes silhouette",
    },
    {
        "slug": "jacaranda-skyline",
        "prompt": (
            "Create a flat-vector desktop wallpaper of Buenos Aires at dusk, "
            "16:9, 3840x2160. "
            "Concept: a city skyline silhouette with the Obelisco, lined with "
            "jacaranda trees in bloom. "
            "Palette (use these exact hex colors): deep navy #0e1a2b for the "
            "skyline and foreground; celeste blue #74acdf for the upper sky; "
            "Sol de Mayo gold #f6b40e for the warm glow at the horizon; "
            "jacaranda purple #b490dc for the tree blossoms; "
            "white #ffffff for stars and highlights. Flat vector style, clean "
            "geometric shapes, calm dusk mood, suitable behind a dark UI. "
            "No text, no letters, no numbers, no watermark, no signature, "
            "no flags, no flag-like emblems with text."
        ),
        "description": "Flat-vector Buenos Aires skyline with jacarandas at dusk",
    },
]


# ── API helpers ──────────────────────────────────────────────────────────────

def get_api_key() -> str:
    """Retrieve the OpenRouter API key via the pi CLI."""
    result = subprocess.run(
        ["pi", "auth", "print-api-key", "--provider", "openrouter"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def api_get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "ArgentinaPotenciaThemeBuilder/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def api_post(url: str, api_key: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "ArgentinaPotenciaThemeBuilder/1.0",
    })
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


# ── Model selection ──────────────────────────────────────────────────────────

# Preference keywords in id, highest priority first.  "Nano Banana Pro" is
# Google's gemini-3-pro-image; the flash variants are its lighter siblings.
MODEL_PREFERENCES = [
    "gemini-3-pro-image",
    "gemini-3.1-flash-image",
    "gemini-3-flash-image",
    "gemini-2.5-flash-image",
    "nano-banana",
    "banana",
]


def supports_image_output(m: dict) -> bool:
    """True if the model declares image in its output modalities."""
    arch = m.get("architecture", {})
    outputs = [str(x).lower() for x in arch.get("output_modalities", [])]
    if "image" in outputs:
        return True
    # Fallback on modality string like "text+image->text+image"
    modality = str(arch.get("modality", "")).lower()
    if "->" in modality:
        rhs = modality.split("->", 1)[1]
        if "image" in rhs:
            return True
    return False


def find_best_image_model(api_key: str) -> dict | None:
    """Query OpenRouter and pick the best image-output model.

    Preference: Google Gemini image models, with Gemini 3 Pro Image ("Nano
    Banana Pro") first, then newer flash image models, then legacy.
    """
    print("Querying OpenRouter models...")
    data = api_get("https://openrouter.ai/api/v1/models", api_key)
    models = data.get("data", [])
    print(f"  Got {len(models)} models")

    image_models = [m for m in models if supports_image_output(m)]
    if not image_models:
        print("Error: no image-output models found on OpenRouter.", file=sys.stderr)
        return None

    print("  Image-output models available:")
    for m in image_models:
        arch = m.get("architecture", {})
        print(f"    - {m['id']}  ({arch.get('modality')})")

    # Pick by preference keyword
    for pref in MODEL_PREFERENCES:
        for m in image_models:
            if pref in m.get("id", "").lower():
                print(f"\n  Selected (preference '{pref}'): {m['id']}")
                return m

    # Any gemini image model
    for m in image_models:
        if "gemini" in m.get("id", "").lower():
            print(f"\n  Selected (gemini fallback): {m['id']}")
            return m

    # Last resort: first available
    m = image_models[0]
    print(f"\n  Selected (first available): {m['id']}")
    return m


# ── Generation ───────────────────────────────────────────────────────────────

def generate_image(api_key: str, model_id: str, prompt: str, slug: str) -> dict | None:
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }
    print(f"\n[{slug}] Sending prompt to {model_id}...")
    print(f"  Prompt: {prompt[:140]}...")
    try:
        return api_post("https://openrouter.ai/api/v1/chat/completions", api_key, body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace") if e.fp else ""
        print(f"  HTTP {e.code}: {detail[:600]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Request failed: {e}", file=sys.stderr)
        return None


def _decode_and_save(data_url: str, slug: str) -> bool:
    """Decode a data: URL (or raw base64) and write work/generated/<slug>.png."""
    if data_url.startswith("data:"):
        try:
            _, b64 = data_url.split(",", 1)
        except ValueError:
            b64 = data_url
    else:
        b64 = data_url
    b64 = b64.strip().replace("\n", "").replace("\r", "")
    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        print(f"  Base64 decode failed: {e}")
        return False
    out = GENERATED_DIR / f"{slug}.png"
    out.write_bytes(raw)
    print(f"  Saved {out} ({len(raw)} bytes)")
    return True


def extract_image_from_response(resp: dict, slug: str) -> bool:
    """Save the generated image from an OpenRouter response. Returns success."""
    choices = resp.get("choices") or []
    if not choices:
        print("  No choices in response")
        return False
    msg = choices[0].get("message", {})

    # Preferred: message.images = [{"type":"image_url","image_url":{"url":...}}]
    for img in (msg.get("images") or []):
        if isinstance(img, dict):
            url = ""
            if isinstance(img.get("image_url"), dict):
                url = img["image_url"].get("url", "")
            elif isinstance(img.get("image_url"), str):
                url = img["image_url"]
            elif isinstance(img.get("url"), str):
                url = img["url"]
            if url:
                return _decode_and_save(url, slug)

    # Fallback: content as a list of parts
    content = msg.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "image_url":
                    u = part.get("image_url", {})
                    u = u.get("url", "") if isinstance(u, dict) else str(u)
                    if u:
                        return _decode_and_save(u, slug)
                if part.get("type") == "image" and part.get("image"):
                    return _decode_and_save(part["image"], slug)
    elif isinstance(content, str) and content.startswith("data:image"):
        return _decode_and_save(content, slug)

    print("  Could not locate image in response (no message.images)")
    print(f"  message keys: {list(msg.keys())}")
    return False


def get_cost_from_response(resp: dict) -> float:
    """Exact per-call cost from usage.cost (OpenRouter provides this)."""
    usage = resp.get("usage", {}) or {}
    cost = usage.get("cost")
    if cost is not None:
        return float(cost)
    # Fallback: sum cost_details if present
    details = usage.get("cost_details", {}) or {}
    total = details.get("upstream_inference_cost")
    if total is not None:
        return float(total)
    print("  Warning: no cost in usage; logging 0")
    return 0.0


# ── Post-processing ──────────────────────────────────────────────────────────

def ensure_dimensions(slug: str):
    """Crop/upscale the saved PNG to exactly 3840x2160 if it isn't already."""
    img = GENERATED_DIR / f"{slug}.png"
    if not img.exists():
        return
    res = subprocess.run(
        ["magick", "identify", "-format", "%w %h", str(img)],
        capture_output=True, text=True,
    )
    try:
        w, h = (int(x) for x in res.stdout.strip().split())
    except ValueError:
        print(f"  Could not read dimensions for {slug}")
        return
    print(f"  Generated dimensions: {w}x{h}")
    if (w, h) == (TARGET_W, TARGET_H):
        print("  Already at target size")
        return
    tmp = GENERATED_DIR / f"{slug}.tmp.png"
    subprocess.run([
        "magick", str(img),
        "-gravity", "Center",
        "-crop", "16:9",
        "+repage",
        "-filter", "Lanczos",
        "-resize", f"{TARGET_W}x{TARGET_H}!",
        "-colorspace", "sRGB",
        str(tmp),
    ], check=True)
    tmp.replace(img)
    print(f"  Adjusted to {TARGET_W}x{TARGET_H}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    print("Getting OpenRouter API key...")
    try:
        api_key = get_api_key()
    except subprocess.CalledProcessError as e:
        print(f"Error: could not get API key: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    if not api_key:
        print("Error: empty API key", file=sys.stderr)
        sys.exit(1)
    print("  API key retrieved")

    model = find_best_image_model(api_key)
    if model is None:
        sys.exit(1)
    model_id = model["id"]
    print(f"\nUsing model: {model.get('name', model_id)} ({model_id})\n")

    cumulative = 0.0
    for spec in IMAGE_SPECS:
        slug = spec["slug"]
        out = GENERATED_DIR / f"{slug}.png"

        if out.exists():
            print(f"[{slug}] already exists, skipping.")
            continue
        if cumulative >= MAX_COST:
            print(f"[{slug}] cumulative ${cumulative:.4f} >= cap ${MAX_COST:.2f}; stopping.")
            break

        resp = generate_image(api_key, model_id, spec["prompt"], slug)
        if resp is None:
            print(f"  FAILED to generate {slug}")
            continue

        cost = get_cost_from_response(resp)
        cumulative += cost
        print(f"  Cost: ${cost:.6f}  |  cumulative: ${cumulative:.4f}")

        if not extract_image_from_response(resp, slug):
            dump = GENERATED_DIR / f"{slug}_response.json"
            dump.write_text(json.dumps(resp, indent=2)[:200000])
            print(f"  Full response dumped to {dump}")
            continue

        ensure_dimensions(slug)

    print(f"\nDone. Total generation cost: ${cumulative:.4f}")


if __name__ == "__main__":
    main()