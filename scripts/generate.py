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

A native 4K image is requested via image_config (aspect_ratio 16:9, image_size
4K), supported by the Gemini image *preview* models; upscaling is only a
fallback when the returned image is still narrower than 3840px.  Images are
saved to work/generated/<slug>.png.  Per-call cost is read from the response
usage and logged.  Hard cap: stop if cumulative cost exceeds $2.00 USD across
runs (prior spend is carried in via PRIOR_SPEND_USD, default 0.2789).

Requires `pi auth print-api-key --provider openrouter` for the API key.

OpenRouter image-generation response shape (verified):
  choices[0].message.images = [
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
  ]
  usage = {"prompt_tokens": ..., "completion_tokens": ..., "cost": 0.0387, ...}
"""

import base64
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = ROOT / "work" / "generated"

MAX_COST = 2.00  # USD hard cap across ALL runs
# Cost already spent on the v1 (first-pass) generations.  Subtracted from the
# cap so the total across runs never exceeds MAX_COST.
PRIOR_SPEND = float(os.environ.get("PRIOR_SPEND_USD", "0.2789"))
TARGET_W, TARGET_H = 3840, 2160

# ── Image generation prompts ─────────────────────────────────────────────────
# Exact hex colors from colors.toml.  No text / watermark / flags-with-text.

IMAGE_SPECS = [
    {
        "slug": "sol-de-mayo",
        "prompt": (
            "Create a minimalist flat-vector desktop wallpaper, 16:9, 3840x2160. "
            "\n\n"
            "SKY: a smooth VERTICAL gradient with NO hard horizontal bands and no "
            "flat celeste stripe. The top 45% is deep night navy #0e1a2b, then it "
            "fades downward through #1a2b44 into a soft celeste blue #74acdf glow "
            "only near the horizon. Leave generous empty dark sky across the top "
            "half so desktop icons and a top bar remain readable. "
            "\n\n"
            "SUBJECT: the Sol de Mayo half-risen behind the central Andes peak. "
            "It is a golden sun with a face and alternating straight and wavy "
            "rays. Use gold #f6b40e for the sun and a brown #85340a outline, with "
            "a subtle warm glow bleeding into the sky around it. "
            "\n\n"
            "MOUNTAINS: 3 to 4 layered mountain ridge silhouettes with realistic "
            "atmospheric perspective (farther ridges are lighter and bluer, "
            "nearer ridges are darker navy #0e1a2b). Snow caps in white #ffffff "
            "on the highest peaks. "
            "\n\n"
            "STYLE: minimalist flat vector, clean geometric shapes, crisp edges, "
            "calm. No text, no letters, no numbers, no watermark, no signature, "
            "no flags, no flag-like emblems with text."
        ),
        "description": "Minimalist Sol de Mayo half-risen over layered Andes ridges",
    },
    {
        "slug": "jacaranda-skyline",
        "prompt": (
            "Create a minimalist flat-vector desktop wallpaper of Buenos Aires "
            "at blue hour, 16:9, 3840x2160. It must be DARK and nocturnal."
            "\n\n"
            "SKY: a dark blue-hour gradient. The top is deep navy #0e1a2b, "
            "fading down to #24426a near the horizon, with a thin warm gold "
            "#f6b40e band right at the horizon line. The top 40% is mostly empty "
            "dark sky. No moon. At most a few very faint stars. "
            "\n\n"
            "SKYLINE: the Obelisco centered and slender, the rest of the skyline "
            "as low, dark silhouettes. Very few lit windows: only sparse warm "
            "gold #f6b40e dots, no cartoon window grids, no big rectangles. "
            "\n\n"
            "FOREGROUND: jacaranda canopies in purple #b490dc and light lilac "
            "#cdb2ec framing the left and right edges, with a few petals drifting "
            "in the air. The ground is the dark, wide avenue (Avenida 9 de Julio) "
            "receding toward the Obelisco. Do NOT draw water and do NOT draw a "
            "reflective water blob or lake. "
            "\n\n"
            "STYLE: minimalist flat vector, calm night mood, generous empty dark "
            "sky at the top. No text, no letters, no numbers, no watermark, no "
            "signature, no flags, no flag-like emblems with text."
        ),
        "description": "Dark blue-hour Buenos Aires skyline, Obelisco and jacarandas",
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
# NOTE: only the *-preview* builds of the Gemini image models accept the 4K
# image_config, so they are preferred for native 4K output.  The non-preview
# variants are fallbacks and will be upscaled from ~1K.
MODEL_PREFERENCES = [
    "gemini-3-pro-image-preview",   # Nano Banana Pro, native 4K
    "gemini-3.1-flash-image-preview",  # native 4K
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
    base = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
        # Native-resolution request (supported by the Gemini image preview
        # models on OpenRouter).  Fall back to Lanczos upscaling only if the
        # returned image is still narrower than 3840px.
        "image_config": {
            "aspect_ratio": "16:9",
            "image_size": "4K",
        },
    }
    print(f"\n[{slug}] Sending prompt to {model_id} (native 4K requested)...")
    print(f"  Prompt: {prompt[:140]}...")
    try:
        return api_post("https://openrouter.ai/api/v1/chat/completions", api_key, base)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace") if e.fp else ""
        # If 4K image_config is rejected, retry once without it (will upscale).
        if e.code == 400 and ("image_size" in detail or "not supported" in detail):
            print(f"  Native 4K not supported by {model_id}; retrying without image_config")
            retry = dict(base)
            retry.pop("image_config", None)
            try:
                return api_post("https://openrouter.ai/api/v1/chat/completions", api_key, retry)
            except urllib.error.HTTPError as e2:
                d2 = e2.read().decode(errors="replace") if e2.fp else ""
                print(f"  Retry HTTP {e2.code}: {d2[:600]}", file=sys.stderr)
                return None
            except Exception as e2:
                print(f"  Retry failed: {e2}", file=sys.stderr)
                return None
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
    """Normalize the saved PNG to exactly 3840x2160.

    Logs the size the API actually returned.  Only upscales (Lanczos) when the
    returned image is narrower than 3840px; larger images are downscaled.
    """
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
    print(f"  Returned size: {w}x{h}")
    if (w, h) == (TARGET_W, TARGET_H):
        print("  Exactly 3840x2160 — no resize needed")
        return

    if w < TARGET_W or h < TARGET_H:
        print(f"  Below 4K (w={w}); upscaling with Lanczos")
    else:
        print("  Above 4K; downscaling/cropping to 3840x2160")

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
    print(f"  Normalized to {TARGET_W}x{TARGET_H}")


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

    cumulative = PRIOR_SPEND
    print(f"Prior spend carried into cap: ${PRIOR_SPEND:.4f} "
          f"(remaining budget ${MAX_COST - PRIOR_SPEND:.4f})\n")
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

    print(f"\nDone. Total across runs (incl. prior ${PRIOR_SPEND:.4f}): ${cumulative:.4f} "
          f"of ${MAX_COST:.2f} cap. This run: ${cumulative - PRIOR_SPEND:.4f}")


if __name__ == "__main__":
    main()