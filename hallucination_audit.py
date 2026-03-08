#!/usr/bin/env python3
"""
Comprehensive hallucination detection audit for M4E database.
Checks for data integrity issues, impossible values, suspicious text patterns,
cross-reference integrity, and potential fabricated data.
"""

import sqlite3
import re
from collections import defaultdict, Counter
from pathlib import Path

DB_PATH = Path("db/m4e.db")

# Valid enums
VALID_FACTIONS = {"Guild", "Arcanists", "Neverborn", "Bayou", "Outcasts",
                  "Resurrectionists", "Ten Thunders", "Explorer's Society"}
VALID_STATIONS = {"Master", "Henchman", "Minion", "Peon", "Totem"}
VALID_TRIGGER_TIMINGS = {"after_succeeding", "when_resolving", "after_failing", "after_resolving"}
VALID_RESIST_STATS = {"Df", "Wp", "Mv"}
VALID_SUITS = {"(r)", "(c)", "(m)", "(t)"}
VALID_TOKENS = {"Adversary", "Bolstered", "Burning", "Craven", "Distracted",
                "Exposed", "Fast", "Focused", "Hastened", "Hidden", "Impact",
                "Injured", "Poison", "Shielded", "Slow", "Staggered", "Stunned", "Summon"}

# Edge cases (verified models with unusual stats)
VERIFIED_EDGE_CASES = {
    "Clockwork Trap": {"wp": 0},
    "Marathine": {"health": 0},
    "Camerabot": {"sz": 0},
    "Voodoo Doll": {"sz": 0},
    "Gupps": {"sz": 0},
    "Ashen Core": {"sp": 0},
    "Last Bite": {"sp": 0},
    "Sunless Self": {"sp": 9},
}


def connect_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def print_section(title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")


def print_finding(severity, message):
    print(f"  [{severity}] {message}")


def audit_duplicate_abilities(conn):
    """Check 1: Duplicate abilities/actions/triggers across models."""
    print_section("1. DUPLICATE ABILITIES / ACTIONS / TRIGGERS")
    cur = conn.cursor()
    findings = 0

    # Duplicate abilities: same name+text on different models
    cur.execute("""
        SELECT a.name, a.text, COUNT(DISTINCT a.model_id) as model_count,
               GROUP_CONCAT(DISTINCT m.name) as models
        FROM abilities a
        JOIN models m ON a.model_id = m.id
        WHERE a.text IS NOT NULL AND a.text != ''
        GROUP BY a.name, a.text
        HAVING COUNT(DISTINCT a.model_id) > 1
        ORDER BY model_count DESC
    """)
    rows = cur.fetchall()

    # Filter: common shared abilities (appearing on 5+ models) are normal game design
    common_threshold = 5
    unusual_dupes = [r for r in rows if r['model_count'] < common_threshold]
    common_dupes = [r for r in rows if r['model_count'] >= common_threshold]

    if common_dupes:
        print(f"\n  --- Common shared abilities ({common_threshold}+ models, expected) ---")
        for r in common_dupes[:10]:
            model_list = r['models']
            if len(model_list) > 100:
                model_list = model_list[:100] + "..."
            print_finding("INFO", f"Ability '{r['name']}' shared by {r['model_count']} models: {model_list}")

    if unusual_dupes:
        print(f"\n  --- Unusual duplicates (2-{common_threshold-1} models, review) ---")
        for r in unusual_dupes:
            print_finding("INFO", f"Ability '{r['name']}' on {r['model_count']} models: {r['models']}")
        findings += len(unusual_dupes)
    else:
        print("\n  No unusual duplicate abilities found.")

    # Duplicate actions: same name+effects on different models
    cur.execute("""
        SELECT ac.name, ac.effects, COUNT(DISTINCT ac.model_id) as model_count,
               GROUP_CONCAT(DISTINCT m.name) as models
        FROM actions ac
        JOIN models m ON ac.model_id = m.id
        WHERE ac.effects IS NOT NULL AND ac.effects != ''
        GROUP BY ac.name, ac.effects
        HAVING COUNT(DISTINCT ac.model_id) > 1
        ORDER BY model_count DESC
    """)
    rows = cur.fetchall()
    unusual_action_dupes = [r for r in rows if r['model_count'] < common_threshold]
    common_action_dupes = [r for r in rows if r['model_count'] >= common_threshold]

    if common_action_dupes:
        print(f"\n  --- Common shared actions ({common_threshold}+ models, expected) ---")
        for r in common_action_dupes[:10]:
            model_list = r['models']
            if len(model_list) > 100:
                model_list = model_list[:100] + "..."
            print_finding("INFO", f"Action '{r['name']}' shared by {r['model_count']} models: {model_list}")

    if unusual_action_dupes:
        print(f"\n  --- Unusual action duplicates (2-{common_threshold-1} models) ---")
        for r in unusual_action_dupes[:20]:
            print_finding("INFO", f"Action '{r['name']}' on {r['model_count']} models: {r['models']}")

    return findings


def audit_stat_values(conn):
    """Check 2: Impossible stat values."""
    print_section("2. IMPOSSIBLE STAT VALUES")
    cur = conn.cursor()
    findings = 0

    stat_ranges = {
        'df': (2, 8, 'Df'),
        'wp': (0, 8, 'Wp'),
        'sz': (0, 6, 'Sz'),
        'sp': (0, 9, 'Sp'),
        'health': (0, 16, 'Health'),
    }

    cur.execute("SELECT * FROM models")
    models = cur.fetchall()

    for model in models:
        name = model['name']
        for col, (lo, hi, label) in stat_ranges.items():
            val = model[col]
            if val is None:
                continue
            try:
                v = int(val)
            except (ValueError, TypeError):
                print_finding("ERROR", f"Model '{name}': {label} = '{val}' (non-numeric)")
                findings += 1
                continue

            if v < lo or v > hi:
                # Check if this is a verified edge case
                if name in VERIFIED_EDGE_CASES and col in VERIFIED_EDGE_CASES[name]:
                    if VERIFIED_EDGE_CASES[name][col] == v:
                        print_finding("INFO", f"Model '{name}': {label} = {v} (verified edge case)")
                        continue
                print_finding("ERROR", f"Model '{name}': {label} = {v} (valid range: {lo}-{hi})")
                findings += 1

        # Cost check
        cost = model['cost']
        if cost is not None and cost != '-':
            try:
                c = int(cost)
                if c < 0 or c > 15:
                    print_finding("ERROR", f"Model '{name}': cost = {c} (valid range: 0-15 or '-')")
                    findings += 1
            except (ValueError, TypeError):
                print_finding("ERROR", f"Model '{name}': cost = '{cost}' (non-numeric and not '-')")
                findings += 1

    if findings == 0:
        print("  No impossible stat values found.")

    return findings


def audit_suspicious_text(conn):
    """Check 3: Suspicious text patterns in ability/action descriptions."""
    print_section("3. SUSPICIOUS TEXT PATTERNS")
    cur = conn.cursor()
    findings = 0

    # Check abilities
    cur.execute("""
        SELECT a.id, a.name, a.text, m.name as model_name
        FROM abilities a
        JOIN models m ON a.model_id = m.id
    """)
    abilities = cur.fetchall()

    # Check actions
    cur.execute("""
        SELECT ac.id, ac.name, ac.effects, m.name as model_name
        FROM actions ac
        JOIN models m ON ac.model_id = m.id
    """)
    actions = cur.fetchall()

    # Check triggers
    cur.execute("""
        SELECT t.id, t.name, t.text, ac.name as action_name, m.name as model_name
        FROM triggers t
        JOIN actions ac ON t.action_id = ac.id
        JOIN models m ON ac.model_id = m.id
    """)
    triggers = cur.fetchall()

    # -- Page number references --
    page_ref_pattern = re.compile(r'(?:page\s+\d+|see\s+page|pg\.\s*\d+|p\.\s*\d+)', re.IGNORECASE)

    # -- "example" or "note:" patterns --
    commentary_pattern = re.compile(r'\b(?:example|note:|for\s+example|e\.g\.|i\.e\.)\b', re.IGNORECASE)

    # -- Parenthetical citations --
    citation_pattern = re.compile(r'\((?:see|refer|cf\.)\s', re.IGNORECASE)

    print("\n  --- Abilities ---")

    null_or_empty_abilities = 0
    short_abilities = []
    long_abilities = []
    page_ref_abilities = []
    commentary_abilities = []

    for ab in abilities:
        text = ab['text']
        if text is None or text.strip() == '':
            null_or_empty_abilities += 1
            continue
        if len(text) < 10:
            short_abilities.append((ab['model_name'], ab['name'], text))
        if len(text) > 500:
            long_abilities.append((ab['model_name'], ab['name'], len(text)))
        if page_ref_pattern.search(text):
            page_ref_abilities.append((ab['model_name'], ab['name'], text[:100]))
        if commentary_pattern.search(text):
            commentary_abilities.append((ab['model_name'], ab['name'], text[:100]))

    if null_or_empty_abilities:
        print_finding("WARNING", f"{null_or_empty_abilities} abilities with NULL or empty text")
        findings += null_or_empty_abilities

    if short_abilities:
        print_finding("WARNING", f"{len(short_abilities)} abilities with very short text (<10 chars):")
        for model, name, text in short_abilities[:15]:
            print(f"           {model} -> '{name}': \"{text}\"")
        findings += len(short_abilities)

    if long_abilities:
        print_finding("INFO", f"{len(long_abilities)} abilities with very long text (>500 chars):")
        for model, name, length in long_abilities[:15]:
            print(f"           {model} -> '{name}': {length} chars")

    if page_ref_abilities:
        print_finding("ERROR", f"{len(page_ref_abilities)} abilities with page number references:")
        for model, name, text in page_ref_abilities:
            print(f"           {model} -> '{name}': \"{text}\"")
        findings += len(page_ref_abilities)

    if commentary_abilities:
        print_finding("WARNING", f"{len(commentary_abilities)} abilities with commentary patterns:")
        for model, name, text in commentary_abilities[:15]:
            print(f"           {model} -> '{name}': \"{text}\"")
        findings += len(commentary_abilities)

    print("\n  --- Actions ---")

    null_or_empty_actions = 0
    short_actions = []
    long_actions = []
    page_ref_actions = []
    commentary_actions = []

    for ac in actions:
        text = ac['effects']
        if text is None or text.strip() == '':
            null_or_empty_actions += 1
            continue
        if len(text) < 10:
            short_actions.append((ac['model_name'], ac['name'], text))
        if len(text) > 500:
            long_actions.append((ac['model_name'], ac['name'], len(text)))
        if page_ref_pattern.search(text):
            page_ref_actions.append((ac['model_name'], ac['name'], text[:100]))
        if commentary_pattern.search(text):
            commentary_actions.append((ac['model_name'], ac['name'], text[:100]))

    if null_or_empty_actions:
        print_finding("INFO", f"{null_or_empty_actions} actions with NULL or empty effects (may be valid for simple attacks)")

    if short_actions:
        print_finding("WARNING", f"{len(short_actions)} actions with very short effects (<10 chars):")
        for model, name, text in short_actions[:15]:
            print(f"           {model} -> '{name}': \"{text}\"")
        findings += len(short_actions)

    if long_actions:
        print_finding("INFO", f"{len(long_actions)} actions with very long effects (>500 chars):")
        for model, name, length in long_actions[:15]:
            print(f"           {model} -> '{name}': {length} chars")

    if page_ref_actions:
        print_finding("ERROR", f"{len(page_ref_actions)} actions with page number references:")
        for model, name, text in page_ref_actions:
            print(f"           {model} -> '{name}': \"{text}\"")
        findings += len(page_ref_actions)

    if commentary_actions:
        print_finding("WARNING", f"{len(commentary_actions)} actions with commentary patterns:")
        for model, name, text in commentary_actions[:15]:
            print(f"           {model} -> '{name}': \"{text}\"")
        findings += len(commentary_actions)

    print("\n  --- Triggers ---")

    null_or_empty_triggers = 0
    short_triggers = []
    page_ref_triggers = []

    for tr in triggers:
        text = tr['text']
        if text is None or text.strip() == '':
            null_or_empty_triggers += 1
            continue
        if len(text) < 10:
            short_triggers.append((tr['model_name'], tr['action_name'], tr['name'], text))
        if page_ref_pattern.search(text):
            page_ref_triggers.append((tr['model_name'], tr['name'], text[:100]))

    if null_or_empty_triggers:
        print_finding("WARNING", f"{null_or_empty_triggers} triggers with NULL or empty text")
        findings += null_or_empty_triggers

    if short_triggers:
        print_finding("WARNING", f"{len(short_triggers)} triggers with very short text (<10 chars):")
        for model, action, name, text in short_triggers[:15]:
            print(f"           {model} -> {action} -> '{name}': \"{text}\"")
        findings += len(short_triggers)

    if page_ref_triggers:
        print_finding("ERROR", f"{len(page_ref_triggers)} triggers with page number references:")
        for model, name, text in page_ref_triggers:
            print(f"           {model} -> '{name}': \"{text}\"")
        findings += len(page_ref_triggers)

    if not any([null_or_empty_abilities, short_abilities, long_abilities,
                page_ref_abilities, commentary_abilities,
                null_or_empty_actions, short_actions, long_actions,
                page_ref_actions, commentary_actions,
                null_or_empty_triggers, short_triggers, page_ref_triggers]):
        print("  No suspicious text patterns found.")

    return findings


def audit_cross_references(conn):
    """Check 4: Cross-reference integrity."""
    print_section("4. CROSS-REFERENCE INTEGRITY")
    cur = conn.cursor()
    findings = 0

    # 4a. Models with 0 abilities AND 0 actions
    cur.execute("""
        SELECT m.id, m.name, m.faction, m.station
        FROM models m
        WHERE NOT EXISTS (SELECT 1 FROM abilities a WHERE a.model_id = m.id)
          AND NOT EXISTS (SELECT 1 FROM actions ac WHERE ac.model_id = m.id)
    """)
    no_data_models = cur.fetchall()
    if no_data_models:
        print_finding("WARNING", f"{len(no_data_models)} models with 0 abilities AND 0 actions:")
        for m in no_data_models:
            print(f"           {m['name']} ({m['faction']}, station={m['station']})")
        findings += len(no_data_models)
    else:
        print("  All models have at least one ability or action.")

    # 4b. Models referenced in crew_cards.associated_master that don't exist
    cur.execute("""
        SELECT DISTINCT cc.associated_master
        FROM crew_cards cc
        WHERE cc.associated_master IS NOT NULL
          AND cc.associated_master != ''
          AND cc.associated_master NOT IN (SELECT name FROM models)
          AND cc.associated_master NOT IN (SELECT COALESCE(title, '') FROM models)
    """)
    missing_masters = cur.fetchall()
    if missing_masters:
        print_finding("WARNING", f"{len(missing_masters)} crew card masters not found in models table:")
        for m in missing_masters:
            print(f"           '{m['associated_master']}'")
        findings += len(missing_masters)
    else:
        print("  All crew card masters found in models table.")

    # 4c. Keywords in model_keywords not associated with any crew card keyword
    cur.execute("""
        SELECT DISTINCT mk.keyword, COUNT(DISTINCT mk.model_id) as model_count
        FROM model_keywords mk
        GROUP BY mk.keyword
        ORDER BY mk.keyword
    """)
    all_keywords = cur.fetchall()
    print(f"\n  Total distinct keywords in model_keywords: {len(all_keywords)}")

    # 4d. Triggers referencing non-existent actions (orphan triggers)
    cur.execute("""
        SELECT t.id, t.name, t.action_id
        FROM triggers t
        WHERE t.action_id NOT IN (SELECT id FROM actions)
    """)
    orphan_triggers = cur.fetchall()
    if orphan_triggers:
        print_finding("ERROR", f"{len(orphan_triggers)} triggers reference non-existent actions:")
        for t in orphan_triggers:
            print(f"           Trigger '{t['name']}' (id={t['id']}) -> action_id={t['action_id']}")
        findings += len(orphan_triggers)
    else:
        print("  No orphan triggers found.")

    # 4e. Models with crew_card_name that don't match any crew card
    cur.execute("""
        SELECT m.name, m.crew_card_name, m.faction
        FROM models m
        WHERE m.crew_card_name IS NOT NULL
          AND m.crew_card_name != ''
          AND m.crew_card_name != '-'
    """)
    models_with_crew = cur.fetchall()

    cur.execute("SELECT name FROM crew_cards")
    crew_card_names = {r['name'] for r in cur.fetchall()}

    unmatched_crew = []
    for m in models_with_crew:
        # crew_card_name can contain " / " separated values
        card_names = [n.strip() for n in m['crew_card_name'].split('/')]
        for cn in card_names:
            cn_clean = cn.strip()
            if cn_clean and cn_clean not in crew_card_names:
                # Try case-insensitive and smart-quote normalization
                cn_normalized = cn_clean.replace('\u2019', "'").replace('\u2018', "'")
                found = False
                for cc_name in crew_card_names:
                    cc_normalized = cc_name.replace('\u2019', "'").replace('\u2018', "'")
                    if cn_normalized.lower() == cc_normalized.lower():
                        found = True
                        break
                if not found:
                    unmatched_crew.append((m['name'], cn_clean, m['faction']))

    if unmatched_crew:
        print_finding("WARNING", f"{len(unmatched_crew)} model crew_card_names not matching any crew card:")
        for name, cc, faction in unmatched_crew[:20]:
            print(f"           {name} ({faction}) -> '{cc}'")
        findings += len(unmatched_crew)
    else:
        print("  All model crew_card_names match a crew card.")

    # 4f. Check for models where totem field references non-existent model
    cur.execute("""
        SELECT m.name, m.totem, m.faction
        FROM models m
        WHERE m.totem IS NOT NULL
          AND m.totem != ''
          AND m.totem != '-'
    """)
    totem_refs = cur.fetchall()
    unmatched_totems = []
    for m in totem_refs:
        totem_name = m['totem']
        # Strip model limit like "(2)" from end
        totem_clean = re.sub(r'\s*\(\d+\)\s*$', '', totem_name).strip()
        cur.execute("SELECT COUNT(*) as cnt FROM models WHERE name = ?", (totem_clean,))
        if cur.fetchone()['cnt'] == 0:
            # Try fuzzy
            cur.execute("SELECT COUNT(*) as cnt FROM models WHERE name LIKE ?", (totem_clean,))
            if cur.fetchone()['cnt'] == 0:
                unmatched_totems.append((m['name'], totem_name, m['faction']))

    if unmatched_totems:
        print_finding("WARNING", f"{len(unmatched_totems)} totem references not found in models table:")
        for name, totem, faction in unmatched_totems:
            print(f"           {name} ({faction}) -> totem='{totem}'")
        findings += len(unmatched_totems)
    else:
        print("  All totem references found in models table.")

    return findings


def audit_fabricated_data(conn):
    """Check 5: Data that seems fabricated."""
    print_section("5. FABRICATED DATA CHECKS")
    cur = conn.cursor()
    findings = 0

    # 5a. Invalid resist stats on actions
    cur.execute("""
        SELECT ac.id, ac.name, ac.resist, ac.category, m.name as model_name
        FROM actions ac
        JOIN models m ON ac.model_id = m.id
        WHERE ac.resist IS NOT NULL AND ac.resist != ''
    """)
    actions_with_resist = cur.fetchall()
    invalid_resist = []
    for ac in actions_with_resist:
        resist = ac['resist'].strip()
        if resist not in VALID_RESIST_STATS:
            invalid_resist.append((ac['model_name'], ac['name'], resist, ac['category']))

    if invalid_resist:
        print_finding("ERROR", f"{len(invalid_resist)} actions with invalid resist stat:")
        for model, action, resist, cat in invalid_resist:
            print(f"           {model} -> '{action}' ({cat}): resist='{resist}'")
        findings += len(invalid_resist)
    else:
        print("  All action resist stats are valid (Df, Wp, Mv).")

    # 5b. Invalid trigger timings
    cur.execute("""
        SELECT t.id, t.name, t.timing, ac.name as action_name, m.name as model_name
        FROM triggers t
        JOIN actions ac ON t.action_id = ac.id
        JOIN models m ON ac.model_id = m.id
        WHERE t.timing IS NOT NULL AND t.timing != ''
    """)
    all_triggers = cur.fetchall()
    invalid_timings = []
    for t in all_triggers:
        if t['timing'] not in VALID_TRIGGER_TIMINGS:
            invalid_timings.append((t['model_name'], t['action_name'], t['name'], t['timing']))

    if invalid_timings:
        print_finding("ERROR", f"{len(invalid_timings)} triggers with invalid timing:")
        for model, action, trigger, timing in invalid_timings:
            print(f"           {model} -> {action} -> '{trigger}': timing='{timing}'")
        findings += len(invalid_timings)
    else:
        print("  All trigger timings are valid.")

    # 5c. Invalid trigger suit values
    cur.execute("""
        SELECT t.id, t.name, t.suit, ac.name as action_name, m.name as model_name
        FROM triggers t
        JOIN actions ac ON t.action_id = ac.id
        JOIN models m ON ac.model_id = m.id
        WHERE t.suit IS NOT NULL AND t.suit != ''
    """)
    all_trigger_suits = cur.fetchall()
    invalid_suits = []
    suit_pattern = re.compile(r'^(\((?:r|c|m|t)\)\s*)+$')
    for t in all_trigger_suits:
        suit_val = t['suit'].strip()
        if not suit_pattern.match(suit_val + ' '):
            # Try individual suit check
            individual_suits = re.findall(r'\([rcmt]\)', suit_val)
            remaining = suit_val
            for s in individual_suits:
                remaining = remaining.replace(s, '', 1)
            remaining = remaining.strip()
            if remaining:
                invalid_suits.append((t['model_name'], t['action_name'], t['name'], suit_val))

    if invalid_suits:
        print_finding("ERROR", f"{len(invalid_suits)} triggers with invalid suit values:")
        for model, action, trigger, suit in invalid_suits[:20]:
            print(f"           {model} -> {action} -> '{trigger}': suit='{suit}'")
        findings += len(invalid_suits)
    else:
        print("  All trigger suit values are valid.")

    # 5d. NULL or empty trigger suits
    cur.execute("""
        SELECT t.id, t.name, t.suit, ac.name as action_name, m.name as model_name
        FROM triggers t
        JOIN actions ac ON t.action_id = ac.id
        JOIN models m ON ac.model_id = m.id
        WHERE t.suit IS NULL OR t.suit = ''
    """)
    null_suit_triggers = cur.fetchall()
    if null_suit_triggers:
        print_finding("WARNING", f"{len(null_suit_triggers)} triggers with NULL/empty suit:")
        for t in null_suit_triggers[:15]:
            print(f"           {t['model_name']} -> {t['action_name']} -> '{t['name']}': suit='{t['suit']}'")
        findings += len(null_suit_triggers)
    else:
        print("  No triggers with NULL/empty suits.")

    # 5e. Station/cost mismatches
    cur.execute("""
        SELECT name, station, cost, faction
        FROM models
        WHERE station IS NOT NULL
    """)
    station_models = cur.fetchall()
    station_cost_issues = []
    for m in station_models:
        station = m['station']
        cost = m['cost']

        if station == 'Master' and cost != '-':
            station_cost_issues.append((m['name'], station, cost, "Master should have cost='-'"))
        elif station == 'Totem' and cost is not None and cost != '-':
            # Effigy totems have cost=2, that's OK
            if 'Effigy' not in m['name']:
                try:
                    c = int(cost)
                    if c > 2:
                        station_cost_issues.append((m['name'], station, cost, "Totem with unusual cost"))
                except (ValueError, TypeError):
                    pass
        elif station in ('Minion', 'Peon', 'Henchman') and cost == '-':
            station_cost_issues.append((m['name'], station, cost, f"{station} with cost='-' is unusual"))

    if station_cost_issues:
        print_finding("WARNING", f"{len(station_cost_issues)} station/cost mismatches:")
        for name, station, cost, note in station_cost_issues:
            print(f"           {name}: station={station}, cost={cost} ({note})")
        findings += len(station_cost_issues)
    else:
        print("  No station/cost mismatches.")

    # 5f. Models with cost but no station, or station but NULL cost
    cur.execute("""
        SELECT name, station, cost, faction
        FROM models
        WHERE (station IS NOT NULL AND cost IS NULL)
    """)
    missing_cost = cur.fetchall()
    if missing_cost:
        print_finding("WARNING", f"{len(missing_cost)} models with station but NULL cost:")
        for m in missing_cost[:15]:
            print(f"           {m['name']} ({m['faction']}): station={m['station']}, cost=NULL")
        findings += len(missing_cost)

    # 5g. Invalid faction values
    cur.execute("SELECT DISTINCT faction FROM models")
    db_factions = {r['faction'] for r in cur.fetchall()}
    invalid_factions = db_factions - VALID_FACTIONS
    if invalid_factions:
        print_finding("ERROR", f"Invalid factions found: {invalid_factions}")
        findings += len(invalid_factions)
    else:
        print(f"  All factions valid: {sorted(db_factions)}")

    # 5h. Invalid station values
    cur.execute("SELECT DISTINCT station FROM models WHERE station IS NOT NULL")
    db_stations = {r['station'] for r in cur.fetchall()}
    invalid_stations = db_stations - VALID_STATIONS
    if invalid_stations:
        print_finding("ERROR", f"Invalid stations found: {invalid_stations}")
        findings += len(invalid_stations)
    else:
        print(f"  All stations valid: {sorted(db_stations)}")

    # 5i. Attack actions without resist
    cur.execute("""
        SELECT ac.name, ac.category, m.name as model_name
        FROM actions ac
        JOIN models m ON ac.model_id = m.id
        WHERE ac.category = 'attack_actions'
          AND (ac.resist IS NULL OR ac.resist = '')
    """)
    attack_no_resist = cur.fetchall()
    if attack_no_resist:
        print_finding("WARNING", f"{len(attack_no_resist)} attack actions without resist stat:")
        for a in attack_no_resist[:15]:
            print(f"           {a['model_name']} -> '{a['name']}'")
        findings += len(attack_no_resist)
    else:
        print("  All attack actions have resist stats.")

    return findings


def audit_token_references(conn):
    """Check 6: Token references in text that reference non-existent tokens."""
    print_section("6. TOKEN REFERENCE AUDIT")
    cur = conn.cursor()
    findings = 0

    # Build a pattern to find capitalized words that look like token names
    # We'll search for known token pattern + potential unknown tokens
    token_condition_pattern = re.compile(
        r'\b(?:gains?|receives?|suffers?|has|gives?|applies|apply|applies?|'
        r'remove|removes?|removing|with|the|a)\s+(?:the\s+)?'
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*'
        r'(?:Condition|Token|condition|token)',
        re.IGNORECASE
    )

    # Also check for direct "+X Token" patterns
    direct_token_pattern = re.compile(
        r'(?:the\s+)?([A-Z][a-z]+)\s+(?:Condition|Token)',
        re.IGNORECASE
    )

    # Gather all text from abilities, actions, triggers
    cur.execute("""
        SELECT 'ability' as source, a.name, a.text as content, m.name as model_name
        FROM abilities a JOIN models m ON a.model_id = m.id
        WHERE a.text IS NOT NULL AND a.text != ''
        UNION ALL
        SELECT 'action' as source, ac.name, ac.effects as content, m.name as model_name
        FROM actions ac JOIN models m ON ac.model_id = m.id
        WHERE ac.effects IS NOT NULL AND ac.effects != ''
        UNION ALL
        SELECT 'trigger' as source, t.name, t.text as content, m.name as model_name
        FROM triggers t
        JOIN actions ac ON t.action_id = ac.id
        JOIN models m ON ac.model_id = m.id
        WHERE t.text IS NOT NULL AND t.text != ''
    """)
    all_text = cur.fetchall()

    # Also check the tokens table itself
    cur.execute("SELECT name FROM tokens")
    db_tokens = {r['name'] for r in cur.fetchall()}

    unknown_tokens = defaultdict(list)
    for row in all_text:
        content = row['content']
        matches = direct_token_pattern.findall(content)
        for match in matches:
            token_name = match.strip()
            # Normalize
            if token_name.lower() in {t.lower() for t in VALID_TOKENS}:
                continue
            if token_name.lower() in {t.lower() for t in db_tokens}:
                continue
            # Skip common false positives
            if token_name.lower() in {'this', 'that', 'their', 'target', 'other',
                                       'another', 'enemy', 'friendly', 'model',
                                       'action', 'ability', 'trigger', 'activation',
                                       'general', 'terrain', 'marker', 'card',
                                       'soulstone', 'death', 'pass', 'suffer',
                                       'move', 'place', 'push', 'remove', 'gain',
                                       'bonus', 'control', 'health', 'range',
                                       'generated', 'master', 'crew', 'base',
                                       'hand', 'flip', 'duel', 'fate', 'severe',
                                       'moderate', 'weak', 'critical', 'black',
                                       'joker', 'damage', 'healing', 'pulse',
                                       'aura', 'blast', 'simple', 'complex',
                                       'once', 'per', 'each', 'all', 'any',
                                       'may', 'must', 'cannot', 'instead',
                                       'water', 'blood', 'pyre', 'corpse',
                                       'scrap', 'scheme', 'strategy', 'ice',
                                       'poison', 'none', 'same', 'your',
                                       'attached', 'within', 'ending'}:
                continue
            unknown_tokens[token_name].append(
                f"{row['model_name']} -> {row['source']} '{row['name']}'"
            )

    if unknown_tokens:
        print_finding("WARNING", f"{len(unknown_tokens)} potentially unknown token names found:")
        for token, refs in sorted(unknown_tokens.items()):
            print(f"           '{token}' referenced in {len(refs)} places:")
            for ref in refs[:3]:
                print(f"             - {ref}")
            if len(refs) > 3:
                print(f"             ... and {len(refs)-3} more")
        findings += len(unknown_tokens)
    else:
        print("  No references to unknown tokens found.")

    # Check db tokens vs valid tokens
    extra_db_tokens = db_tokens - VALID_TOKENS
    if extra_db_tokens:
        print_finding("WARNING", f"Tokens in DB not in valid set: {extra_db_tokens}")
        findings += len(extra_db_tokens)

    missing_db_tokens = VALID_TOKENS - db_tokens
    if missing_db_tokens:
        print_finding("INFO", f"Valid tokens not in DB tokens table: {missing_db_tokens}")

    return findings


def audit_hallucination_indicators(conn):
    """Additional hallucination-specific checks."""
    print_section("7. ADDITIONAL HALLUCINATION INDICATORS")
    cur = conn.cursor()
    findings = 0

    # 7a. WP > SP + 2 (WP/SP swap detection)
    cur.execute("""
        SELECT name, wp, sp, faction, station
        FROM models
        WHERE wp IS NOT NULL AND sp IS NOT NULL
          AND CAST(wp AS INTEGER) > CAST(sp AS INTEGER) + 2
    """)
    wp_sp_swaps = cur.fetchall()
    if wp_sp_swaps:
        print_finding("WARNING", f"{len(wp_sp_swaps)} models where Wp > Sp+2 (possible swap):")
        for m in wp_sp_swaps:
            is_verified = m['name'] in VERIFIED_EDGE_CASES
            flag = " (verified)" if is_verified else ""
            print(f"           {m['name']} ({m['faction']}): Wp={m['wp']}, Sp={m['sp']}{flag}")
        findings += len([m for m in wp_sp_swaps if m['name'] not in VERIFIED_EDGE_CASES])
    else:
        print("  No Wp/Sp swap suspects found.")

    # 7b. Models with >4 triggers on a single action
    cur.execute("""
        SELECT ac.id, ac.name as action_name, m.name as model_name,
               COUNT(t.id) as trigger_count
        FROM actions ac
        JOIN models m ON ac.model_id = m.id
        JOIN triggers t ON t.action_id = ac.id
        GROUP BY ac.id
        HAVING COUNT(t.id) > 4
    """)
    many_triggers = cur.fetchall()
    if many_triggers:
        print_finding("WARNING", f"{len(many_triggers)} actions with >4 triggers:")
        for a in many_triggers:
            print(f"           {a['model_name']} -> '{a['action_name']}': {a['trigger_count']} triggers")
        findings += len(many_triggers)
    else:
        print("  No actions with >4 triggers.")

    # 7c. Duplicate model names (same name, different IDs)
    cur.execute("""
        SELECT name, COUNT(*) as cnt, GROUP_CONCAT(id) as ids,
               GROUP_CONCAT(faction) as factions
        FROM models
        GROUP BY name
        HAVING COUNT(*) > 1
    """)
    dup_models = cur.fetchall()
    if dup_models:
        print_finding("WARNING", f"{len(dup_models)} duplicate model names:")
        for d in dup_models:
            print(f"           '{d['name']}' x{d['cnt']} (ids: {d['ids']}, factions: {d['factions']})")
        findings += len(dup_models)
    else:
        print("  No duplicate model names.")

    # 7d. Models with suspiciously many abilities (>8)
    cur.execute("""
        SELECT m.name, COUNT(a.id) as ability_count
        FROM models m
        JOIN abilities a ON a.model_id = m.id
        GROUP BY m.id
        HAVING COUNT(a.id) > 8
        ORDER BY ability_count DESC
    """)
    many_abilities = cur.fetchall()
    if many_abilities:
        print_finding("INFO", f"{len(many_abilities)} models with >8 abilities:")
        for m in many_abilities:
            print(f"           {m['name']}: {m['ability_count']} abilities")

    # 7e. Models with suspiciously many actions (>8)
    cur.execute("""
        SELECT m.name, COUNT(ac.id) as action_count
        FROM models m
        JOIN actions ac ON ac.model_id = m.id
        GROUP BY m.id
        HAVING COUNT(ac.id) > 8
        ORDER BY action_count DESC
    """)
    many_actions = cur.fetchall()
    if many_actions:
        print_finding("INFO", f"{len(many_actions)} models with >8 actions:")
        for m in many_actions:
            print(f"           {m['name']}: {m['action_count']} actions")

    # 7f. Health outliers (health > 12 on non-Masters)
    cur.execute("""
        SELECT name, station, health, faction
        FROM models
        WHERE health IS NOT NULL
          AND CAST(health AS INTEGER) > 12
          AND (station IS NULL OR station != 'Master')
    """)
    health_outliers = cur.fetchall()
    if health_outliers:
        print_finding("INFO", f"{len(health_outliers)} non-Master models with health > 12:")
        for m in health_outliers:
            print(f"           {m['name']} ({m['faction']}): health={m['health']}, station={m['station']}")

    # 7g. Duplicate ability names on the same model
    cur.execute("""
        SELECT m.name as model_name, a.name as ability_name, COUNT(*) as cnt
        FROM abilities a
        JOIN models m ON a.model_id = m.id
        GROUP BY a.model_id, a.name
        HAVING COUNT(*) > 1
    """)
    dup_abilities = cur.fetchall()
    if dup_abilities:
        print_finding("ERROR", f"{len(dup_abilities)} models with duplicate ability names:")
        for d in dup_abilities:
            print(f"           {d['model_name']} -> '{d['ability_name']}' x{d['cnt']}")
        findings += len(dup_abilities)
    else:
        print("  No duplicate ability names on same model.")

    # 7h. Duplicate action names on the same model
    cur.execute("""
        SELECT m.name as model_name, ac.name as action_name, COUNT(*) as cnt
        FROM actions ac
        JOIN models m ON ac.model_id = m.id
        GROUP BY ac.model_id, ac.name
        HAVING COUNT(*) > 1
    """)
    dup_actions = cur.fetchall()
    if dup_actions:
        print_finding("ERROR", f"{len(dup_actions)} models with duplicate action names:")
        for d in dup_actions:
            print(f"           {d['model_name']} -> '{d['action_name']}' x{d['cnt']}")
        findings += len(dup_actions)
    else:
        print("  No duplicate action names on same model.")

    # 7i. Duplicate trigger names on the same action
    cur.execute("""
        SELECT m.name as model_name, ac.name as action_name,
               t.name as trigger_name, COUNT(*) as cnt
        FROM triggers t
        JOIN actions ac ON t.action_id = ac.id
        JOIN models m ON ac.model_id = m.id
        GROUP BY t.action_id, t.name
        HAVING COUNT(*) > 1
    """)
    dup_triggers = cur.fetchall()
    if dup_triggers:
        print_finding("ERROR", f"{len(dup_triggers)} actions with duplicate trigger names:")
        for d in dup_triggers:
            print(f"           {d['model_name']} -> {d['action_name']} -> '{d['trigger_name']}' x{d['cnt']}")
        findings += len(dup_triggers)
    else:
        print("  No duplicate trigger names on same action.")

    return findings


def audit_upgrade_integrity(conn):
    """Check upgrade data integrity."""
    print_section("8. UPGRADE DATA INTEGRITY")
    cur = conn.cursor()
    findings = 0

    # Check upgrades exist
    cur.execute("SELECT COUNT(*) as cnt FROM upgrades")
    upgrade_count = cur.fetchone()['cnt']
    print(f"  Total upgrades: {upgrade_count}")

    # Invalid factions in upgrades
    cur.execute("SELECT DISTINCT faction FROM upgrades WHERE faction IS NOT NULL")
    upgrade_factions = {r['faction'] for r in cur.fetchall()}
    invalid = upgrade_factions - VALID_FACTIONS - {'Universal'}
    if invalid:
        print_finding("ERROR", f"Invalid upgrade factions: {invalid}")
        findings += len(invalid)

    # Upgrade actions with invalid trigger timings
    cur.execute("""
        SELECT ut.name, ut.timing, u.name as upgrade_name
        FROM upgrade_action_triggers ut
        JOIN upgrade_actions ua ON ut.action_id = ua.id
        JOIN upgrades u ON ua.upgrade_id = u.id
        WHERE ut.timing IS NOT NULL AND ut.timing != ''
          AND ut.timing NOT IN ('after_succeeding', 'when_resolving', 'after_failing', 'after_resolving')
    """)
    bad_upgrade_timings = cur.fetchall()
    if bad_upgrade_timings:
        print_finding("ERROR", f"{len(bad_upgrade_timings)} upgrade triggers with invalid timing:")
        for t in bad_upgrade_timings:
            print(f"           {t['upgrade_name']} -> '{t['name']}': timing='{t['timing']}'")
        findings += len(bad_upgrade_timings)

    # Universal triggers with invalid timings
    cur.execute("""
        SELECT ut.name, ut.timing, u.name as upgrade_name
        FROM upgrade_universal_triggers ut
        JOIN upgrades u ON ut.upgrade_id = u.id
        WHERE ut.timing IS NOT NULL AND ut.timing != ''
          AND ut.timing NOT IN ('after_succeeding', 'when_resolving', 'after_failing', 'after_resolving')
    """)
    bad_univ_timings = cur.fetchall()
    if bad_univ_timings:
        print_finding("ERROR", f"{len(bad_univ_timings)} universal triggers with invalid timing:")
        for t in bad_univ_timings:
            print(f"           {t['upgrade_name']} -> '{t['name']}': timing='{t['timing']}'")
        findings += len(bad_univ_timings)

    if not bad_upgrade_timings and not bad_univ_timings:
        print("  All upgrade trigger timings are valid.")

    return findings


def print_summary(results):
    """Print summary of all findings."""
    print_section("SUMMARY")
    total_errors = 0
    total_warnings = 0
    total_info = 0

    for section, count in results.items():
        print(f"  {section}: {count} findings")

    # Recount from output (simplified)
    total = sum(results.values())
    print(f"\n  Total findings: {total}")
    if total == 0:
        print("  STATUS: CLEAN - No hallucination indicators detected")
    else:
        print("  STATUS: REVIEW NEEDED - See details above")


def main():
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    conn = connect_db()

    print("=" * 80)
    print("  M4E DATABASE HALLUCINATION DETECTION AUDIT")
    print(f"  Database: {DB_PATH}")
    print("=" * 80)

    # Get basic counts
    cur = conn.cursor()
    for table in ['models', 'abilities', 'actions', 'triggers', 'crew_cards', 'upgrades']:
        cur.execute(f"SELECT COUNT(*) as cnt FROM {table}")
        print(f"  {table}: {cur.fetchone()['cnt']} records")

    results = {}
    results["1. Duplicate abilities/actions"] = audit_duplicate_abilities(conn)
    results["2. Impossible stat values"] = audit_stat_values(conn)
    results["3. Suspicious text patterns"] = audit_suspicious_text(conn)
    results["4. Cross-reference integrity"] = audit_cross_references(conn)
    results["5. Fabricated data checks"] = audit_fabricated_data(conn)
    results["6. Token references"] = audit_token_references(conn)
    results["7. Hallucination indicators"] = audit_hallucination_indicators(conn)
    results["8. Upgrade integrity"] = audit_upgrade_integrity(conn)

    print_summary(results)

    conn.close()


if __name__ == "__main__":
    main()
