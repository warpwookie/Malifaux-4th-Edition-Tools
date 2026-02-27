#!/usr/bin/env python3
"""
pdf_text_extractor.py — Extract M4E stat card data from PDF text layers.

Uses PyMuPDF dict-mode to read structured text with font/position metadata.
Zero Vision API calls — all extraction from PDF text layer.

Public API mirrors card_extractor.py so merger/validator/db_loader are unchanged.

Usage:
    python pdf_text_extractor.py source.pdf [--debug]
    python pdf_text_extractor.py source.pdf --card-type crew
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF required. Install: pip install PyMuPDF")
    sys.exit(1)


# ============================================================================
# CONSTANTS — M4ESymbolsRegular character map
# ============================================================================

SYMBOL_MAP = {
    43:  "(+)",              # + → positive fate modifier
    45:  "(-)",              # - → negative fate modifier
    83:  "(soulstone)",      # S → soulstone (stat block context)
    99:  "(c)",              # c → Crow suit
    102: "(aura)",           # f → Aura range
    109: "(m)",              # m → Mask suit
    112: "(pulse)",          # p → Pulse range
    113: "(magic)",          # q → Magic range
    114: "(r)",              # r → Ram suit
    115: "(soulstone)",      # s → soulstone (inline text)
    116: "(t)",              # t → Tome suit
    117: "(fortitude)",      # u → Fortitude defense
    118: "(unusual_defense)", # v → Unusual defense
    120: "(warding)",        # x → Warding defense
    121: "(melee)",          # y → Melee range
    122: "(gun)",            # z → Gun/missile range
}

# Defensive icon codes → defensive_type values
DEFENSIVE_ICON_MAP = {
    117: "fortitude",        # u
    118: "unusual_defense",  # v
    120: "warding",          # x
}

# Range icon codes → action_type values
ACTION_TYPE_MAP = {
    121: "melee",            # y
    122: "missile",          # z → gun/missile
    113: "magic",            # q
    102: "aura",             # f (for tactical actions with aura range)
    112: "pulse",            # p (for tactical actions with pulse range)
}

# Trigger timing keywords found in trigger text
TRIGGER_TIMING_MAP = {
    "when resolving": "when_resolving",
    "after succeeding": "after_succeeding",
    "after failing": "after_failing",
    "after damaging": "after_damaging",
    "when declaring": "when_declaring",
    "after resolving": "after_resolving",
}

# Font role constants
FONT_NAME_LARGE = "Astoria-Bold"          # Model names (12.5pt), titles
FONT_NAME_ITALIC = "Astoria-BoldItalic"   # Characteristics, station info
FONT_LABEL = "FairplexWideOT-Bold"        # Stat labels (DF, SP, WP, SZ, COST)
FONT_STAT_VALUE = "ModestoPoster-Regular"  # Large stat values
FONT_ABILITY_NAME = "HarriText-ExtraBold" # Ability/action names, section headers
FONT_BODY = "HarriText-Regular"           # Body text
FONT_BOLD = "HarriText-Bold"              # Bold keywords in text
FONT_ITALIC = "HarriText-Italic"          # Conditional text, once per activation
FONT_TRIGGER = "HarriText-BoldItalic"     # Trigger names
FONT_BULLET = "ArponaSans-Bold"           # Diamond bullet separator
FONT_SYMBOL = "M4ESymbolsRegular"         # Game icon glyphs

# Position constants (page = 198.0 x 342.0 pt)
PAGE_WIDTH = 198.0
PAGE_HEIGHT = 342.0

# Front page stat positions (ModestoPoster-Regular)
STAT_REGIONS = {
    "df": {"x_range": (10, 30),  "y_range": (60, 90)},   # upper-left
    "sp": {"x_range": (165, 190), "y_range": (60, 90)},   # upper-right
    "wp": {"x_range": (10, 30),  "y_range": (130, 160)},  # lower-left
    "sz": {"x_range": (165, 190), "y_range": (130, 160)},  # lower-right
}

# Cost position
COST_REGION = {"x_range": (165, 195), "y_range": (5, 28), "font": FONT_STAT_VALUE, "size_range": (13, 16)}

# Characteristics/keywords Y range (170 to catch edge chars on wide arcs)
CHARKEY_Y_RANGE = (155, 215)

# Abilities Y start
ABILITIES_Y_START = 225

# Back page regions
BACK_NAME_Y_RANGE = (5, 25)
BACK_BASE_SIZE_Y_RANGE = (322, 340)

# Action table column X midpoints (for binning values)
COL_RG_X = (90, 115)
COL_SKL_X = (115, 135)
COL_RST_X = (135, 155)
COL_TN_X = (155, 172)
COL_DMG_X = (172, 195)


# ============================================================================
# SPAN EXTRACTION AND DEDUPLICATION
# ============================================================================

def _get_page_spans(page):
    """
    Extract all text spans from a page, deduplicated and sorted.

    Returns list of span dicts: {font, size, x0, y0, x1, y1, text, raw_chars}
    where raw_chars preserves original character codes for symbol detection.
    """
    data = page.get_text("dict")
    spans = []
    seen = set()

    for block in data["blocks"]:
        if block["type"] != 0:  # text blocks only
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                font = span["font"]
                size = round(span["size"], 1)
                bbox = tuple(round(x, 1) for x in span["bbox"])
                text = span["text"]

                # Dedup key: font + size + bbox + text
                key = (font, size, bbox, text)
                if key in seen:
                    continue
                seen.add(key)

                spans.append({
                    "font": font,
                    "size": size,
                    "x0": bbox[0],
                    "y0": bbox[1],
                    "x1": bbox[2],
                    "y1": bbox[3],
                    "text": text,
                    "raw_chars": [ord(c) for c in text],
                })

    # Sort by Y then X
    spans.sort(key=lambda s: (s["y0"], s["x0"]))
    return spans


def _map_symbol_text(text, font):
    """Replace M4ESymbolsRegular characters with icon text notation."""
    if font != FONT_SYMBOL:
        return text
    result = []
    for ch in text:
        code = ord(ch)
        if code in SYMBOL_MAP:
            result.append(SYMBOL_MAP[code])
        elif code == 32:  # space
            continue  # Skip spaces in symbol font
        else:
            result.append(f"[?{code}]")
    return "".join(result)


def _get_symbol_codes(span):
    """Get the M4E symbol character codes from a span, if it's a symbol font."""
    if span["font"] != FONT_SYMBOL:
        return []
    return [c for c in span["raw_chars"] if c != 32]  # exclude spaces


# ============================================================================
# CURVED TEXT RECONSTRUCTION
# ============================================================================

def _reconstruct_curved_text(spans):
    """
    Reconstruct text from individually-placed characters on curved paths.

    M4E cards place name/characteristics/keywords as individual characters
    along a curved path. Despite Y varying along the arc, X positions are
    always monotonically increasing. Simple X-sort is correct.

    Uses x-center (midpoint of x0, x1) for stability with overlapping chars.

    Returns the reconstructed string.
    """
    if not spans:
        return ""

    # Sort by x-center (midpoint) for robust ordering on curved paths
    sorted_spans = sorted(spans, key=lambda s: (s["x0"] + s["x1"]) / 2)
    return "".join(s["text"] for s in sorted_spans)


def _extract_characteristics_keywords(spans):
    """
    Parse the curved text zone to extract characteristics and keywords.

    Layout: [chars on left arc] • [keywords on right arc]
    where • is ArponaSans-Bold diamond bullet.

    Uses bullet X-position to split, NOT font variant, because some cards
    use BoldItalic for both sides (e.g. Bad Juju).

    Also captures Master info: crew_card_name and totem_name from
    Astoria-Bold at 6.3pt in the bottom area.

    Returns: (characteristics_list, keywords_list, extras_dict)
    """
    # Filter spans in the characteristics/keywords Y zone
    zone_spans = [s for s in spans
                  if CHARKEY_Y_RANGE[0] <= s["y0"] <= CHARKEY_Y_RANGE[1]]

    if not zone_spans:
        return [], [], {}

    # Find the diamond bullet — this separates characteristics from keywords
    bullet_spans = [s for s in zone_spans
                    if s["font"] == FONT_BULLET and "•" in s["text"]]

    # Collect Astoria curved-text chars by font variant
    # Size varies: 6.4pt (Fire Gamin), 7.1pt (Joss), 8.2pt (Bad Juju), 9.0pt (Dashel)
    # Exclude multi-char spans to avoid crew card name / totem name text
    italic_spans = [s for s in zone_spans
                    if s["font"] == FONT_NAME_ITALIC
                    and 5.5 <= s["size"] <= 10.0
                    and len(s["text"].strip()) <= 3]
    bold_spans = [s for s in zone_spans
                  if s["font"] == FONT_NAME_LARGE
                  and 5.5 <= s["size"] <= 10.0
                  and len(s["text"].strip()) <= 3]

    # Crew card name / totem name: Astoria-Bold multi-char at 6.0-6.5pt
    small_bold_spans = [s for s in zone_spans
                        if s["font"] == FONT_NAME_LARGE and 5.5 <= s["size"] <= 7.5
                        and len(s["text"].strip()) > 2]

    # STN (Summon Target Number): Astoria-Bold ~7.0pt
    stn_spans = [s for s in zone_spans
                 if s["font"] == FONT_NAME_LARGE and 6.5 <= s["size"] <= 7.5]

    # Split by bullet position into left (characteristics) and right (keywords)
    if bullet_spans:
        bullet_x = (bullet_spans[0]["x0"] + bullet_spans[0]["x1"]) / 2

        # Left side: prefer BoldItalic (avoids STN Bold chars), fall back to all
        left_italic = [s for s in italic_spans
                       if (s["x0"] + s["x1"]) / 2 < bullet_x]
        left_bold = [s for s in bold_spans
                     if (s["x0"] + s["x1"]) / 2 < bullet_x]
        left_italic_text = _reconstruct_curved_text(left_italic).strip()
        if left_italic_text:
            char_spans = left_italic
        else:
            char_spans = left_italic + left_bold

        # Right side: prefer Bold, fall back to BoldItalic (handles Bad Juju)
        right_bold = [s for s in bold_spans
                      if (s["x0"] + s["x1"]) / 2 > bullet_x]
        right_italic = [s for s in italic_spans
                        if (s["x0"] + s["x1"]) / 2 > bullet_x]
        right_bold_text = _reconstruct_curved_text(right_bold).strip()
        if right_bold_text:
            keyword_spans = right_bold
        else:
            keyword_spans = right_italic
    else:
        # No bullet found — all text goes to characteristics
        char_spans = italic_spans if italic_spans else bold_spans
        keyword_spans = []

    # Reconstruct text
    char_text = _reconstruct_curved_text(char_spans)
    kw_text = _reconstruct_curved_text(keyword_spans)
    # Strip any STN pattern that may have leaked into text
    char_text = re.sub(r'STN\s*:\s*\d+', '', char_text).strip()
    kw_text = re.sub(r'STN\s*:\s*\d+', '', kw_text).strip()

    # Parse characteristics: "Master,Living" or "Minion(3),Living,Beast"
    characteristics = _parse_char_keyword_string(char_text)

    # Parse keywords: "Guard" or "BigHat,Sooey"
    keywords = _parse_char_keyword_string(kw_text)

    # Extract extras (crew card name, totem, STN)
    extras = _extract_front_extras(small_bold_spans, stn_spans, zone_spans)

    return characteristics, keywords, extras


def _parse_char_keyword_string(text):
    """
    Parse a concatenated characteristic/keyword string into a list.

    Input: "Master,Living" or "Minion(3),Living,Beast" or "Guard"
    Output: ["Master", "Living"] or ["Minion (3)", "Living", "Beast"] or ["Guard"]
    """
    if not text:
        return []

    # Clean up the text
    text = text.strip().rstrip(",")

    # Split on commas (but not inside parentheses)
    items = []
    current = ""
    paren_depth = 0
    for ch in text:
        if ch == "(":
            paren_depth += 1
            current += ch
        elif ch == ")":
            paren_depth -= 1
            current += ch
        elif ch == "," and paren_depth == 0:
            item = current.strip()
            if item:
                items.append(item)
            current = ""
        else:
            current += ch

    item = current.strip()
    if item:
        items.append(item)

    # Normalize station format: "Minion(3)" → "Minion (3)"
    normalized = []
    for item in items:
        m = re.match(r'^(Minion|Peon)\((\d+)\)$', item)
        if m:
            normalized.append(f"{m.group(1)} ({m.group(2)})")
        else:
            normalized.append(item)

    return normalized


def _extract_front_extras(small_bold_spans, stn_spans, all_zone_spans):
    """
    Extract crew card name, totem name, and summon TN from the front page.

    Master cards show:
    - Bottom-left (X < 50): crew card name (Astoria-Bold 6.3pt, multiline)
    - Bottom-right (X > 130): totem name (Astoria-Bold 6.3pt, multiline)

    Non-Master cards may show:
    - STN:N (Summon Target Number) at Astoria-Bold 7.0pt
    """
    extras = {}

    # Separate crew card name (left) from totem name (right)
    # Only applies to 6.0-6.5pt size spans
    small_63_spans = [s for s in small_bold_spans if 6.0 <= s["size"] <= 6.5]

    if small_63_spans:
        left_spans = [s for s in small_63_spans if s["x0"] < PAGE_WIDTH / 2]
        right_spans = [s for s in small_63_spans if s["x0"] >= PAGE_WIDTH / 2]

        if left_spans:
            # Group by Y position to reconstruct multiline names
            extras["crew_card_name"] = _reconstruct_multiline_text(left_spans)

        if right_spans:
            extras["totem"] = _reconstruct_multiline_text(right_spans)

    # Extract STN (Summon Target Number)
    stn_text = _reconstruct_curved_text(stn_spans)
    stn_match = re.search(r'STN\s*:\s*(\d+)', stn_text)
    if stn_match:
        extras["summon_tn"] = int(stn_match.group(1))

    return extras


def _smart_title_case(text):
    """Convert all-caps text to title case, keeping articles/prepositions lowercase.

    Handles:
    - Apostrophes: "WINTER'S TEETH" → "Winter's Teeth" (not "Winter'S")
    - Hyphens: "DEATH-TOUCHED" → "Death-Touched" (capitalize after hyphen)
    - Small words: "ARBITER OF THE UNDEAD" → "Arbiter of the Undead"
    """
    small_words = {"a", "an", "and", "as", "at", "but", "by", "for", "in",
                   "nor", "of", "on", "or", "so", "the", "to", "up", "yet",
                   "aka", "that"}
    words = text.split()
    result = []
    for i, word in enumerate(words):
        lower = word.lower()
        if i > 0 and lower.strip("\"'(\u2018\u2019\u201c\u201d") in small_words:
            result.append(lower)
        else:
            # Handle hyphens: capitalize each part
            parts = lower.split("-")
            capped_parts = []
            for p in parts:
                capped_parts.append(_capitalize_first_letter(p))
            result.append("-".join(capped_parts))
    return " ".join(result)


def _capitalize_first_letter(s):
    """Capitalize the first letter in a string, handling leading punctuation."""
    for i, ch in enumerate(s):
        if ch.isalpha():
            return s[:i] + ch.upper() + s[i+1:]
    return s


def _reconstruct_multiline_text(spans):
    """Reconstruct multiline text from spans grouped by Y position."""
    if not spans:
        return ""

    # Group by Y position (within 3pt tolerance)
    lines = []
    current_line = [spans[0]]

    sorted_spans = sorted(spans, key=lambda s: (s["y0"], s["x0"]))

    for span in sorted_spans[1:]:
        if abs(span["y0"] - current_line[-1]["y0"]) <= 3.0:
            current_line.append(span)
        else:
            lines.append(current_line)
            current_line = [span]
    lines.append(current_line)

    # Reconstruct each line
    result_lines = []
    for line_spans in lines:
        sorted_line = sorted(line_spans, key=lambda s: s["x0"])
        text = " ".join(s["text"].strip() for s in sorted_line)
        if text.strip():
            result_lines.append(text.strip())

    return " ".join(result_lines)


# ============================================================================
# FRONT PAGE EXTRACTION
# ============================================================================

def _extract_front(page_spans, page, faction=None, pdf_path=None):
    """
    Extract stat card front page data.

    Returns dict matching Vision API front extraction schema.
    """
    notes = []

    # 1. MODEL NAME — Astoria-Bold at 10-13pt (varies by name length), Y range 15-65
    name_spans = [s for s in page_spans
                  if s["font"] == FONT_NAME_LARGE
                  and 9.5 <= s["size"] <= 13.5
                  and s["y0"] < 65]
    model_name_raw = _reconstruct_curved_text(name_spans)
    # Normalize from ALL CAPS to title case (matches existing DB convention)
    model_name = _smart_title_case(model_name_raw) if model_name_raw else ""

    if not model_name:
        notes.append("Could not extract model name from front page")

    # 2. STATS — ModestoPoster-Regular at 15.8pt in four quadrants
    stats = {}
    for stat_name, region in STAT_REGIONS.items():
        stat_spans = [s for s in page_spans
                      if s["font"] == FONT_STAT_VALUE
                      and 14.5 <= s["size"] <= 16.5
                      and region["x_range"][0] <= s["x0"] <= region["x_range"][1]
                      and region["y_range"][0] <= s["y0"] <= region["y_range"][1]]
        if stat_spans:
            val_text = stat_spans[0]["text"].strip()
            try:
                stats[stat_name] = int(val_text)
            except ValueError:
                stats[stat_name] = val_text
                notes.append(f"Non-integer {stat_name}: {val_text}")
        else:
            notes.append(f"Could not find {stat_name} stat value")

    # 3. COST — ModestoPoster-Regular at 14.4pt, top-right
    cost_spans = [s for s in page_spans
                  if s["font"] == FONT_STAT_VALUE
                  and 13.0 <= s["size"] <= 15.5
                  and s["x0"] > 165 and s["y0"] < 28]
    cost = None
    if cost_spans:
        cost = cost_spans[0]["text"].strip()
    else:
        notes.append("Could not find cost value")

    # 4. CHARACTERISTICS AND KEYWORDS — curved text with diamond bullet
    characteristics, keywords, extras = _extract_characteristics_keywords(page_spans)

    # 5. TITLE — Astoria-Bold 7.0pt below the name (Y 33-50)
    #    Only for Master title variants (e.g., "BUTCHER" under "DASHEL BARKER")
    title = None
    title_spans = [s for s in page_spans
                   if s["font"] == FONT_NAME_LARGE
                   and 6.5 <= s["size"] <= 7.5
                   and 30 < s["y0"] < 55]
    # Reconstruct ALL title chars first, then check for STN pattern
    # (Don't pre-filter individual chars — that removes "T" from "BUTCHER")
    if title_spans:
        title_text = _reconstruct_curved_text(title_spans)
        # Remove any embedded STN:N pattern and digits-only remnants
        title_text = re.sub(r'STN\s*:\s*\d+', '', title_text).strip()
        # Also strip any lone digits that might be STN remnants
        title_text = re.sub(r'^\d+$', '', title_text).strip()
        if title_text:
            # Normalize case: front has all-caps, back has title case
            title = _smart_title_case(title_text)

    # Also check back page for title (Astoria-BoldItalic at ~8.0pt)
    # This is handled at the caller level

    # 6. ABILITIES — HarriText-ExtraBold (names) + HarriText-Regular (text)
    abilities = _extract_abilities(page_spans)

    # 7. HEALTH — from graphical elements (pips), not text layer
    health = _extract_health_from_drawings(page)
    if health is None:
        notes.append("Health not extracted from PDF graphics — needs manual verification")

    # 8. SOULSTONE CACHE — also graphical
    soulstone_cache = _extract_soulstone_cache(page)

    # Determine faction from folder path
    if faction is None and pdf_path:
        faction = _faction_from_path(pdf_path)

    front = {
        "card_type": "stat_card_front",
        "name": model_name,
        "title": title,
        "faction": faction or "Unknown",
        "cost": cost,
        "stats": stats,
        "health": health,
        "soulstone_cache": soulstone_cache,
        "shields": 0,  # TODO: extract from graphics if present
        "infuses_soulstone_on_death": True,  # Default; overridden by validator for Peons
        "crew_card_name": extras.get("crew_card_name"),
        "totem": extras.get("totem"),
        "characteristics": characteristics,
        "keywords": keywords,
        "abilities": abilities,
        "extraction_notes": notes,
    }

    # Add summon TN if found
    if "summon_tn" in extras:
        front["summon_tn"] = extras["summon_tn"]

    return front


def _extract_abilities(spans):
    """
    Extract abilities from front page.

    Pattern: [optional defensive_icon] [name:] [text]
    - Name = HarriText-ExtraBold, ending with ":"
    - Text = HarriText-Regular (+ HarriText-Bold for game terms + HarriText-Italic for conditions)
    - Defensive icon = M4ESymbolsRegular u/v/x code immediately before name
    """
    # Filter to ability region (Y > 225)
    ability_spans = [s for s in spans if s["y0"] > ABILITIES_Y_START]

    if not ability_spans:
        return []

    abilities = []
    current_ability = None

    # Group spans by Y position into lines (3pt tolerance)
    lines = _group_into_lines(ability_spans, tolerance=2.0)

    for line_spans in lines:
        # Check if this line starts a new ability
        first_span = line_spans[0]

        # Check for defensive icon at start
        defensive_type = None
        ability_start_idx = 0

        if first_span["font"] == FONT_SYMBOL:
            codes = _get_symbol_codes(first_span)
            for code in codes:
                if code in DEFENSIVE_ICON_MAP:
                    defensive_type = DEFENSIVE_ICON_MAP[code]
                    break
            ability_start_idx = 1

        # Scan for an ExtraBold ability name in this line (not just position [1])
        # Skip whitespace-only spans (Regular spaces between symbol and name)
        has_name = False
        name_idx = ability_start_idx
        for idx in range(ability_start_idx, len(line_spans)):
            span = line_spans[idx]
            if span["font"] == FONT_ABILITY_NAME and span["text"].strip().endswith(":"):
                has_name = True
                name_idx = idx
                break
            # Stop scanning if we hit body text WITH content (skip whitespace-only)
            if span["font"] in (FONT_BODY, FONT_BOLD, FONT_ITALIC) and span["text"].strip():
                break

        if has_name:
            # Save previous ability
            if current_ability:
                current_ability["text"] = current_ability["text"].strip()
                abilities.append(current_ability)

            # Start new ability
            name_text = line_spans[name_idx]["text"].strip().rstrip(":")

            # Collect rest of line as text
            remaining = line_spans[name_idx + 1:]
            text_parts = _spans_to_text(remaining)

            current_ability = {
                "name": name_text,
                "text": text_parts,
                "defensive_type": defensive_type,
            }
        elif current_ability:
            # Continuation of current ability
            text_parts = _spans_to_text(line_spans)
            current_ability["text"] += " " + text_parts

    # Don't forget the last ability
    if current_ability:
        current_ability["text"] = current_ability["text"].strip()
        abilities.append(current_ability)

    return abilities


def _spans_to_text(spans):
    """Convert a list of spans to text, handling symbol substitution."""
    parts = []
    for s in spans:
        if s["font"] == FONT_SYMBOL:
            parts.append(_map_symbol_text(s["text"], s["font"]))
        else:
            parts.append(s["text"])

    # Join and clean up spacing
    text = "".join(parts)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _group_into_lines(spans, tolerance=2.0):
    """Group spans into lines based on Y position proximity."""
    if not spans:
        return []

    sorted_spans = sorted(spans, key=lambda s: (s["y0"], s["x0"]))
    lines = []
    current_line = [sorted_spans[0]]

    for span in sorted_spans[1:]:
        if abs(span["y0"] - current_line[0]["y0"]) <= tolerance:
            current_line.append(span)
        else:
            # Sort line by X position
            current_line.sort(key=lambda s: s["x0"])
            lines.append(current_line)
            current_line = [span]

    current_line.sort(key=lambda s: s["x0"])
    lines.append(current_line)

    return lines


# ============================================================================
# HEALTH AND SOULSTONE EXTRACTION (GRAPHICAL)
# ============================================================================

def _count_rect_groups(rects):
    """Count unique X-position groups from a list of fitz.Rect objects."""
    if not rects:
        return 0
    unique_x = sorted(set(round(r.x0, 0) for r in rects))
    if not unique_x:
        return 0
    groups = 1
    prev = unique_x[0]
    for x in unique_x[1:]:
        if x - prev >= 3.0:
            groups += 1
        prev = x
    return groups


def _extract_health_from_drawings(page):
    """
    Extract health value by counting health pip drawings.

    Health pips are small squares (~10x10pt) at Y > 318 (bottom of card).
    Each pip has a white inner fill and a red border. Testing showed:
    - White rect count = correct health for most cards
    - Red rect count = health + 1 for most (extra border element)
    - Some templates only have white (no red)

    Strategy: count white rects as primary, fall back to max(white, red-1).
    """
    drawings = page.get_drawings()

    white_rects = []
    red_rects = []

    for d in drawings:
        rect = fitz.Rect(d["rect"])
        w = rect.width
        h = rect.height
        # Health pip boxes: ~10.3 x 10.3pt (inner) or ~11.3 x 11.3pt (outer)
        if 9.0 < w < 13.0 and 9.0 < h < 13.0 and rect.y0 > 318:
            fill = d.get("fill")
            if fill == (1.0, 1.0, 1.0):
                white_rects.append(rect)
            elif fill and len(fill) == 3:
                r, g, b = fill
                if r > 0.5 and g < 0.3 and b < 0.3:
                    red_rects.append(rect)

    white_count = _count_rect_groups(white_rects)
    red_count = _count_rect_groups(red_rects)

    # Primary: white rect count (most reliable)
    # Fallback: max of white and (red - 1)
    health = max(white_count, max(0, red_count - 1)) if (white_count or red_count) else 0

    # Validate: health should be 0-16 range
    if health > 16:
        return None

    # Return 0 for cards with no pips (e.g., Marathine "does not have health")
    return health


def _extract_soulstone_cache(page):
    """
    Extract soulstone cache value from graphical elements.

    Soulstone cache icons appear near the cost area for Masters/Henchmen.
    Returns int or None.
    """
    # Soulstone cache is hard to extract from graphics alone
    # For now, return None and let it be populated from existing data
    return None


# ============================================================================
# BACK PAGE EXTRACTION
# ============================================================================

def _extract_back(page_spans, page):
    """
    Extract stat card back page data.

    Returns dict matching Vision API back extraction schema.
    """
    notes = []

    # 1. MODEL NAME — Astoria-Bold at 11.0pt, centered, Y 5-25
    #    Back page name is a single span (not curved like front)
    name_spans = [s for s in page_spans
                  if s["font"] == FONT_NAME_LARGE
                  and 9.5 <= s["size"] <= 12.5
                  and s["y0"] < 32
                  and s["text"].strip()]  # Skip whitespace-only spans
    back_name = ""
    if name_spans:
        # Join all name spans (handles multiline names like "DISEASE CONTAINMENT UNIT")
        raw = " ".join(s["text"].strip() for s in name_spans if s["text"].strip())
        back_name = _smart_title_case(raw)
    else:
        # Fallback: any large Astoria-Bold text with content in top region
        fallback = [s for s in page_spans
                    if s["font"] == FONT_NAME_LARGE
                    and s["size"] > 9.0
                    and s["y0"] < 35
                    and s["text"].strip()]
        if fallback:
            raw = " ".join(s["text"].strip() for s in fallback if s["text"].strip())
            back_name = _smart_title_case(raw)

    # 2. TITLE — Astoria-BoldItalic at ~8.0pt, below name
    title = None
    title_spans = [s for s in page_spans
                   if s["font"] == FONT_NAME_ITALIC
                   and 7.0 <= s["size"] <= 9.0
                   and s["y0"] < 32]
    if title_spans:
        title = title_spans[0]["text"].strip()

    # 3. BASE SIZE — Astoria-Bold at 7.0pt, Y > 322
    base_size = None
    base_spans = [s for s in page_spans
                  if s["font"] == FONT_NAME_LARGE
                  and 6.0 <= s["size"] <= 8.0
                  and s["y0"] > 322]
    if base_spans:
        base_size = base_spans[0]["text"].strip()

    # 4. SECTION HEADERS — find "Attack Actions" and "Tactical Actions"
    sections = _find_action_sections(page_spans)

    # 5. PARSE ACTIONS in each section
    attack_actions = []
    tactical_actions = []

    for section in sections:
        actions = _parse_action_section(page_spans, section)
        if section["type"] == "attack":
            attack_actions.extend(actions)
        else:
            tactical_actions.extend(actions)

    back = {
        "card_type": "stat_card_back",
        "name": back_name,
        "title": title,
        "base_size": base_size,
        "attack_actions": attack_actions,
        "tactical_actions": tactical_actions,
        "extraction_notes": notes,
    }

    return back


def _find_action_sections(spans):
    """
    Find section headers (Attack Actions, Tactical Actions) and their Y ranges.

    Returns list of dicts: {type, header_y, start_y, end_y}
    """
    sections = []

    # Find section headers: HarriText-ExtraBold at ~8.9pt
    # Broadened size range to catch template variations
    header_spans = [s for s in spans
                    if s["font"] == FONT_ABILITY_NAME
                    and 7.5 <= s["size"] <= 10.0]

    for span in header_spans:
        text = span["text"].strip().lower()
        if "attack" in text and "action" in text:
            sections.append({
                "type": "attack",
                "header_y": span["y0"],
                "start_y": span["y1"],  # Content starts after header
                "end_y": PAGE_HEIGHT,    # Will be trimmed
            })
        elif "tactical" in text and "action" in text:
            sections.append({
                "type": "tactical",
                "header_y": span["y0"],
                "start_y": span["y1"],
                "end_y": PAGE_HEIGHT,
            })

    # Sort sections by Y position
    sections.sort(key=lambda s: s["header_y"])

    # Set end_y for each section (starts at next section's header)
    for i in range(len(sections) - 1):
        sections[i]["end_y"] = sections[i + 1]["header_y"]

    # Last section ends at base size area
    if sections:
        sections[-1]["end_y"] = 320.0

    return sections


def _parse_action_section(all_spans, section):
    """
    Parse all actions within a section (Attack or Tactical).

    Each action has:
    - Name line: [optional aura/pulse icon] [ExtraBold name] [table values in columns]
    - Optional effect text (italic conditions, regular text)
    - Optional triggers (BoldItalic, indented)
    """
    # Filter spans within this section's Y range
    section_spans = [s for s in all_spans
                     if section["start_y"] <= s["y0"] < section["end_y"]]

    if not section_spans:
        return []

    # Skip column header row (Rg, Skl, Rst, TN, Dmg)
    # These are HarriText-ExtraBold at 8.1pt in the column positions
    col_header_y = None
    for s in section_spans:
        if (s["font"] == FONT_ABILITY_NAME
            and 7.5 <= s["size"] <= 8.5
            and s["text"].strip() in ("Rg", "Skl", "Rst", "TN", "Dmg")):
            col_header_y = s["y0"]
            break

    if col_header_y is not None:
        section_spans = [s for s in section_spans if s["y0"] > col_header_y + 2]

    # Group into lines
    lines = _group_into_lines(section_spans, tolerance=2.0)

    # Parse lines into actions
    actions = []
    current_action = None
    has_active_trigger = False

    for line_spans in lines:
        line_type = _classify_action_line(line_spans, has_active_trigger)

        if line_type == "action_header":
            parsed = _parse_action_header(line_spans, section["type"])

            # Check if this is a name continuation (no column values filled)
            # Multi-line action names like '"Look Upon Your Works"'
            has_columns = (parsed["range"] or parsed["skill_value"] != "0"
                           or parsed["resist"] or parsed["tn"] != "-"
                           or parsed["damage"] != "-")

            if not has_columns and (current_action or len(parsed["name"]) <= 2):
                # Continuation of previous action name, or artifact (single char)
                if current_action:
                    current_action["name"] += " " + parsed["name"]
                # else: skip artifact line with no current action
            else:
                # Save previous action
                if current_action:
                    current_action["effects"] = current_action["effects"].strip()
                    actions.append(current_action)

                # Start new action
                current_action = parsed
                has_active_trigger = False

        elif line_type == "trigger" and current_action:
            trigger = _parse_trigger_line(line_spans)
            if trigger:
                current_action["triggers"].append(trigger)
                has_active_trigger = True

        elif line_type == "trigger_continuation" and current_action and current_action["triggers"]:
            # Continue previous trigger text
            text = _spans_to_text(line_spans)
            current_action["triggers"][-1]["text"] += " " + text

        elif line_type == "effect_text" and current_action:
            text = _spans_to_text(line_spans)
            current_action["effects"] += " " + text
            has_active_trigger = False  # Effect text breaks trigger continuation

    # Don't forget the last action
    if current_action:
        current_action["effects"] = current_action["effects"].strip()
        actions.append(current_action)

    return actions


def _classify_action_line(line_spans, has_active_trigger=False):
    """
    Classify what kind of line this is in the action section.

    Args:
        line_spans: list of span dicts for this line
        has_active_trigger: whether we're currently inside a trigger

    Returns: "action_header", "trigger", "trigger_continuation", "effect_text"
    """
    if not line_spans:
        return "effect_text"

    # Find the first non-whitespace span (trigger lines often start with tab spans)
    first = line_spans[0]
    first_content = first
    for s in line_spans:
        if s["text"].strip():
            first_content = s
            break

    # Check if line contains a BoldItalic span (trigger name indicator)
    has_bold_italic = any(s["font"] == FONT_TRIGGER for s in line_spans)

    # Check if line contains a Symbol span with a SUIT icon (c=99, m=109, r=114, t=116)
    # Other symbols (soulstone, aura, pulse, melee, etc.) are NOT suit indicators
    SUIT_CODES = {99, 109, 114, 116}  # c, m, r, t
    has_suit_symbol = any(
        s["font"] == FONT_SYMBOL and any(c in SUIT_CODES for c in _get_symbol_codes(s))
        for s in line_spans
    )

    # Check if line contains an ExtraBold span (action name indicator)
    has_extra_bold = any(
        s["font"] == FONT_ABILITY_NAME and s["size"] < 8.5
        for s in line_spans
    )

    # Trigger: has a suit symbol AND a BoldItalic trigger name, at indented X
    # The symbol may not be first (tab spans precede it), so check first_content or has_suit_symbol
    if has_suit_symbol and has_bold_italic and first["x0"] >= 9:
        return "trigger"

    # Action header: ExtraBold name at left margin (X < 15), possibly preceded by symbol
    if first_content["font"] == FONT_ABILITY_NAME and first_content["size"] < 8.5 and first_content["x0"] < 15:
        return "action_header"

    if first_content["font"] == FONT_SYMBOL and first_content["x0"] < 15 and has_extra_bold:
        return "action_header"

    # Trigger continuation: indented body text when we're inside a trigger
    if has_active_trigger and first["x0"] >= 18 and first["font"] in (FONT_BODY, FONT_BOLD, FONT_ITALIC):
        return "trigger_continuation"

    # Effect text (italic conditions or regular body text)
    return "effect_text"


def _parse_action_header(line_spans, section_type):
    """
    Parse an action header line.

    Layout: [optional range_icon] [ExtraBold name] [optional type_icon] [Rg col] [Skl col] [Rst col] [TN col] [Dmg col]
    """
    action_type = None
    action_name = ""
    range_val = ""
    skill_val = ""
    resist_val = None
    tn_val = ""
    damage_val = ""

    # Process spans
    name_parts = []
    range_icon = None

    for span in line_spans:
        x_mid = (span["x0"] + span["x1"]) / 2

        # Symbol font: could be action type or range prefix
        if span["font"] == FONT_SYMBOL:
            codes = _get_symbol_codes(span)
            for code in codes:
                if code in ACTION_TYPE_MAP:
                    if span["x0"] < 95:
                        # Before columns: this is the action type/range icon
                        # For melee/gun/magic before name, it's the action type
                        # For aura/pulse before name, it sets the range type
                        at = ACTION_TYPE_MAP[code]
                        if at in ("melee", "missile", "magic"):
                            action_type = at
                            range_icon = SYMBOL_MAP[code]
                        elif at in ("aura", "pulse"):
                            range_icon = SYMBOL_MAP[code]
                    elif COL_RG_X[0] <= x_mid <= COL_RG_X[1]:
                        # In the Rg column: range type indicator
                        at = ACTION_TYPE_MAP[code]
                        if at in ("melee", "missile", "magic"):
                            action_type = at
                            range_icon = SYMBOL_MAP[code]
                        elif at in ("aura", "pulse"):
                            range_icon = SYMBOL_MAP[code]
            continue

        # ExtraBold: action name
        if span["font"] == FONT_ABILITY_NAME and span["x0"] < 95:
            name_parts.append(span["text"].strip())
            continue

        # Column values (use X midpoint to determine column)
        if COL_RG_X[0] <= x_mid <= COL_RG_X[1]:
            range_val += span["text"].strip()
        elif COL_SKL_X[0] <= x_mid <= COL_SKL_X[1]:
            skill_val += span["text"].strip()
        elif COL_RST_X[0] <= x_mid <= COL_RST_X[1]:
            if span["font"] == FONT_BOLD:
                resist_val = span["text"].strip()
            else:
                r = span["text"].strip()
                if r and r != "-":
                    resist_val = r
        elif COL_TN_X[0] <= x_mid <= COL_TN_X[1]:
            tn_val += span["text"].strip()
        elif COL_DMG_X[0] <= x_mid <= COL_DMG_X[1]:
            damage_val += span["text"].strip()

    action_name = " ".join(name_parts).rstrip(":")

    # Build range string
    if range_icon and range_val:
        range_str = f"{range_icon} {range_val}"
    elif range_icon:
        range_str = range_icon
    elif range_val:
        range_str = range_val
    else:
        range_str = ""

    # For tactical actions, force action_type and resist to None
    if section_type == "tactical":
        action_type = None
        resist_val = None
    elif section_type == "attack" and action_type is None:
        # Attack actions without explicit icon: default to "variable"
        action_type = "variable"

    return {
        "name": action_name,
        "action_type": action_type,
        "range": range_str,
        "skill_value": skill_val or "0",
        "resist": resist_val,
        "tn": tn_val or "-",
        "damage": damage_val or "-",
        "effects": "",
        "triggers": [],
    }


def _parse_trigger_line(line_spans):
    """
    Parse a trigger line.

    Layout: [suit_icon] [BoldItalic "Name:"] [Regular text...]
    """
    if not line_spans:
        return None

    suit = ""
    trigger_name = ""
    trigger_text = ""

    # Find suit symbol (may not be first — leading whitespace/tab spans)
    idx = 0
    for i, s in enumerate(line_spans):
        if s["font"] == FONT_SYMBOL:
            codes = _get_symbol_codes(s)
            suit_parts = []
            for code in codes:
                if code in SYMBOL_MAP:
                    suit_parts.append(SYMBOL_MAP[code])
            suit = "".join(suit_parts)
            idx = i + 1
            break

    # Find BoldItalic trigger name ending with ":"
    for i in range(idx, len(line_spans)):
        if line_spans[i]["font"] == FONT_TRIGGER:
            trigger_name = line_spans[i]["text"].strip().rstrip(":")
            idx = i + 1
            break
        # Skip whitespace-only Regular spans
        if line_spans[i]["text"].strip():
            break

    # Rest is trigger text
    remaining = line_spans[idx:]
    trigger_text = _spans_to_text(remaining)

    # Determine timing from text
    timing = _extract_timing(trigger_text)

    return {
        "name": trigger_name,
        "suit": suit,
        "timing": timing,
        "text": trigger_text,
    }


def _extract_timing(text):
    """Extract trigger timing from the trigger text."""
    text_lower = text.lower()

    for phrase, timing in TRIGGER_TIMING_MAP.items():
        if phrase in text_lower:
            return timing

    # Default: if text mentions damage, likely after_damaging
    # If text mentions declaring, likely when_declaring
    # Otherwise, default to after_succeeding (most common)
    return "after_succeeding"


# ============================================================================
# FACTION DETECTION
# ============================================================================

def _faction_from_path(pdf_path):
    """Determine faction from the PDF file path."""
    path = Path(pdf_path)
    parts = path.parts

    faction_names = {
        "Guild", "Arcanists", "Neverborn", "Bayou",
        "Outcasts", "Resurrectionists", "Ten Thunders", "Explorer's Society"
    }

    for part in parts:
        if part in faction_names:
            return part
        # Handle path separators
        if part.replace("'", "'") in faction_names:
            return part.replace("'", "'")

    return "Unknown"


# ============================================================================
# PUBLIC API
# ============================================================================

def extract_stat_card_text(pdf_path, faction=None):
    """
    Extract front + back from a 2-page stat card PDF.

    Returns: {"front": {...}, "back": {...}} matching Vision API schema.
    """
    pdf_path = str(pdf_path)
    doc = fitz.open(pdf_path)

    if len(doc) < 2:
        doc.close()
        return {"error": f"Expected 2-page stat card, got {len(doc)} pages"}

    # Extract front page
    front_spans = _get_page_spans(doc[0])
    front = _extract_front(front_spans, doc[0], faction=faction, pdf_path=pdf_path)

    # Extract back page
    back_spans = _get_page_spans(doc[1])
    back = _extract_back(back_spans, doc[1])

    # Cross-reference title from back to front
    if back.get("title") and not front.get("title"):
        front["title"] = back["title"]

    doc.close()

    return {"front": front, "back": back}


def extract_crew_card_text(pdf_path, faction=None):
    """
    Extract crew card from PDF.

    Crew cards are 2 pages: front (abilities/actions/markers) and back (tokens).
    Returns merged crew card data.
    """
    # TODO: Implement crew card parsing
    return {"error": "Crew card text extraction not yet implemented"}


def extract_upgrade_card_text(pdf_path, faction=None):
    """
    Extract upgrade card from PDF.

    Returns upgrade card data.
    """
    # TODO: Implement upgrade card parsing
    return {"error": "Upgrade card text extraction not yet implemented"}


# ============================================================================
# DEBUG / CLI
# ============================================================================

def dump_spans(pdf_path, page_idx=None):
    """Debug: dump all spans from a PDF."""
    doc = fitz.open(pdf_path)

    pages = range(len(doc)) if page_idx is None else [page_idx]

    for pi in pages:
        if pi >= len(doc):
            continue
        label = "FRONT" if pi == 0 else "BACK" if pi == 1 else f"PAGE{pi}"
        print(f"\n{'='*80}")
        print(f"PAGE {pi} ({label})")
        print(f"{'='*80}")

        spans = _get_page_spans(doc[pi])
        for s in spans:
            font = s["font"]
            size = s["size"]
            text = s["text"]
            if s["font"] == FONT_SYMBOL:
                codes = s["raw_chars"]
                mapped = _map_symbol_text(text, font)
                print(f"  {label} | {font:30s} {size:5.1f} [{s['x0']:6.1f},{s['y0']:6.1f}]-[{s['x1']:6.1f},{s['y1']:6.1f}] codes={codes} → {mapped}")
            else:
                if text.strip():
                    print(f"  {label} | {font:30s} {size:5.1f} [{s['x0']:6.1f},{s['y0']:6.1f}]-[{s['x1']:6.1f},{s['y1']:6.1f}] {repr(text.strip())}")

    doc.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract M4E card data from PDF text")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--card-type", choices=["stat", "crew", "upgrade"], default="stat")
    parser.add_argument("--faction", help="Override faction (default: detect from path)")
    parser.add_argument("--debug", action="store_true", help="Dump raw spans")
    parser.add_argument("--output", "-o", help="Output JSON file")
    parser.add_argument("--page", type=int, help="Debug: dump specific page only")
    args = parser.parse_args()

    if args.debug:
        dump_spans(args.pdf, args.page)
        sys.exit(0)

    if args.card_type == "stat":
        result = extract_stat_card_text(args.pdf, faction=args.faction)
    elif args.card_type == "crew":
        result = extract_crew_card_text(args.pdf, faction=args.faction)
    elif args.card_type == "upgrade":
        result = extract_upgrade_card_text(args.pdf, faction=args.faction)
    else:
        result = {"error": f"Unknown card type: {args.card_type}"}

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Written to {output_path}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
