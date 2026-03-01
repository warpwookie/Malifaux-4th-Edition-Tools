#!/usr/bin/env python3
"""Fix token data: M3E hallucinations, timing mismatches, AI-summarized rules text.

Issues found:
1. Poison rules_text is M3E (stacking/value mechanic)
2. Distracted/Entranced have wrong timing metadata
3. 20+ tokens have timing that contradicts their own rules text
4. 9 tokens have AI-generated summary text instead of actual game rules
5. Blood, Spirit, Research Bar tokens missing entirely
6. reference_data.json has M3E notes for Poison and Burning
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "m4e.db"
REF_PATH = Path(__file__).resolve().parent.parent / "reference" / "reference_data.json"


def fix_tokens_table(conn: sqlite3.Connection) -> list[str]:
    """Fix all token issues in the tokens table. Returns list of changes made."""
    changes = []
    c = conn.cursor()

    # ── 1. CRITICAL: Fix Poison M3E hallucination ──────────────────────
    # M3E had stacking tokens with values. M4E tokens don't stack.
    c.execute(
        "UPDATE tokens SET rules_text = ? WHERE name = 'Poison'",
        ("During the end phase, deal 1 irreducible damage to this model.",),
    )
    if c.rowcount:
        changes.append("Poison: fixed M3E stacking rules_text → correct M4E text")

    # Poison timing: 'never' is defensible since the token doesn't self-remove.
    # The damage triggers during end phase but the token persists.
    # Keep as 'never' per M4E rules (token stays until removed by another effect).

    # ── 2. Fix Distracted timing: end_activation → when_triggered ──────
    # PDF categorizes as "Remove When Triggered" — removed when targeting friendly
    c.execute(
        "UPDATE tokens SET timing = 'when_triggered' WHERE name = 'Distracted'",
    )
    if c.rowcount:
        changes.append("Distracted: timing end_activation → when_triggered")

    # ── 3. Fix Entranced timing: permanent → when_triggered ────────────
    # "After this model resolves an action targeting a friendly model, remove"
    c.execute(
        "UPDATE tokens SET timing = 'when_triggered' WHERE name = 'Entranced'",
    )
    if c.rowcount:
        changes.append("Entranced: timing permanent → when_triggered")

    # ── 4. Fix Spiritual Chains timing: on_use → when_triggered ────────
    # Forced removal on event (black joker), not voluntary use
    c.execute(
        "UPDATE tokens SET timing = 'when_triggered' WHERE name = 'Spiritual Chains'",
    )
    if c.rowcount:
        changes.append("Spiritual Chains: timing on_use → when_triggered")

    # ── 5. Fix tokens wrongly marked 'permanent' that have end_phase removal ──
    end_phase_fixes = {
        "Abandoned": None,  # "if this token did not damage this model, remove" during end phase
        "Analyzed": None,  # "Remove this token during the end phase"
        "Challenged": None,  # "During the end phase, remove this token"
        "Exposed": None,  # "During the end phase, remove this token"
        "Glowy": None,  # "During the end phase, remove this token"
        "Hidden": None,  # "During the end phase, remove this token"
        "Numb": None,  # "During the end phase, remove this token"
        "Paranoia": None,  # "During the end phase, must discard or remove"
        "Graft": None,  # "During the end phase, may remove to heal 2"
        "Blight": None,  # Conditional end_phase removal
    }
    for name in end_phase_fixes:
        c.execute(
            "UPDATE tokens SET timing = 'end_phase' WHERE name = ? AND timing != 'end_phase'",
            (name,),
        )
        if c.rowcount:
            changes.append(f"{name}: timing → end_phase")

    # ── 6. Fix tokens wrongly marked 'permanent' that have end_activation removal ──
    end_activation_fixes = ["Hunger", "Sin", "Shame"]
    for name in end_activation_fixes:
        c.execute(
            "UPDATE tokens SET timing = 'end_activation' WHERE name = ? AND timing != 'end_activation'",
            (name,),
        )
        if c.rowcount:
            changes.append(f"{name}: timing → end_activation")

    # ── 7. Fix tokens wrongly marked 'permanent' that are on_use ───────
    on_use_fixes = ["Backtrack", "Death", "Familia", "Life", "Replica", "Voyage"]
    for name in on_use_fixes:
        c.execute(
            "UPDATE tokens SET timing = 'on_use' WHERE name = ? AND timing != 'on_use'",
            (name,),
        )
        if c.rowcount:
            changes.append(f"{name}: timing → on_use")

    # ── 8. Fix Glutted: permanent → end_activation ────────────────────
    c.execute(
        "UPDATE tokens SET timing = 'end_activation' WHERE name = 'Glutted' AND timing != 'end_activation'",
    )
    if c.rowcount:
        changes.append("Glutted: timing → end_activation")

    # ── 9. Fix Incurable: permanent → end_phase ───────────────────────
    # Already covered above, but let's make sure
    c.execute(
        "UPDATE tokens SET timing = 'end_phase' WHERE name = 'Incurable' AND timing != 'end_phase'",
    )
    if c.rowcount:
        changes.append("Incurable: timing → end_phase")

    # ── 10. Fix Analyzed: NULL → end_phase ────────────────────────────
    c.execute(
        "UPDATE tokens SET timing = 'end_phase' WHERE name = 'Analyzed' AND timing IS NULL",
    )
    if c.rowcount:
        changes.append("Analyzed: timing NULL → end_phase")

    # ── 11. Fix AI-summarized rules text with actual crew_token text ──
    rules_fixes = {
        "Balm": "During the end phase, this model heals 1. Then, remove this token.",
        "Bounty": "When this model is killed, the crew that applied this token draws a card.",
        "Broodling": "After this model is killed, summon a friendly Terror Tot into base contact.",
        "Chi": "Before performing a duel, this model may remove this token to receive +1 to its duel total.",
        "Convert": "The Dmg stat of this model's attack actions is reduced by 1.",
        "Glutted": "When this model ends its activation, it may remove this token to heal 1.",
        "Greedy": "When this model would discard an upgrade, it may instead remove this token.",
        "Incurable": "This model cannot heal. During the end phase, remove this token.",
        "Parasite": "When this model is killed, the crew that applied this token infuses a (soulstone).",
    }
    for name, text in rules_fixes.items():
        c.execute(
            "UPDATE tokens SET rules_text = ? WHERE name = ?",
            (text, name),
        )
        if c.rowcount:
            changes.append(f"{name}: replaced AI-summary rules_text with actual card text")

    # ── 12. Fix Balm timing: on_use → end_phase ──────────────────────
    c.execute(
        "UPDATE tokens SET timing = 'end_phase' WHERE name = 'Balm' AND timing != 'end_phase'",
    )
    if c.rowcount:
        changes.append("Balm: timing on_use → end_phase")

    # ── 13. Fix Greedy timing ─────────────────────────────────────────
    # "When this model would discard an upgrade, it may instead remove this token"
    # This is event-triggered (forced by the discard event)
    c.execute(
        "UPDATE tokens SET timing = 'when_triggered' WHERE name = 'Greedy'",
    )
    if c.rowcount:
        changes.append("Greedy: timing → when_triggered")

    # ── 14. Add missing tokens ────────────────────────────────────────
    missing_tokens = [
        {
            "name": "Blood",
            "type": "resource",
            "timing": "permanent",
            "rules_text": "Crew-specific resource token. Effects vary by crew card. Used across multiple keywords for kill tracking and ability activation.",
            "cancels": None,
        },
        {
            "name": "Spirit",
            "type": "resource",
            "timing": "permanent",
            "rules_text": "Crew-specific resource token. Effects vary by crew card. Used across Ancestor, Oni, Swampfiend, and Urami keywords for spirit-themed abilities.",
            "cancels": None,
        },
        {
            "name": "Research Bar",
            "type": "resource",
            "timing": "permanent",
            "rules_text": "Crew-level bar (Seeker keyword) with 3 slots granting cumulative bonuses. Increased by resolving the Interact action near terrain.",
            "cancels": None,
        },
    ]
    for tok in missing_tokens:
        # Check if already exists
        existing = c.execute(
            "SELECT id FROM tokens WHERE name = ?", (tok["name"],)
        ).fetchone()
        if not existing:
            c.execute(
                "INSERT INTO tokens (name, type, timing, rules_text, cancels) VALUES (?, ?, ?, ?, ?)",
                (tok["name"], tok["type"], tok["timing"], tok["rules_text"], tok["cancels"]),
            )
            changes.append(f"{tok['name']}: added missing token")

    return changes


def fix_reference_data(ref_path: Path) -> list[str]:
    """Fix M3E hallucinations in reference_data.json."""
    changes = []
    with open(ref_path, encoding="utf-8") as f:
        data = json.load(f)

    tokens = data.get("tokens", {}).get("basic", {})

    # Fix Poison: remove M3E note, keep timing as 'never'
    if "Poison" in tokens:
        if "note" in tokens["Poison"]:
            old_note = tokens["Poison"]["note"]
            del tokens["Poison"]["note"]
            changes.append(f"reference_data.json: removed M3E Poison note: '{old_note}'")

    # Fix Burning: remove M3E note about stacking values
    if "Burning" in tokens:
        if "note" in tokens["Burning"]:
            old_note = tokens["Burning"]["note"]
            del tokens["Burning"]["note"]
            changes.append(f"reference_data.json: removed M3E Burning note: '{old_note}'")

    # Fix Distracted timing: end_activation → when_triggered
    if "Distracted" in tokens:
        if tokens["Distracted"].get("timing") != "when_triggered":
            old = tokens["Distracted"]["timing"]
            tokens["Distracted"]["timing"] = "when_triggered"
            changes.append(f"reference_data.json: Distracted timing {old} → when_triggered")

    # Add cancellation pairs that are missing
    pairs = data.get("tokens", {}).get("cancellation_pairs", [])
    existing_pairs = {tuple(sorted(p)) for p in pairs}

    missing_pairs = [
        ["Bolstered", "Injured"],
        ["Hastened", "Staggered"],
        ["Hidden", "Exposed"],
        ["Fast", "Slow"],  # already exists
        ["Focused", "Stunned"],  # already exists — but note: Focused cancels Distracted too
    ]
    for pair in missing_pairs:
        key = tuple(sorted(pair))
        if key not in existing_pairs:
            pairs.append(pair)
            existing_pairs.add(key)
            changes.append(f"reference_data.json: added cancellation pair {pair}")

    data["tokens"]["cancellation_pairs"] = pairs

    with open(ref_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return changes


def main():
    print("=" * 60)
    print("M4E Token Data Fix Script")
    print("=" * 60)

    # Fix database
    print("\n── Fixing tokens table in DB ──")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    db_changes = fix_tokens_table(conn)
    conn.commit()

    for c in db_changes:
        print(f"  ✓ {c}")
    print(f"\n  Total DB changes: {len(db_changes)}")

    # Verify the fixes
    print("\n── Verifying critical fixes ──")
    for name in ["Poison", "Distracted", "Entranced"]:
        row = conn.execute("SELECT * FROM tokens WHERE name = ?", (name,)).fetchone()
        print(f"  {name}: timing={row['timing']}, rules={row['rules_text'][:80]}...")

    conn.close()

    # Fix reference_data.json
    print("\n── Fixing reference_data.json ──")
    ref_changes = fix_reference_data(REF_PATH)
    for c in ref_changes:
        print(f"  ✓ {c}")
    print(f"\n  Total reference_data changes: {len(ref_changes)}")

    print("\n" + "=" * 60)
    print(f"Total changes: {len(db_changes) + len(ref_changes)}")
    print("\nNext steps:")
    print("  1. Run: python scripts/denormalize.py")
    print("  2. Run: python final_audit.py --verbose")
    print("=" * 60)


if __name__ == "__main__":
    main()
