#!/usr/bin/env python3
"""
merger.py â€” Merge front and back card extractions into a unified card JSON.

Takes the two-part extraction output and produces a single canonical card record
ready for validation and database loading.

Usage:
    python merger.py extracted_card.json --output merged_card.json
"""
import argparse
import json
import re
import sys
from pathlib import Path


def merge_stat_card(front: dict, back: dict, source_pdf: str = None) -> dict:
    """
    Merge front and back extractions into unified card format.
    
    Front provides: name, title, faction, cost, stats, characteristics, keywords,
                    health, soulstone, shields, abilities, base_size (sometimes)
    Back provides:  attack_actions, tactical_actions, base_size (always), name/title (for cross-check)
    """
    # Cross-check name/title match
    warnings = []
    front_name = front.get("name", "").strip()
    back_name = back.get("name", "").strip()
    if front_name.lower() != back_name.lower():
        warnings.append(f"Name mismatch: front='{front_name}' back='{back_name}'")
    
    front_title = front.get("title")
    back_title = back.get("title")
    if front_title != back_title:
        warnings.append(f"Title mismatch: front='{front_title}' back='{back_title}'")
    
    # Parse station and model_limit from characteristics
    characteristics = front.get("characteristics", [])
    station = None
    model_limit = 1
    
    for char in characteristics:
        # Check for station with limit: "Minion (3)", "Peon (7)"
        m = re.match(r'(Minion|Peon)\s*\((\d+)\)', char)
        if m:
            station = m.group(1)
            model_limit = int(m.group(2))
            break
        elif char in ("Master", "Henchman", "Totem"):
            station = char
            break
    
    # If "Unique" in characteristics, model_limit = 1
    if "Unique" in characteristics:
        model_limit = 1
    
    # Base size: prefer back (always shown there), fall back to front
    base_size = back.get("base_size") or front.get("base_size")
    if base_size:
        # Normalize: "30 mm" -> "30mm", "50mm" -> "50mm"
        base_size = base_size.replace(" ", "").lower()
    
    # Build unified card
    stats = front.get("stats", {})
    
    # Merge actions: add category and action_type fields
    attack_actions = []
    for act in back.get("attack_actions", []):
        act["category"] = "attack_actions"
        # Ensure action_type exists
        if "action_type" not in act or act["action_type"] is None:
            warnings.append(f"Attack action '{act.get('name')}' missing action_type")
        attack_actions.append(act)
    
    tactical_actions = []
    for act in back.get("tactical_actions", []):
        act["category"] = "tactical_actions"
        act["action_type"] = None  # Force null for tacticals
        # Check for layout exception: attacks listed under tactical header
        if act.get("resist") is not None:
            warnings.append(
                f"Tactical action '{act.get('name')}' has resist='{act.get('resist')}' â€” "
                "may be attack action under tactical header (layout exception). "
                "Reclassifying as attack_action."
            )
            act["category"] = "attack_actions"
            # Need to determine action_type from range
            rng = act.get("range", "")
            if "(melee)" in str(rng).lower() or "melee" in str(rng).lower():
                act["action_type"] = "melee"
            elif "(gun)" in str(rng).lower() or "(missile)" in str(rng).lower():
                act["action_type"] = "missile"
            elif "(magic)" in str(rng).lower():
                act["action_type"] = "magic"
            else:
                act["action_type"] = "melee"  # default for unknown ranged attacks
                warnings.append(f"Could not determine action_type for '{act.get('name')}', defaulted to melee")
        tactical_actions.append(act)
    
    # Separate reclassified attacks from true tacticals
    true_tacticals = [a for a in tactical_actions if a["category"] == "tactical_actions"]
    reclassified_attacks = [a for a in tactical_actions if a["category"] == "attack_actions"]
    all_attacks = attack_actions + reclassified_attacks
    
    merged = {
        "card_type": "stat_card",
        "name": front_name,
        "title": front_title,
        "faction": front.get("faction", "Unknown"),
        "station": station,
        "model_limit": model_limit,
        "cost": front.get("cost"),
        "df": stats.get("df"),
        "wp": stats.get("wp"),
        "sz": stats.get("sz"),
        "sp": stats.get("sp"),
        "health": front.get("health"),
        "soulstone_cache": front.get("soulstone_cache"),
        "shields": front.get("shields", 0),
        "base_size": base_size,
        "infuses_soulstone_on_death": front.get("infuses_soulstone_on_death", True),
        "crew_card_name": front.get("crew_card_name"),
        "totem": front.get("totem"),
        "characteristics": characteristics,
        "keywords": front.get("keywords", []),
        "abilities": front.get("abilities", []),
        "actions": all_attacks + true_tacticals,
        "source_pdf": source_pdf,
        "merge_warnings": warnings,
        "extraction_notes": (
            front.get("extraction_notes", []) + 
            back.get("extraction_notes", [])
        ),
    }
    
    return merged


def merge_from_file(input_path: str, source_pdf: str = None) -> dict:
    """Load extraction JSON and merge."""
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    
    if "front" in data and "back" in data:
        return merge_stat_card(data["front"], data["back"], source_pdf)
    elif data.get("card_type") == "crew_card":
        # Crew cards don't need merging
        data["source_pdf"] = source_pdf
        return data
    else:
        return {"error": "Unknown card format", "data": data}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge front/back card extractions")
    parser.add_argument("input", help="Extraction JSON file")
    parser.add_argument("--output", "-o", required=True, help="Output merged JSON")
    parser.add_argument("--source-pdf", help="Original PDF filename for traceability")
    args = parser.parse_args()
    
    result = merge_from_file(args.input, args.source_pdf)
    
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    warnings = result.get("merge_warnings", [])
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  âš  {w}")
    
    print(f"Merged card written to {args.output}")
