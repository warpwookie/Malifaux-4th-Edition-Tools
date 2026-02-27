#!/usr/bin/env python3
"""
fix_token_data.py — Token Data Cleanup & Standardization

Fixes inconsistencies in the M4E token data:
1. Renames orphaned short-name tokens in global registry
2. Adds missing tokens (Aura variants, crew-specific)
3. Populates rules_text for bare tokens
4. Standardizes crew_tokens text across crew cards
5. Rebuilds token_model_sources cross-references

Usage:
    python fix_token_data.py --dry-run    # Preview changes
    python fix_token_data.py --apply      # Apply changes
"""

import argparse
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "db" / "m4e.db"


# ============================================================
# STEP 2a: Rename orphaned short-name tokens
# ============================================================

RENAMES = {
    "Ego": "Fragile Ego",
    "Solid": "Frozen Solid",
    "Part": "Improvised Part",
    "Surge": "Aetheric Surge",
    # "Chains" -> delete (duplicate of "Spiritual Chains")
}

# "Chains" is a duplicate of "Spiritual Chains" which already exists
DUPLICATES_TO_DELETE = ["Chains"]

# "Blood" and "Spirit" are left as-is — "Blood" maps to Family keyword's
# Blood token (not New Blood), and "Spirit" maps to Ancestor keyword's
# Spirit token (not Bog Spirit). These are separate concepts.


# ============================================================
# STEP 2b: Missing tokens to add
# ============================================================

MISSING_TOKENS = [
    # Aura variants (type=debuff, timing=end_phase per rulebook)
    {"name": "Aura (Binding)", "type": "debuff", "timing": "end_phase",
     "rules_text": "Enemy models within 6\" may not empower duels. During the end phase, remove this token."},
    {"name": "Aura (Concealment)", "type": "debuff", "timing": "end_phase",
     "rules_text": "The area within 2\" of this model is concealing terrain. Friendly models may choose to be unaffected by this terrain. During the end phase, remove this token."},
    {"name": "Aura (Fire)", "type": "debuff", "timing": "end_phase",
     "rules_text": "The area within 2\" of this model is hazardous (Burning) terrain. Friendly models may choose to be unaffected by this terrain. During the end phase, remove this token."},
    {"name": "Aura (Fumes)", "type": "debuff", "timing": "end_phase",
     "rules_text": "Enemy models within 3\" receive a (-) to attack actions that target friendly models. During the end phase, remove this token."},
    {"name": "Aura (Hazardous)", "type": "debuff", "timing": "end_phase",
     "rules_text": "The area within 2\" of this model is hazardous terrain. Friendly models may choose to be unaffected by this terrain. During the end phase, remove this token."},
    {"name": "Aura (Negligent)", "type": "debuff", "timing": "end_phase",
     "rules_text": "Enemy models within 2\" of this model that declare a non-Walk action must pass a TN 10 Wp duel or the action fails. During the end phase, remove this token."},
    {"name": "Aura (Poison)", "type": "debuff", "timing": "end_phase",
     "rules_text": "The area within 2\" of this model is hazardous (Poison) terrain. Friendly models may choose to be unaffected by this terrain. During the end phase, remove this token."},
    {"name": "Aura (Staggered)", "type": "debuff", "timing": "end_phase",
     "rules_text": "When an enemy model within 2\" of this model activates, it must discard a card or gain a Staggered token."},
    # Crew-specific tokens
    {"name": "Bog Spirit", "type": "resource", "timing": "permanent",
     "rules_text": "After this model is killed, the crew that applied this token may summon a Will o' the Wisp with 3 health into base contact."},
    {"name": "New Blood", "type": "buff", "timing": "permanent",
     "rules_text": "This model gains the Family keyword."},
    {"name": "Interesting Parts", "type": "debuff", "timing": "permanent",
     "rules_text": "This model is affected by the enemy crew card as if it were a unique model allied to the enemy leader, but it may not affect or use power bars. This model considers enemy non-Scheme, non-Strategy markers to be friendly."},
]
# Note: Fragile Ego, Frozen Solid, Improvised Part, Aetheric Surge
# are covered by the renames in STEP 2a


# ============================================================
# STEP 2c: Populate rules_text for bare tokens
# ============================================================

# Canonical rules text from majority consensus across crew cards
# + rulebook definitions where available
RULES_TEXT_UPDATES = {
    "Adversary": "Friendly models receive a (+) to attack actions targeting this model. During the end phase, remove this token.",
    "Analyzed": "This model may not reduce damage with its abilities. Remove this token during the end phase.",
    "Bolstered": "This model receives +1 to its Df and Wp. During the end phase, remove this token. Canceled by Injured.",
    "Craven": "This model cannot declare the Interact action and is ignored for strategies and schemes. When this model ends its activation, remove this token.",
    "Distracted": "When this model targets a friendly model, it must remove this token and suffer a (-) to that action's duel. Canceled by Focused.",
    "Drift": "When this model activates, it may remove this token to place into base contact with a friendly Tide marker within 5\".",
    "Fast": "Increase this model's action limit by 1 (to a maximum of 3). When this model ends its activation, remove this token. Canceled by Slow.",
    "Focused": "Before performing a duel, this model may remove this token to receive a (+) to the duel. Canceled by Distracted.",
    "Hastened": "This model receives +2 Sp. When this model ends its activation, remove this token. Canceled by Staggered.",
    "Impact": "When this model succeeds in an attack action that deals damage, it must remove this token to deal +1 damage.",
    "Injured": "This model suffers -1 to its Df and Wp. During the end phase, remove this token. Canceled by Bolstered.",
    "Slow": "Reduce this model's action limit by 1 (to a minimum of 1). When this model ends its activation, remove this token. Canceled by Fast.",
    "Staggered": "This model suffers -2 Sp and cannot be moved by other enemy models. When this model ends its activation, remove this token. Canceled by Hastened.",
    "Stunned": "This model cannot declare triggers, and it counts all (t) symbols on its card as blank. When this model ends its activation, remove this token.",
    "Summon": "This model cannot declare the Interact action. This model does not infuse a (soulstone) for its crew when it is killed. This token cannot be removed.",
}


# ============================================================
# STEP 2d: Standardize crew_tokens text
# ============================================================

# Maps token name -> canonical text to apply across ALL crew cards
# Only for tokens where all crew cards SHOULD have the same text
CREW_TOKEN_CANONICAL_TEXT = {
    "Adaptable": "Before performing a duel, this model may remove this token to add a suit of its choice to its duel total.",
    "Adversary": "Friendly models receive a (+) to attack actions targeting this model. During the end phase, remove this token.",
    "Bolstered": "This model receives +1 to its Df and Wp. During the end phase, remove this token. Canceled by Injured.",
    "Burning": "During the end phase deal 1 damage to this model and enemy models in base contact with it. Then remove this token.",
    "Craven": "This model cannot declare the Interact action and is ignored for strategies and schemes. When this model ends its activation, remove this token.",
    "Distracted": "When this model targets a friendly model, it must remove this token and suffer a (-) to that action's duel. Canceled by Focused.",
    "Entranced": "This model's actions that target a friendly model cannot be cheated. After this model resolves an action targeting a friendly model, remove this token.",
    "Fast": "Increase this model's action limit by 1 (to a maximum of 3). When this model ends its activation, remove this token. Canceled by Slow.",
    "Focused": "Before performing a duel, this model may remove this token to receive a (+) to the duel. Canceled by Distracted.",
    "Hastened": "This model receives +2 Sp. When this model ends its activation, remove this token. Canceled by Staggered.",
    "Impact": "When this model succeeds in an attack action that deals damage, it must remove this token to deal +1 damage.",
    "Injured": "This model suffers -1 to its Df and Wp. During the end phase, remove this token. Canceled by Bolstered.",
    "Insight": "Before performing a duel, this model may remove this token to look at the top card of its fate deck and may discard it.",
    "Poison": "During the end phase, deal 1 irreducible damage to this model.",
    "Shielded": "When this model is dealt non-irreducible damage, it must remove this token to reduce that damage by 1. This token may reduce damage to 0.",
    "Slow": "Reduce this model's action limit by 1 (to a minimum of 1). When this model ends its activation, remove this token. Canceled by Fast.",
    "Staggered": "This model suffers -2 Sp and cannot be moved by other enemy models. When this model ends its activation, remove this token. Canceled by Hastened.",
    "Stunned": "This model cannot declare triggers, and it counts all (t) symbols on its card as blank. When this model ends its activation, remove this token.",
    "Summon": "This model cannot declare the Interact action. This model does not infuse a (soulstone) for its crew when it is killed. This token cannot be removed.",
}

# Tokens that intentionally vary per crew card — DO NOT standardize:
# Blight, Fright, Suppressed (different suits/effects per crew)
# Spiritual Chains (only 1 card, unique text)
# Aetheric Surge, Bog Spirit, Fragile Ego, Frozen Solid,
# Improvised Part, Interesting Parts, New Blood (crew-specific, 1-2 cards each)


# ============================================================
# STEP 2e: Rebuild token_model_sources
# ============================================================

def rebuild_token_model_sources(conn, dry_run=False):
    """Re-scan all models for token references and rebuild the cross-reference table."""
    c = conn.cursor()

    token_pattern = re.compile(r'\b([A-Z][a-z]+)\s+token')
    or_pattern = re.compile(r'\b([A-Z][a-z]+)\s+or\s+(?:a\s+|an\s+)?([A-Z][a-z]+)\s+token')

    if not dry_run:
        c.execute("DELETE FROM token_model_sources")

    # Build a cache of token name -> id
    c.execute("SELECT id, name FROM tokens")
    token_cache = {row[1]: row[0] for row in c.fetchall()}

    total_refs = 0
    models_with_refs = 0

    c.execute("SELECT id, name FROM models ORDER BY id")
    all_models = c.fetchall()

    for model_row in all_models:
        model_id = model_row[0]
        model_name = model_row[1]
        refs_for_model = []

        def scan_text(text, source_type, source_name):
            if not text:
                return
            for m in token_pattern.finditer(text):
                token_name = m.group(1)
                if token_name not in token_cache:
                    continue  # Don't create new stubs during rebuild
                context = text[max(0, m.start()-20):m.end()+10].lower()
                if any(w in context for w in ["gains", "gain", "receive", "apply"]):
                    rel = "applies"
                elif any(w in context for w in ["remove", "removing", "lose"]):
                    rel = "removes"
                else:
                    rel = "references"
                refs_for_model.append((token_cache[token_name], model_id, source_type, source_name, rel))
            for m in or_pattern.finditer(text):
                t1 = m.group(1)
                if t1 in token_cache:
                    refs_for_model.append((token_cache[t1], model_id, source_type, source_name, "applies"))

        # Read abilities
        c2 = conn.cursor()
        c2.execute("SELECT name, text FROM abilities WHERE model_id=?", (model_id,))
        for ab in c2.fetchall():
            scan_text(ab[1], "ability", ab[0])

        # Read action effects
        c2.execute("SELECT name, effects FROM actions WHERE model_id=?", (model_id,))
        for act in c2.fetchall():
            scan_text(act[1], "action_effect", act[0])

        # Read triggers
        c2.execute("""
            SELECT a.name as action_name, t.name as trigger_name, t.text
            FROM triggers t
            JOIN actions a ON t.action_id = a.id
            WHERE a.model_id=?
        """, (model_id,))
        for trig in c2.fetchall():
            scan_text(trig[2], "trigger", f"{trig[0]} > {trig[1]}")

        if refs_for_model:
            models_with_refs += 1
            total_refs += len(refs_for_model)
            if not dry_run:
                c.executemany("""
                    INSERT INTO token_model_sources
                    (token_id, model_id, source_type, source_name, applies_or_references)
                    VALUES (?,?,?,?,?)
                """, refs_for_model)

    return total_refs, models_with_refs


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Fix M4E token data inconsistencies")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview changes without modifying DB")
    group.add_argument("--apply", action="store_true", help="Apply all fixes to DB")
    args = parser.parse_args()

    dry_run = args.dry_run
    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"=== Token Data Cleanup ({mode}) ===\n")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    c = conn.cursor()

    # ---- STEP 2a: Rename orphaned short-name tokens ----
    print("--- Step 2a: Rename orphaned short-name tokens ---")
    for old_name, new_name in RENAMES.items():
        c.execute("SELECT id FROM tokens WHERE name=?", (old_name,))
        old_row = c.fetchone()
        c.execute("SELECT id FROM tokens WHERE name=?", (new_name,))
        new_row = c.fetchone()

        if old_row and not new_row:
            print(f"  RENAME: '{old_name}' -> '{new_name}'")
            if not dry_run:
                c.execute("UPDATE tokens SET name=? WHERE name=?", (new_name, old_name))
        elif old_row and new_row:
            # Both exist — merge: move token_model_sources from old to new, delete old
            print(f"  MERGE: '{old_name}' (id={old_row[0]}) into '{new_name}' (id={new_row[0]})")
            if not dry_run:
                c.execute("UPDATE token_model_sources SET token_id=? WHERE token_id=?",
                          (new_row[0], old_row[0]))
                c.execute("DELETE FROM tokens WHERE id=?", (old_row[0],))
        else:
            print(f"  SKIP: '{old_name}' not found in tokens table")

    for dup_name in DUPLICATES_TO_DELETE:
        c.execute("SELECT id FROM tokens WHERE name=?", (dup_name,))
        dup_row = c.fetchone()
        if dup_row:
            # Check if the full-name version exists
            c.execute("SELECT id FROM tokens WHERE name='Spiritual Chains'")
            full_row = c.fetchone()
            if full_row:
                print(f"  DELETE duplicate: '{dup_name}' (id={dup_row[0]}) — 'Spiritual Chains' exists (id={full_row[0]})")
                if not dry_run:
                    c.execute("UPDATE token_model_sources SET token_id=? WHERE token_id=?",
                              (full_row[0], dup_row[0]))
                    c.execute("DELETE FROM tokens WHERE id=?", (dup_row[0],))
            else:
                print(f"  RENAME: '{dup_name}' -> 'Spiritual Chains'")
                if not dry_run:
                    c.execute("UPDATE tokens SET name='Spiritual Chains' WHERE name=?", (dup_name,))
        else:
            print(f"  SKIP: '{dup_name}' not found")
    print()

    # ---- STEP 2b: Add missing tokens ----
    print("--- Step 2b: Add missing tokens ---")
    added = 0
    for token in MISSING_TOKENS:
        c.execute("SELECT id FROM tokens WHERE name=?", (token["name"],))
        if c.fetchone():
            print(f"  EXISTS: '{token['name']}' — skip")
            continue
        print(f"  ADD: '{token['name']}' (type={token.get('type')}, timing={token.get('timing')})")
        added += 1
        if not dry_run:
            c.execute("""
                INSERT INTO tokens (name, type, timing, rules_text)
                VALUES (?, ?, ?, ?)
            """, (token["name"], token.get("type"), token.get("timing"), token.get("rules_text")))
    print(f"  Total added: {added}")
    print()

    # ---- STEP 2c: Populate rules_text for bare tokens ----
    print("--- Step 2c: Populate rules_text for bare tokens ---")
    updated_rules = 0
    for name, text in RULES_TEXT_UPDATES.items():
        c.execute("SELECT id, rules_text FROM tokens WHERE name=?", (name,))
        row = c.fetchone()
        if not row:
            print(f"  NOT FOUND: '{name}' — skip")
            continue
        if row["rules_text"]:
            print(f"  HAS TEXT: '{name}' — skip (already has rules_text)")
            continue
        print(f"  UPDATE: '{name}' rules_text")
        updated_rules += 1
        if not dry_run:
            c.execute("UPDATE tokens SET rules_text=? WHERE name=?", (text, name))
    print(f"  Total updated: {updated_rules}")
    print()

    # ---- STEP 2d: Standardize crew_tokens text ----
    print("--- Step 2d: Standardize crew_tokens text ---")
    total_standardized = 0
    for token_name, canonical_text in CREW_TOKEN_CANONICAL_TEXT.items():
        c.execute("""
            SELECT COUNT(*) FROM crew_tokens
            WHERE name=? AND text != ?
        """, (token_name, canonical_text))
        non_canonical = c.fetchone()[0]
        if non_canonical > 0:
            c.execute("SELECT COUNT(*) FROM crew_tokens WHERE name=?", (token_name,))
            total = c.fetchone()[0]
            print(f"  STANDARDIZE: '{token_name}' — {non_canonical}/{total} rows need update")
            total_standardized += non_canonical
            if not dry_run:
                c.execute("""
                    UPDATE crew_tokens SET text=? WHERE name=? AND text != ?
                """, (canonical_text, token_name, canonical_text))
        else:
            c.execute("SELECT COUNT(*) FROM crew_tokens WHERE name=?", (token_name,))
            total = c.fetchone()[0]
            if total > 0:
                print(f"  OK: '{token_name}' — all {total} rows already canonical")
    print(f"  Total rows standardized: {total_standardized}")
    print()

    # ---- STEP 2e: Rebuild token_model_sources ----
    print("--- Step 2e: Rebuild token_model_sources ---")
    c.execute("SELECT COUNT(*) FROM token_model_sources")
    before_count = c.fetchone()[0]
    print(f"  Before: {before_count} references")
    total_refs, models_with_refs = rebuild_token_model_sources(conn, dry_run=dry_run)
    print(f"  After: {total_refs} references across {models_with_refs} models")
    print()

    # ---- Summary ----
    print("=" * 50)
    if dry_run:
        print("DRY RUN complete — no changes made.")
        print("Re-run with --apply to commit changes.")
    else:
        conn.commit()
        print("All changes committed to database.")

    # Final counts
    c.execute("SELECT COUNT(*) FROM tokens")
    token_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM tokens WHERE rules_text IS NULL OR rules_text = ''")
    null_rules = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM crew_tokens")
    crew_token_count = c.fetchone()[0]
    c.execute("""
        SELECT COUNT(DISTINCT ct.name) FROM crew_tokens ct
        LEFT JOIN tokens t ON ct.name = t.name
        WHERE t.id IS NULL
    """)
    missing_from_global = c.fetchone()[0]

    print(f"\n--- Final State ---")
    print(f"  Global tokens: {token_count}")
    print(f"  Tokens with NULL rules_text: {null_rules}")
    print(f"  Crew token rows: {crew_token_count}")
    print(f"  Crew tokens missing from global: {missing_from_global}")
    print(f"  Token model sources: {total_refs}")

    conn.close()


if __name__ == "__main__":
    main()
