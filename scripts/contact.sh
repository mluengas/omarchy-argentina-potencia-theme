#!/usr/bin/env bash
# contact.sh — Build a labeled contact-sheet grid of passing candidate images
# plus any images from work/generated/.
#
# Reads the pass/fail report from work/candidates/report.json, collects all
# passing images, appends any files in work/generated/, and uses ImageMagick's
# `magick montage` to create a labeled grid: id under each tile, tiles ~640px
# wide, total width <= 2600px.
#
# Output: work/contact/sheet.jpg

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
REPORT="$ROOT/work/candidates/report.json"
CONTACT_DIR="$ROOT/work/contact"
CANDIDATES_DIR="$ROOT/work/candidates"
GENERATED_DIR="$ROOT/work/generated"
OUTPUT="$CONTACT_DIR/sheet.jpg"

TILE_WIDTH=640
TILE_GAP=6
MAX_TOTAL_WIDTH=2600
LABEL_FONT="${LABEL_FONT:-Adwaita-Sans}"

mkdir -p "$CONTACT_DIR"

# ── Collect passing images from report ─────────────────────────────────────
declare -a IMAGES=()

if [[ -f "$REPORT" ]]; then
    pass_ids=$(python3 -c "
import json
report = json.load(open('$REPORT'))
for r in report:
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

# ── Append generated images ────────────────────────────────────────────────
if [[ -d "$GENERATED_DIR" ]]; then
    shopt -s nullglob
    for f in "$GENERATED_DIR"/*.png "$GENERATED_DIR"/*.jpg \
             "$GENERATED_DIR"/*.jpeg "$GENERATED_DIR"/*.webp; do
        [[ -f "$f" ]] && IMAGES+=("$f")
    done
    shopt -u nullglob
fi

if [[ ${#IMAGES[@]} -eq 0 ]]; then
    echo "No images found for contact sheet — exiting."
    exit 0
fi

echo "Building contact sheet with ${#IMAGES[@]} images..."

# ── Determine grid layout ──────────────────────────────────────────────────
# Total width <= 2600px. With N columns of TILE_WIDTH and (N+1) gaps, require
# N*TILE_WIDTH + (N+1)*TILE_GAP <= MAX_TOTAL_WIDTH.
N=${#IMAGES[@]}
COLS=1
for candidate_cols in 4 3 2 1; do
    if [[ $candidate_cols -le $N ]]; then
        width=$(( candidate_cols * TILE_WIDTH + (candidate_cols + 1) * TILE_GAP ))
        if [[ $width -le $MAX_TOTAL_WIDTH ]]; then
            COLS=$candidate_cols
            break
        fi
    fi
done
echo "  Layout: ${COLS} columns, tile width ${TILE_WIDTH}px"

# ── Build labeled montage ──────────────────────────────────────────────────
# montage applies -label to the next image it encounters, so build a list of
# `-label <id> <file>` pairs.  The id is the filename stem (candidate id or
# generated slug).
LABEL_ARGS=()
for img in "${IMAGES[@]}"; do
    stem="$(basename "$img")"
    label="${stem%.*}"
    LABEL_ARGS+=( "-label" "$label" "$img" )
done

magick montage \
    -font "$LABEL_FONT" -pointsize 20 -fill '#e8f0f8' \
    -background '#0e1a2b' \
    -tile "${COLS}x" \
    -geometry "${TILE_WIDTH}x+${TILE_GAP}+${TILE_GAP}" \
    -quality 90 \
    "${LABEL_ARGS[@]}" \
    "$OUTPUT"

echo "Contact sheet written to $OUTPUT"
magick identify "$OUTPUT"