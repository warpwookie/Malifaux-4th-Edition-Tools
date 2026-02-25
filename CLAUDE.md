# CLAUDE.md — M4E Card Parsing Pipeline

## Project Overview

Automated data extraction pipeline for **Malifaux 4th Edition** (M4E) tabletop game stat cards. Reads PDF card images via Claude Vision API, extracts structured game data into JSON, validates it, and loads it into a normalized SQLite database.

**Current state:** 798 models, 130 crew cards, 70 upgrades across 8 factions. JSON files in `Model Data Json/` are the **authoritative data source** (the SQLite database needs rebuilding — see [Database Status](#database-status)).

## Tech Stack

- **Language:** Python 3 (no external package manager — no requirements.txt/pyproject.toml)
- **Dependencies:** `anthropic` (Claude API), `fitz`/PyMuPDF (PDF rendering), `sqlite3` (stdlib)
- **Database:** SQLite (`db/m4e.db`), 22 normalized tables, WAL journal mode, foreign keys enforced
- **API:** Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) for vision extraction, 4096 max tokens, 3 retries with 5s delay
- **Environment variable required:** `ANTHROPIC_API_KEY`

## Directory Layout

```
├── run_faction.py          # MAIN ENTRY POINT — batch process a faction
├── final_audit.py          # Database-wide validation (7 audit layers)
├── cleanup_repo.py         # Archive one-off scripts
├── m4e_data_inventory.md   # Data integrity report (Feb 2026)
├── scripts/                # Core pipeline modules (8 files)
│   ├── pipeline.py         # Single-card orchestrator (single/batch/dry-run)
│   ├── pdf_splitter.py     # PDF → PNG at 250 DPI via PyMuPDF
│   ├── card_extractor.py   # PNG → JSON via Claude Vision API
│   ├── merger.py           # Front+Back JSON → unified card JSON
│   ├── validator.py        # Hard rules, soft flags, hallucination detection
│   ├── db_loader.py        # Validated JSON → SQLite (upsert with cascades)
│   ├── denormalize.py      # DB → denormalized JSON for AI knowledge base
│   └── rebuild_db_from_json.py  # Reconstruct DB from JSON exports
├── schema/
│   └── schema.sql          # Full SQLite DDL (22 tables, 12 indexes, idempotent)
├── db/
│   ├── m4e.db              # SQLite database (currently empty — needs rebuild)
│   └── README.md           # Table docs + example queries
├── data/                   # Per-faction JSON exports (8 files, stat cards only)
├── Model Data Json/        # Denormalized exports for AI context (13 files)
├── reference/
│   └── reference_data.json # Validation enums: factions, stations, suits, tokens
├── prompts/                # Vision prompt templates (4 files)
│   ├── front_prompt.txt    # Stat card front (model data, stats, characteristics)
│   ├── back_prompt.txt     # Stat card back (actions, triggers, effects)
│   ├── crew_card_prompt.txt    # Crew cards (keyword grants, markers, tokens)
│   └── upgrade_prompt.txt      # Upgrade cards (type, limitations, abilities)
├── source_pdfs/            # Source PDFs organized by faction/keyword (gitignored)
├── pipeline_work/          # Intermediate PNGs and merged JSONs (~280 subdirs)
└── archive_scripts/        # 52 archived one-off fix/check/diagnose scripts
```

## Key Commands

```bash
# Process a single keyword within a faction
python run_faction.py Bayou --keyword Sooey

# Process an entire faction (auto-detects keyword folders)
python run_faction.py Guild

# Preview what would be processed (no API calls)
python run_faction.py Outcasts --list-only

# Dry run — extract + validate but don't load to DB
python run_faction.py Outcasts --dry-run

# Include upgrade card processing
python run_faction.py Guild --include-upgrades

# Set API rate limiting (default: 1.5s between calls)
python run_faction.py Bayou --delay 2.0

# Run the comprehensive audit (always do this after changes)
python final_audit.py --verbose

# Export audit to JSON
python final_audit.py --export report.json

# Rebuild database from JSON sources
python scripts/rebuild_db_from_json.py

# Export denormalized JSON from DB
python scripts/denormalize.py
```

## Pipeline Flow

```
PDF → pdf_splitter (PNG at 250 DPI)
    → card_extractor (raw JSON via Claude Vision API)
    → merger (front+back → unified card JSON)
    → validator (hard rules + soft flags + hallucination detection)
    → db_loader (SQLite upsert with cascade deletes)
    → denormalize (DB → per-faction JSON for AI knowledge base)
```

### Card Types

The pipeline processes three card types:
- **Stat cards** — Two-sided (front: stats/abilities, back: actions/triggers). Split into front/back PNGs, extracted separately, then merged.
- **Crew cards** — Single-sided. Grant keyword abilities/actions to models in a crew.
- **Upgrade cards** — Single-sided. Attachable abilities/actions with restrictions.

## Database Status

The SQLite database (`db/m4e.db`) is currently **empty** (the original was corrupted — binary content mangled). The JSON files in `Model Data Json/` are the authoritative data source.

**To rebuild the database:**
```bash
python scripts/rebuild_db_from_json.py
```

This reads from `Model Data Json/` (8 faction files + crew cards + upgrades + tokens) and reconstructs all 22 tables.

### Schema Overview (22 tables)

| Group | Tables | Description |
|-------|--------|-------------|
| Core model data | `models`, `model_keywords`, `model_characteristics`, `model_factions` | One row per model with stats, keywords, characteristics |
| Abilities & actions | `abilities`, `actions`, `triggers` | Passive abilities, attack/tactical actions, trigger effects |
| Crew cards | `crew_cards`, `crew_keyword_abilities`, `crew_keyword_actions`, `crew_keyword_action_triggers`, `crew_markers`, `crew_marker_terrain_traits`, `crew_tokens` | Master crew cards and their keyword grants |
| Upgrade cards | `upgrades`, `upgrade_abilities`, `upgrade_actions`, `upgrade_action_triggers`, `upgrade_universal_triggers` | Attachable upgrades and their effects |
| Reference | `tokens`, `token_model_sources` | Global token registry and which models apply/remove them |
| Audit | `parse_log` | Extraction audit trail with violation records |

## Data Files

### `data/` — Per-Faction Stat Card Exports
8 JSON files (`all_cards_{faction}.json`), one per faction. Contains fully parsed stat card data exported from the pipeline. These are intermediate exports — some contain duplicates from re-processing.

### `Model Data Json/` — Denormalized Knowledge Base (Authoritative)
13 JSON files generated by `denormalize.py`. Self-contained documents with all stats, keywords, abilities, actions, and triggers nested inline:

| File | Contents |
|------|----------|
| `m4e_models_all.json` | All 798 models combined |
| `m4e_models_{faction}.json` (×8) | Per-faction model data |
| `m4e_crew_cards.json` | 130 crew cards |
| `m4e_upgrades.json` | 70 upgrade cards |
| `m4e_tokens.json` | 66 tokens (name-only, no effect descriptions) |
| `m4e_faction_summary.json` | Keywords per faction |

### Model Counts by Faction

| Faction | Models |
|---------|-------:|
| Arcanists | 95 |
| Bayou | 110 |
| Explorer's Society | 100 |
| Guild | 99 |
| Neverborn | 97 |
| Outcasts | 102 |
| Resurrectionists | 107 |
| Ten Thunders | 88 |
| **Total** | **798** |

## Coding Conventions

- **Imports:** stdlib first, then third-party. `try/except ImportError` with install hints for optional deps.
- **Naming:** `snake_case` functions/variables, `PascalCase` classes, `SCREAMING_SNAKE_CASE` constants.
- **Paths:** Always use `pathlib.Path`, never `os.path`.
- **File I/O:** Always specify `encoding="utf-8"` explicitly.
- **CLI:** Every script is both importable and a CLI tool (`if __name__ == "__main__"` + `argparse`).
- **Return values:** Functions return dicts with `"status"` key. Errors return `{"error": "message"}`.
- **DB access:** Use `sqlite3.Row` for column-name access.

## M4E Domain Knowledge

### Factions (8)
Guild, Arcanists, Neverborn, Bayou, Outcasts, Resurrectionists, Ten Thunders, Explorer's Society

### Stations
Master (`cost='-'`), Henchman, Minion (with model limit), Peon (with model limit), Totem (usually `cost='-'`, except Effigies at cost=2). No "Enforcer" — that was 3rd Edition.

### Suit symbols
`(r)` Ram, `(c)` Crow, `(m)` Mask, `(t)` Tome

### Range icons
`(melee)`, `(gun)`, `(magic)`, `(aura)`, `(pulse)`

### Other icons
`(soulstone)` soulstone cost, `(+)` positive fate modifier, `(-)` negative fate modifier, `(fortitude)` fortitude defense, `(warding)` warding defense

### Critical rules
- **Versatile** is a characteristic, NOT a keyword. Never put it in `model_keywords`.
- Each model belongs to exactly **one** faction. No dual-faction models in M4E.
- Keywords define crew membership. Characteristics are inherent traits.
- Attack actions MUST have a resist stat. Tactical actions must NOT have one.
- Tactical actions must have `action_type=null`.
- Trigger timings (6 valid values): `when_resolving`, `after_succeeding`, `after_failing`, `after_damaging`, `when_declaring`, `after_resolving`
- Valid resist stats: `Df`, `Wp`, `Sz`, `Sp`, `Mv`
- Defensive ability types: `fortitude`, `warding`, `unusual_defense`

### Stat ranges (hard bounds)
- Df: 2–8, Wp: 0–8, Sz: 0–6, Sp: 0–9, Health: 0–16
- Wp=0: Clockwork Trap (inanimate). Sz=0: Gupps, Voodoo Doll, Camerabot. Sp=0: immobile/inanimate models. Sp=9: Sunless Self. Health=0: Marathine (card text: "does not have health").

### Known edge cases
1. Bayou Gremlin: attack actions under "Tactical Actions" header (auto-reclassified by validator)
2. Alt-art variants: `_A`/`_B`/`_C` suffixes — only `_A` is processed
3. Variable range actions: `action_type: "variable"`
4. Summoned-only models: `cost='-'` with `station=NULL`
5. Nexus has no totem: represented as `totem='-'`
6. Control-effect attacks: no damage value (lures, pushes) — this is correct
7. Effigy totems have `cost=2` (excluded from Master/Totem cost audit)
8. Crossroads keyword: 7 Henchman-led crews (Seven Deadly Sins: Envy, Gluttony, Greed, Wrath, Pride, Sloth, Lust). Wrath is the only one with a crew card ("On Tour"). These are Henchmen (`cost=8`), not Masters.
9. Master stat card layout: center text after bullet = **keyword**, bottom-left = **crew card name**, bottom-right = **totem name** (sometimes with model limit). Both master titles share the same keyword. Do NOT parse crew card names or totem names as keywords.
10. 54 Versatile models (Effigies, Emissaries, Riders, cross-faction) have no keywords — this is correct by design.
11. Master title variants produce duplicate name+faction entries (expected — base + title version).

## Validation Tiers

- **Hard rules** (auto-reject): required fields, valid factions, stat ranges, attack/tactical action constraints, trigger timing enums, Unique→model_limit=1
- **Soft rules** (flag for review): unusual cost/station combos, zero abilities/actions, soulstone-on-death anomalies
- **Hallucination flags**: WP/SP swaps (WP > SP+2), health outliers, >4 triggers per action, duplicate names, name mismatches between front/back, stat copy errors between title variants, fabricated abilities from similar models or older editions

### Audit Layers (`final_audit.py`)

The audit runs 7 sequential validation passes:

1. **Structural** — Missing required fields, invalid enum values, type checks
2. **Statistical** — Stat outlier detection, hallucination pattern matching
3. **Consistency** — Faction/keyword/station cross-validation
4. **Completeness** — Source PDF coverage, empty abilities/actions, null trigger suits
5. **Duplicates** — Name collisions, case-sensitive mismatches
6. **Upgrades** — Upgrade card structure and keyword validity
7. **Cross-table** — Crew cards reference valid masters, models reference valid crew cards

## Known Data Quality Issues

Per `m4e_data_inventory.md` (Feb 2026):

1. **Database needs rebuild** — `m4e.db` is empty; use `scripts/rebuild_db_from_json.py`
2. **33 crew cards have wrong/missing faction** — 12 tagged with keyword name instead of faction, 18 tagged as Unknown, 3 with "Outcast" vs "Outcasts" typo
3. **Faction summary mixes model names with keywords** — Some totem/unique model names appear as "keywords" in `m4e_faction_summary.json`
4. **Token data is name-only** — No effect descriptions in `m4e_tokens.json` yet

## Post-Ingestion Checklist

After loading new cards, always run `final_audit.py --verbose` and check:
1. Station assignment correctness (Masters must have `cost='-'`)
2. Versatile not in keywords table
3. Totem linking (`models.totem` field)
4. Crew card linking (`models.crew_card_name` field)
5. Null or empty trigger suits
6. Stat outliers (mark legitimate ones as `parse_status='verified'`)

## PDF Filename Conventions

Source PDFs follow these patterns:
- Stat cards: `M4E_Stat_{Keyword}_{ModelName}.pdf` (e.g., `M4E_Stat_BigHat_Bayou_Gremlin_A.pdf`)
- Crew cards: `M4E_Crew_{Keyword}_{MasterName}_{Title}.pdf` (e.g., `M4E_Crew_BigHat_Somer_Teeth_Jones_Bayou_Boss.pdf`)
- Suffixes `_A`, `_B`, `_C` indicate alt-art variants with identical game data

## No Build System / Tests / CI

There is no formal test suite, CI pipeline, or package manager configuration. The `final_audit.py` script serves as the primary automated validation mechanism. The `m4e_data_inventory.md` file documents known data quality issues.
