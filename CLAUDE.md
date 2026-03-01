# CLAUDE.md — M4E Card Parsing Pipeline

## Project Overview

Automated data extraction pipeline for **Malifaux 4th Edition** (M4E) tabletop game stat cards. Extracts structured game data directly from PDF text layers using PyMuPDF, validates it, and loads it into a normalized SQLite database.

**Current state:** 798 models, 130 crew cards, 70 upgrades across 8 factions. 0 errors, 0 warnings, 42 audit checks passed.

## Tech Stack

- **Language:** Python (no external package manager — no requirements.txt/pyproject.toml)
- **Dependencies:** `fitz`/PyMuPDF (PDF text extraction), `sqlite3` (stdlib)
- **Database:** SQLite (`db/m4e.db`), 15+ normalized tables, WAL journal mode, foreign keys enforced
- **Extraction:** Font-based text parsing via PyMuPDF — no API calls needed

## Directory Layout

```
├── final_audit.py              # Database-wide validation (run after any changes)
├── cleanup_repo.py             # Archive one-off scripts
├── scripts/                    # Core pipeline modules
│   ├── pdf_text_extractor.py   # PDF → JSON via PyMuPDF text parsing (stat/crew/upgrade)
│   ├── pdf_text_batch.py       # MAIN ENTRY POINT — batch process all factions
│   ├── merger.py               # Front+Back JSON → unified card JSON
│   ├── validator.py            # Hard rules, soft flags, hallucination detection
│   ├── db_loader.py            # Validated JSON → SQLite (upsert with cascades)
│   ├── denormalize.py          # DB → denormalized JSON for AI knowledge base
│   ├── detect_m3e.py           # M3E contamination scanner
│   ├── load_rules_data.py      # Rules/FAQ/strategies → SQLite
│   └── generate_token_reference.py  # Token reference PDF generator
├── schema/
│   └── schema.sql              # Full SQLite DDL (idempotent, CREATE IF NOT EXISTS)
├── db/
│   ├── m4e.db                  # Production database
│   └── README.md               # Table docs + example queries
├── data/                       # Per-faction JSON exports from DB
├── Model Data Json/            # Denormalized exports for AI context
├── reference/
│   └── reference_data.json     # Validation enums: factions, stations, suits, tokens
├── pipeline_work/              # Intermediate merged JSONs (per faction, gitignored)
├── Rules and Objectives/       # Game rules in PDF, JSON, and Markdown
└── archive_scripts/            # ~74 archived scripts (includes legacy Vision API pipeline)
```

## Key Commands

```bash
# Full re-ingestion of all factions (stat + crew + upgrade cards)
PYTHONIOENCODING=utf-8 python scripts/pdf_text_batch.py --all

# Process a single faction
PYTHONIOENCODING=utf-8 python scripts/pdf_text_batch.py --faction Guild

# Reload rules/FAQ/strategies data
PYTHONIOENCODING=utf-8 python scripts/load_rules_data.py

# Run the comprehensive audit (always do this after changes)
python final_audit.py --verbose

# Export denormalized JSON files
PYTHONIOENCODING=utf-8 python scripts/denormalize.py

# Scan for M3E contamination
PYTHONIOENCODING=utf-8 python scripts/detect_m3e.py
```

## Pipeline Flow

PDF → `pdf_text_extractor` (structured JSON via PyMuPDF) → `merger` (unified JSON) → `validator` (rule checks) → `db_loader` (SQLite)

Batch orchestrator: `pdf_text_batch.py` — discovers PDFs across `source_pdfs/`, processes in 3 phases: stat cards → crew cards → upgrades.

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

### Critical rules
- **Versatile** is a characteristic, NOT a keyword. Never put it in `model_keywords`.
- Each model belongs to exactly **one** faction. No dual-faction models in M4E.
- Keywords define crew membership. Characteristics are inherent traits.
- Attack actions MUST have a resist stat. Tactical actions must NOT.
- Trigger timings: `after_resolving`, `after_damaging`, `after_succeeding`, `on_success`, `before_resolving`, `on_trigger`

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

## Validation Tiers

- **Hard rules** (auto-reject): required fields, valid factions, stat ranges, attack/tactical action constraints, trigger timing enums, Unique→model_limit=1
- **Soft rules** (flag for review): unusual cost/station combos, zero abilities/actions, soulstone-on-death anomalies
- **Hallucination flags**: WP/SP swaps (WP > SP+2), health outliers, >4 triggers per action, duplicate names, name mismatches between front/back

## Post-Ingestion Checklist

After loading new cards, always run `final_audit.py --verbose` and check:
1. Station assignment correctness (Masters must have `cost='-'`)
2. Versatile not in keywords table
3. Totem linking (`models.totem` field)
4. Crew card linking (`models.crew_card_name` field)
5. Null or empty trigger suits
6. Stat outliers (mark legitimate ones as `parse_status='verified'`)

## No Build System / Tests / CI

There is no formal test suite, CI pipeline, or package manager configuration. The `final_audit.py` script serves as the primary automated validation mechanism.
