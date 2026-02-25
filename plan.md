# Plan: Extract Crew Card Backs

## Problem

Crew card PDFs are 2-page documents (front + back), but the pipeline only processes the front page. The back PNGs are extracted by `pdf_splitter.py` but never sent to the vision model.

**What's on each side:**
- **Front:** Crew card name, associated master/title, keyword abilities, keyword actions (with stat lines and triggers)
- **Back:** Marker definitions (size, height, terrain traits, full rules text) and Token definitions (full rules text)

**Data currently missing from 130 crew cards:**
- Marker details — only 7/130 have any markers, and those are likely from front-page mentions, not from the structured back-page definitions
- Token rules text — only 12/130 have any tokens, all lacking the full rules descriptions visible on the back

## Changes Required

### Step 1: Create `prompts/crew_card_back_prompt.txt`

New prompt template for crew card back extraction. The back page has a simpler layout than the front:

- **Markers section** — marker name, size (e.g. "40mm"), height (e.g. "Ht 3"), terrain traits (e.g. "severe, concealing"), and detailed rules text (aura effects, interactions)
- **Tokens section** — token name and full rules text for each token

Output schema:
```json
{
  "card_type": "crew_card_back",
  "name": "string — crew card name (shown at top)",
  "markers": [
    {
      "name": "string",
      "size": "string or null",
      "height": "string or null",
      "terrain_traits": ["string"],
      "text": "string — full rules text"
    }
  ],
  "tokens": [
    {
      "name": "string",
      "text": "string — full token rules text"
    }
  ]
}
```

### Step 2: Modify `scripts/card_extractor.py`

Add a new function:

```python
def extract_crew_card_back(client, image_path):
    """Extract markers and tokens from crew card back image."""
    result = extract_card_side(client, image_path, "crew_card_back_prompt")
    return result
```

Update `extract_crew_card()` to accept an optional `back_path` parameter:

```python
def extract_crew_card(client, front_path, back_path=None):
    """Extract a crew card from front (and optionally back) images."""
    front = extract_card_side(client, front_path, "crew_card_prompt")
    if "error" in front:
        return front
    if back_path:
        back = extract_card_side(client, back_path, "crew_card_back_prompt")
        if "error" not in back:
            return {"front": front, "back": back, "status": "extracted"}
        # If back fails, return front-only with warning
        front["_back_extraction_error"] = back.get("error")
    return front
```

Also update the `__main__` block to accept 2 images for crew cards.

### Step 3: Modify `scripts/merger.py`

Add a `merge_crew_card()` function:

```python
def merge_crew_card(front, back, source_pdf=None):
    """Merge crew card front (abilities/actions) with back (markers/tokens)."""
    warnings = []

    # Cross-check name
    if front.get("name", "").lower() != back.get("name", "").lower():
        warnings.append(f"Name mismatch: front='{front.get('name')}' back='{back.get('name')}'")

    # Start from front data, overlay back data
    merged = dict(front)
    merged["card_type"] = "crew_card"

    # Merge markers: back is authoritative (has full details), but keep any front-only markers
    back_markers = back.get("markers", [])
    front_markers = merged.get("markers", [])
    back_marker_names = {m["name"].lower() for m in back_markers}

    # Keep front markers not in back, then add all back markers
    unique_front = [m for m in front_markers if m["name"].lower() not in back_marker_names]
    merged["markers"] = back_markers + unique_front

    # Merge tokens: back is authoritative (has rules text)
    back_tokens = back.get("tokens", [])
    front_tokens = merged.get("tokens", [])
    back_token_names = {t["name"].lower() for t in back_tokens}

    unique_front_tokens = [t for t in front_tokens if t["name"].lower() not in back_token_names]
    merged["tokens"] = back_tokens + unique_front_tokens

    merged["source_pdf"] = source_pdf
    merged["merge_warnings"] = warnings

    # Remove extraction meta from front
    merged.pop("_extraction_meta", None)

    return merged
```

Update `merge_from_file()` to handle the new crew card front+back format.

### Step 4: Modify `scripts/pipeline.py`

Update the crew card branch (lines 131-136) to handle 2-page PDFs:

```python
elif card_type == "crew_card":
    if len(images) >= 2:
        # Two-page crew card: front + back
        front_img = next((i for i in images if i["side"] == "front"), images[0])
        back_img = next((i for i in images if i["side"] == "back"), images[1])

        front = extract_crew_card_front(client, front_img["image_path"])
        if "error" in front:
            return {"status": "error", "step": "vision", "error": front["error"]}

        back = extract_crew_card_back(client, back_img["image_path"])
        if "error" in back:
            # Non-fatal: proceed with front only, log warning
            print(f"  WARNING: Back extraction failed, using front only")
            merged = front
            merged["source_pdf"] = str(pdf_path)
        else:
            merged = merge_crew_card(front, back, str(pdf_path))
    else:
        # Single-page crew card (fallback)
        img = images[0]
        merged = extract_crew_card_front(client, img["image_path"])
        if "error" in merged:
            return {"status": "error", "step": "vision", "error": merged["error"]}
        merged["source_pdf"] = str(pdf_path)
```

### Step 5: Create `scripts/backfill_crew_backs.py` — One-off backfill script

Since all 130 crew card back PNGs already exist in `pipeline_work/`, create a standalone script that:

1. Scans `pipeline_work/` for all `*Crew*_back.png` files
2. Loads the corresponding `*_merged.json` (existing front-only data)
3. Sends each back PNG to the vision API with the new back prompt
4. Merges back data (markers + tokens) into the existing merged JSON
5. Writes updated merged JSONs
6. Optionally reloads into the database

This avoids re-processing fronts (already correct) and re-splitting PDFs (already done).

**CLI interface:**
```bash
# Dry run — show what would be processed
python scripts/backfill_crew_backs.py --dry-run

# Process all backs
python scripts/backfill_crew_backs.py

# Process one faction only
python scripts/backfill_crew_backs.py --faction Bayou

# Reload into DB after backfill
python scripts/backfill_crew_backs.py --reload-db
```

**Estimated API cost:** ~130 calls × ~2K input tokens = ~260K tokens ≈ $0.80 with Sonnet

### Step 6: Update `scripts/db_loader.py` (if needed)

Verify that `load_crew_card()` already handles the `markers` and `tokens` fields properly when they contain full data. The schema tables (`crew_markers`, `crew_marker_terrain_traits`, `crew_tokens`) already exist — confirm the loader populates them correctly with the richer back-page data.

### Step 7: Re-export denormalized JSON

After backfill + DB reload:
```bash
python scripts/denormalize.py
```

This updates `Model Data Json/m4e_crew_cards.json` with the enriched marker/token data.

### Step 8: Run audit

```bash
python final_audit.py --verbose
```

Verify no new errors introduced.

## Execution Order

1. Create `crew_card_back_prompt.txt` (no dependencies)
2. Modify `card_extractor.py` — add `extract_crew_card_back()`
3. Modify `merger.py` — add `merge_crew_card()`
4. Modify `pipeline.py` — update crew card branch for 2-page handling
5. Create `backfill_crew_backs.py` — one-off script for existing data
6. Verify `db_loader.py` handles enriched data
7. Run backfill → rebuild DB → re-export → audit

Steps 1-4 fix the pipeline going forward. Step 5 fixes existing data. Steps 6-8 are validation.

## Files Changed

| File | Change |
|------|--------|
| `prompts/crew_card_back_prompt.txt` | **NEW** — Vision prompt for crew card backs |
| `scripts/card_extractor.py` | Add `extract_crew_card_back()`, update `extract_crew_card()` signature |
| `scripts/merger.py` | Add `merge_crew_card()`, update `merge_from_file()` |
| `scripts/pipeline.py` | Update crew card branch to handle 2-page PDFs |
| `scripts/backfill_crew_backs.py` | **NEW** — One-off backfill for existing 130 crew card backs |

## Risks & Mitigations

- **Some backs may be blank or art-only**: The prompt should handle this gracefully — return empty markers/tokens arrays
- **Token definitions on backs include standard game tokens** (Stunned, Staggered, etc.) alongside crew-specific ones: The merger should store all of them; downstream tools can distinguish standard vs crew-specific
- **Back extraction failure**: Non-fatal — fall back to front-only data (what we have today)
- **No ANTHROPIC_API_KEY in this environment**: The backfill script requires API access. The code changes can be written and tested structurally, but actual backfill needs to run locally where the key is set
