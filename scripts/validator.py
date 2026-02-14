#!/usr/bin/env python3
"""
validator.py â€” Validate merged card JSON against hard rules, soft rules, 
and known hallucination patterns.

Returns a validation report with pass/fail status and flags for human review.

Usage:
    python validator.py merged_card.json
    python validator.py merged_card.json --strict  # fail on soft rule violations too
"""
import argparse
import json
import re
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent.parent
REFERENCE_PATH = SCRIPT_DIR / "reference" / "reference_data.json"


def load_reference() -> dict:
    """Load reference data for validation."""
    with open(REFERENCE_PATH, encoding="utf-8") as f:
        return json.load(f)


class ValidationResult:
    def __init__(self, card_name: str):
        self.card_name = card_name
        self.hard_violations = []      # Must fix â€” data is wrong
        self.soft_flags = []           # Unusual but possible â€” flag for review
        self.hallucination_flags = []  # Suspected fabrication patterns
        self.info = []                 # Informational notes
    
    @property
    def passed(self) -> bool:
        return len(self.hard_violations) == 0
    
    @property
    def needs_review(self) -> bool:
        return len(self.soft_flags) > 0 or len(self.hallucination_flags) > 0
    
    def to_dict(self) -> dict:
        return {
            "card_name": self.card_name,
            "passed": self.passed,
            "needs_review": self.needs_review,
            "hard_violations": self.hard_violations,
            "soft_flags": self.soft_flags,
            "hallucination_flags": self.hallucination_flags,
            "info": self.info,
        }
    
    def summary(self) -> str:
        status = "âœ“ PASS" if self.passed else "âœ— FAIL"
        review = " [NEEDS REVIEW]" if self.needs_review else ""
        lines = [f"{status}{review} â€” {self.card_name}"]
        for v in self.hard_violations:
            lines.append(f"  âœ— HARD: {v}")
        for f in self.soft_flags:
            lines.append(f"  âš  SOFT: {f}")
        for h in self.hallucination_flags:
            lines.append(f"  ðŸ” HALLUCINATION: {h}")
        for i in self.info:
            lines.append(f"  â„¹ {i}")
        return "\n".join(lines)


def validate_stat_card(card: dict, ref: dict) -> ValidationResult:
    """Run all validation checks on a merged stat card."""
    name = card.get("name", "Unknown")
    title = card.get("title", "")
    label = f"{name}" + (f" ({title})" if title else "")
    
    result = ValidationResult(label)
    
    # ============================================================
    # HARD RULES â€” Must pass
    # ============================================================
    
    # 1. Required fields exist
    for field in ["name", "faction", "df", "wp", "sz", "sp", "health"]:
        if card.get(field) is None:
            result.hard_violations.append(f"Missing required field: {field}")
    
    # 2. Faction is valid
    faction = card.get("faction", "")
    if faction not in ref["factions"]:
        result.hard_violations.append(f"Invalid faction: '{faction}'")
    
    # 3. Stats are integers and in reasonable ranges
    for stat_name in ["df", "wp", "sz", "sp"]:
        val = card.get(stat_name)
        if val is not None:
            if not isinstance(val, int):
                result.hard_violations.append(f"{stat_name} must be integer, got {type(val).__name__}: {val}")
            elif val < 0 or val > 10:
                result.hard_violations.append(f"{stat_name}={val} outside expected range 0-10")
    
    health = card.get("health")
    if health is not None:
        if not isinstance(health, int):
            result.hard_violations.append(f"health must be integer, got {type(health).__name__}")
        elif health < 1 or health > 20:
            result.hard_violations.append(f"health={health} outside expected range 1-20")
    
    # 4. Action validation
    actions = card.get("actions", [])
    for act in actions:
        act_name = act.get("name", "???")
        cat = act.get("category", "")
        
        # Attack actions MUST have resist
        if cat == "attack_actions":
            if act.get("resist") is None:
                result.hard_violations.append(f"Attack '{act_name}' missing resist stat")
            
            # Attack actions MUST have action_type
            atype = act.get("action_type")
            valid_types = ref["action_types"]["attack"]
            if atype not in valid_types:
                result.hard_violations.append(
                    f"Attack '{act_name}' invalid action_type: '{atype}' (must be {valid_types})")
        
        # Tactical actions MUST NOT have resist or action_type
        elif cat == "tactical_actions":
            if act.get("resist") is not None:
                result.hard_violations.append(
                    f"Tactical '{act_name}' has resist='{act.get('resist')}' (must be null)")
            if act.get("action_type") is not None:
                result.hard_violations.append(
                    f"Tactical '{act_name}' has action_type='{act.get('action_type')}' (must be null)")
        
        # Trigger timing validation
        valid_timings = ref["trigger_timings"]
        for trig in act.get("triggers", []):
            timing = trig.get("timing")
            if timing not in valid_timings:
                result.hard_violations.append(
                    f"Trigger '{trig.get('name')}' on '{act_name}' has invalid timing: '{timing}'")
    
    # 5. Station/model_limit consistency
    characteristics = card.get("characteristics", [])
    model_limit = card.get("model_limit", 1)
    
    if "Unique" in characteristics and model_limit != 1:
        result.hard_violations.append(f"Unique model has model_limit={model_limit} (must be 1)")
    
    for char in characteristics:
        m = re.match(r'(Minion|Peon)\s*\((\d+)\)', char)
        if m:
            expected = int(m.group(2))
            if model_limit != expected:
                result.hard_violations.append(
                    f"{m.group(1)}({expected}) but model_limit={model_limit}")
    
    # 6. Master requirements
    station = card.get("station")
    if station == "Master":
        if not card.get("crew_card_name"):
            result.soft_flags.append("Master missing crew_card_name (populated post-processing)")
        if not card.get("totem"):
            result.hard_violations.append("Master missing totem")
    
    # ============================================================
    # SOFT RULES â€” Flag for review
    # ============================================================
    
    # Soulstone on death
    infuses = card.get("infuses_soulstone_on_death")
    if station == "Peon" and infuses:
        result.soft_flags.append("Peon with infuses_soulstone_on_death=true (unusual)")
    if station not in ("Peon", None) and not infuses:
        result.soft_flags.append(f"{station} with infuses_soulstone_on_death=false (unusual)")
    
    # Cost expectations
    cost = card.get("cost")
    if station in ("Master", "Totem") and cost not in ("-", None):
        result.soft_flags.append(f"{station} with cost='{cost}' (usually '-')")
    
    # Base size validation
    base_size = card.get("base_size")
    if base_size and base_size not in ref["base_sizes"]:
        result.soft_flags.append(f"Unusual base_size: '{base_size}'")
    
    # No actions at all
    if len(actions) == 0:
        result.soft_flags.append("Card has no actions â€” verify back was parsed")
    
    # No abilities at all
    if len(card.get("abilities", [])) == 0:
        result.soft_flags.append("Card has no abilities â€” verify front was parsed")
    
    # ============================================================
    # HALLUCINATION CHECKS
    # ============================================================
    
    # WP/SP swap detection: WP is usually <= SP for Bayou models
    wp = card.get("wp", 0)
    sp = card.get("sp", 0)
    if wp > sp + 2:
        result.hallucination_flags.append(
            f"WP ({wp}) >> SP ({sp}) â€” possible WP/SP swap? Double-check card positions.")
    
    # Health outlier detection
    if health and health > 14 and station not in ("Master", "Henchman"):
        result.hallucination_flags.append(
            f"health={health} very high for {station or 'non-station'} model â€” verify pip count")
    
    # Trigger count check â€” note for human review
    for act in actions:
        triggers = act.get("triggers", [])
        if len(triggers) > 4:
            result.hallucination_flags.append(
                f"Action '{act.get('name')}' has {len(triggers)} triggers â€” unusually high, verify")
    
    # Duplicate ability names
    ability_names = [a.get("name") for a in card.get("abilities", [])]
    dupes = [n for n in ability_names if ability_names.count(n) > 1]
    if dupes:
        result.hallucination_flags.append(f"Duplicate ability names: {set(dupes)}")
    
    # Duplicate action names
    action_names = [a.get("name") for a in actions]
    dupes = [n for n in action_names if action_names.count(n) > 1]
    if dupes:
        result.hallucination_flags.append(f"Duplicate action names: {set(dupes)}")
    
    # Check for merge warnings
    for w in card.get("merge_warnings", []):
        result.hallucination_flags.append(f"Merge warning: {w}")
    
    # Check extraction notes
    for n in card.get("extraction_notes", []):
        result.info.append(f"Extraction note: {n}")
    
    return result


def validate_crew_card(card: dict, ref: dict) -> ValidationResult:
    """Validate a crew card."""
    name = card.get("name", "Unknown")
    result = ValidationResult(f"[Crew] {name}")
    
    if not card.get("associated_master"):
        result.hard_violations.append("Missing associated_master")
    if not card.get("associated_title"):
        result.hard_violations.append("Missing associated_title")
    
    # Validate any granted actions
    for ka in card.get("keyword_actions", []):
        for act in ka.get("actions", []):
            if act.get("category") == "attack_actions" and not act.get("resist"):
                result.hard_violations.append(
                    f"Granted attack '{act.get('name')}' missing resist")
    
    return result


def validate_card(card: dict) -> ValidationResult:
    """Route to appropriate validator based on card type."""
    ref = load_reference()
    card_type = card.get("card_type", "stat_card")
    
    if card_type == "crew_card":
        return validate_crew_card(card, ref)
    else:
        return validate_stat_card(card, ref)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate M4E card JSON")
    parser.add_argument("input", nargs="+", help="Merged card JSON file(s)")
    parser.add_argument("--strict", action="store_true", help="Fail on soft rules too")
    parser.add_argument("--json-report", help="Write validation report to JSON")
    args = parser.parse_args()
    
    all_results = []
    
    for input_file in args.input:
        with open(input_file, encoding="utf-8") as f:
            card = json.load(f)
        
        result = validate_card(card)
        all_results.append(result)
        print(result.summary())
        print()
    
    # Summary
    passed = sum(1 for r in all_results if r.passed)
    review = sum(1 for r in all_results if r.needs_review)
    failed = sum(1 for r in all_results if not r.passed)
    
    print(f"{'='*50}")
    print(f"Total: {len(all_results)} | Passed: {passed} | Failed: {failed} | Needs Review: {review}")
    
    if args.json_report:
        report = {
            "summary": {"total": len(all_results), "passed": passed, "failed": failed, "needs_review": review},
            "results": [r.to_dict() for r in all_results],
        }
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Report written to {args.json_report}")
    
    sys.exit(0 if failed == 0 else 1)
