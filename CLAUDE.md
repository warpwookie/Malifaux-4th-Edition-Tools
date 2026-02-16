# CLAUDE.md — M4E Card Parsing Pipeline

## Project Overview

Automated data extraction pipeline for **Malifaux 4th Edition** (M4E) tabletop game stat cards. Reads PDF card images via Claude Vision API, extracts structured game data into JSON, validates it, and loads it into a normalized SQLite database.

**Current state:** 778 models, 124 crew cards, 70 upgrades across 8 factions. 0 errors, 0 warnings, 42 audit checks passed.

## Tech Stack

- **Language:** Python (no external package manager — no requirements.txt/pyproject.toml)
- **Dependencies:** `anthropic` (Claude API), `fitz`/PyMuPDF (PDF rendering), `sqlite3` (stdlib)
- **Database:** SQLite (`db/m4e.db`), 15+ normalized tables, WAL journal mode, foreign keys enforced
- **API:** Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) for vision extraction
- **Environment variable required:** `ANTHROPIC_API_KEY`

## Directory Layout

```
├── run_faction.py          # MAIN ENTRY POINT — batch process a faction
├── final_audit.py          # Database-wide validation (run after any changes)
├── cleanup_repo.py         # Archive one-off scripts
├── scripts/                # Core pipeline modules
│   ├── pipeline.py         # Single-card orchestrator (5-step flow)
│   ├── pdf_splitter.py     # PDF → PNG at 250 DPI
│   ├── card_extractor.py   # PNG → JSON via Claude Vision API
│   ├── merger.py           # Front+Back JSON → unified card JSON
│   ├── validator.py        # Hard rules, soft flags, hallucination detection
│   ├── db_loader.py        # Validated JSON → SQLite (upsert with cascades)
│   └── denormalize.py      # DB → denormalized JSON for AI knowledge base
├── schema/
│   └── schema.sql          # Full SQLite DDL (idempotent, CREATE IF NOT EXISTS)
├── db/
│   ├── m4e.db              # Production database
│   └── README.md           # Table docs + example queries
├── data/                   # Per-faction JSON exports from DB
├── Model Data Json/        # Denormalized exports for AI context
├── reference/
│   └── reference_data.json # Validation enums: factions, stations, suits, tokens
├── prompts/                # Vision prompt templates (.txt)
├── pipeline_work/          # Intermediate PNGs and merged JSONs (per faction)
├── Rules and Objectives/   # Game rules in PDF, JSON, and Markdown
└── archive_scripts/        # ~55 archived one-off fix/check/diagnose scripts
```

## Key Commands

```bash
# Process a single keyword within a faction
python run_faction.py Bayou --keyword Sooey

# Process an entire faction (auto-detects keyword folders)
python run_faction.py Guild

# Run the comprehensive audit (always do this after changes)
python final_audit.py --verbose

# Export audit to JSON
python final_audit.py --export report.json
```

## Pipeline Flow

PDF → `pdf_splitter` (PNG) → `card_extractor` (raw JSON via Claude API) → `merger` (unified JSON) → `validator` (rule checks) → `db_loader` (SQLite)

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
- Df/Wp: 2–8, Sz: 1–6, Sp: 3–8, Health: 1–16

### Known edge cases
1. Bayou Gremlin: attack actions under "Tactical Actions" header (auto-reclassified by validator)
2. Alt-art variants: `_A`/`_B`/`_C` suffixes — only `_A` is processed
3. Variable range actions: `action_type: "variable"`
4. Summoned-only models: `cost='-'` with `station=NULL`
5. Nexus has no totem: represented as `totem='-'`
6. Control-effect attacks: no damage value (lures, pushes) — this is correct
7. Effigy totems have `cost=2` (excluded from Master/Totem cost audit)

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
