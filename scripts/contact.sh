#!/usr/bin/env bash
# contact.sh — build labeled review contact sheets from the passing candidates.
#
# Reads work/candidates/report.json, collects every passing candidate image,
# and renders TWO sheets so tiles stay readable:
#   work/contact/sheet-a.jpg
#   work/contact/sheet-b.jpg
# 3 columns, tiles 600px wide, with the id label under each tile.
#
# Set INCLUDE_GENERATED=1 to also append finalized images from work/generated/
# (draft *-v1.* files are always skipped, and the result is still split over
# the same two sheets).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
REPORT="$ROOT/work/candidates/report.json"
CONTACT_DIR="$ROOT/work/contact"
CANDIDATES_DIR="$ROOT/work/candidates"
GENERATED_DIR="$ROOT/work/generated"

TILE_WIDTH=600
TILE_BORDER=4
COLS=3
LABEL_FONT="${LABEL_FONT:-Adwaita-Sans}"
INCLUDE_GENERATED="${INCLUDE_GENERATED:-0}"

mkdir -p "$CONTACT_DIR"

# ── Collect passing candidate images ────────────────────────────────────────
declare -a IMAGES=()
if [[ -f "$REPORT" ]]; then
    pass_ids=$(python3 -c "
import json
for r in json.load(open('$REPORT')):
    if r.get('pass'):
        print(r['id'])
")
    for cid in $pass_ids; do
        for f in "$CANDIDATES_DIR/$cid".*; do
            if [[ -f "$f" ]]; then
                IMAGES+=("$f")
                break
            fi
        done
    done
fi

# ── Optionally append finalized generated images (skip *-v1 drafts) ─────────
if [[ "$INCLUDE_GENERATED" == "1" && -d "$GENERATED_DIR" ]]; then
    shopt -s nullglob
    for f in "$GENERATED_DIR"/*.png "$GENERATED_DIR"/*.jpg \
             "$GENERATED_DIR"/*.jpeg "$GENERATED_DIR"/*.webp; do
        [[ "$(basename "$f")" == *-v1.* ]] && continue
        [[ -f "$f" ]] && IMAGES+=("$f")
    done
    shopt -u nullglob
fi

if [[ ${#IMAGES[@]} -eq 0 ]]; then
    echo "No images found for contact sheets — exiting."
    exit 0
fi

N=${#IMAGES[@]}
echo "Building 2 contact sheets from ${N} images (${COLS} cols, ${TILE_WIDTH}px tiles)"

# ── Render one sheet ────────────────────────────────────────────────────────
render_sheet() {
    local out="$1"; shift
    local imgs=( "$@" )
    if [[ ${#imgs[@]} -eq 0 ]]; then
        echo "  (no images for $out, skipping)"
        return 0
    fi
    local args=()
    for img in "${imgs[@]}"; do
        local stem label
        stem="$(basename "$img")"
        label="${stem%.*}"
        args+=( "-label" "$label" "$img" )
    done
    magick montage \
        -font "$LABEL_FONT" -pointsize 20 -fill '#e8f0f8' \
        -background '#0e1a2b' \
        -tile "${COLS}x" \
        -geometry "${TILE_WIDTH}x+${TILE_BORDER}+${TILE_BORDER}" \
        -quality 90 \
        "${args[@]}" \
        "$out"
    echo "  wrote $out"
    magick identify -format '    %f %wx%h\n' "$out"
}

# ── Split as evenly as possible into exactly two sheets ─────────────────────
HALF=$(( (N + 1) / 2 ))
A=( "${IMAGES[@]:0:$HALF}" )
B=( "${IMAGES[@]:$HALF}" )

render_sheet "$CONTACT_DIR/sheet-a.jpg" "${A[@]}"
render_sheet "$CONTACT_DIR/sheet-b.jpg" "${B[@]}"

# Remove the old single sheet, now superseded.
rm -f "$CONTACT_DIR/sheet.jpg"
