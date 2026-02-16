# M4E Card Parsing Pipeline

Automated extraction pipeline for Malifaux 4th Edition stat cards. Takes PDF card files as input and produces a structured SQLite database of all game data.

## Current State

**Database:** 778 models, 124 crew cards, 70 upgrades across all 8 factions.

| Faction | Models | Crew Cards | Upgrades |
|---------|--------|------------|----------|
| Resurrectionists | 107 | — | 10 |
| Outcasts | 104 | — | 13 |
| Explorer's Society | 100 | — | 8 |
| Guild | 99 | — | 9 |
| Neverborn | 97 | — | 10 |
| Arcanists | 95 | — | 3 |
| Bayou | 88 | — | 6 |
| Ten Thunders | 88 | — | 11 |

**Audit status:** 0 errors, 0 warnings, 42 checks passed.

## Architecture

Think of it like a factory assembly line — each station does one job, passes the result to the next, and quality control catches defects before anything reaches the warehouse.

```
  PDF files
     │
     ▼
┌─────────────┐
│ pdf_splitter │ ──→ Front/Back PNG images (250 DPI)
└─────────────┘
     │
     ▼
┌────────────────┐
│ card_extractor  │ ──→ Raw JSON (front + back separately)
│ (Claude API)    │     Uses vision prompts
└────────────────┘
     │
     ▼
┌─────────┐
│ merger  │ ──→ Unified card JSON (one record per model)
└─────────┘     Cross-checks front/back name match
     │
     ▼
┌───────────┐
│ validator │ ──→ Validation report
└───────────┘     Hard rules (must pass), soft flags, hallucination checks
     │
     ▼
┌───────────┐
│ db_loader │ ──→ SQLite database + audit log
└───────────┘     Auto-registers tokens, handles upsert
```

## Directory Structure

```
Malifaux-4th-Edition-Tools/
├── README.md                  ← You are here
├── source_pdfs/               ← Source PDF card files
│   ├── {Faction}/
│   │   ├── {Keyword}/
│   │   │   ├── M4E_Stat_{Keyword}_{ModelName}.pdf
│   │   │   ├── M4E_Crew_{Keyword}_{MasterName}_{Title}.pdf
│   │   │   └── M4E_Upgrade_{Keyword}_{UpgradeName}.pdf
│   │   └── Versatile - {Faction}/
│   │       └── ...
├── scripts/                   ← Core pipeline scripts
│   ├── pipeline.py            ← Single-card orchestrator
│   ├── pdf_splitter.py        ← PDF → PNG extraction
│   ├── card_extractor.py      ← PNG → JSON via Claude API
│   ├── merger.py              ← Front+Back JSON → unified JSON
│   ├── validator.py           ← Rule checking + hallucination detection
│   └── db_loader.py           ← JSON → SQLite insertion
├── db/
│   ├── schema.sql             ← Database DDL
│   └── m4e.db                 ← Production database
├── data/
│   └── all_cards_{faction}.json  ← Exported JSON per faction
├── reference/
│   └── reference_data.json    ← Valid factions, stations, tokens, enums
├── archive_scripts/           ← Archived one-off fix scripts
│
│  Root-level scripts:
├── run_faction.py             ← Batch processor (by faction/keyword)
├── final_audit.py             ← Database validation (run after any changes)
├── cleanup_repo.py            ← Archive non-essential scripts
│
│  Prompts:
├── front_prompt.txt           ← Vision prompt for card fronts
├── back_prompt.txt            ← Vision prompt for card backs
└── crew_card_prompt.txt       ← Vision prompt for crew cards
```

## Ingesting New Cards

### Adding cards to an existing faction/keyword

1. Place PDFs in the correct folder following naming conventions:
   ```
   source_pdfs/{Faction}/{Keyword}/M4E_Stat_{Keyword}_{ModelName}.pdf
   source_pdfs/{Faction}/{Keyword}/M4E_Crew_{Keyword}_{MasterName}_{Title}.pdf
   source_pdfs/{Faction}/{Keyword}/M4E_Upgrade_{Keyword}_{UpgradeName}.pdf
   ```

2. Run the pipeline for that keyword:
   ```bash
   python run_faction.py {Faction} --keyword {Keyword}
   ```
   The pipeline skips already-loaded models and only processes new ones.

3. Run the audit:
   ```bash
   python final_audit.py --verbose
   ```

4. Check for and fix common issues (see Post-Ingestion Checklist below).

### Processing an entire faction

```bash
python run_faction.py {Faction}
```

This auto-detects all keyword folders under `source_pdfs/{Faction}/` and processes them sequentially.

### Post-Ingestion Checklist

After loading new cards, always run `python final_audit.py --verbose` and check for:

1. **Station assignment** — The pipeline infers stations from characteristics (Minion, Peon, Totem, Henchman) and cost (`cost='-'` → Master). Unique models without those characteristics correctly get `NULL`. However, the API can occasionally hallucinate stations (e.g., assigning "Master" to non-Masters). Verify any new Masters have `cost='-'`.

2. **Versatile is a characteristic, NOT a keyword** — The API may extract "Versatile" as a keyword. It belongs only in `model_characteristics`. Check with:
   ```sql
   SELECT * FROM model_keywords WHERE keyword = 'Versatile';
   ```
   If any results, delete them. Versatile models legitimately have no keywords.

3. **Totem linking** — New Masters won't auto-link to their totems. You need to manually set the `totem` field on the models table. Look at the Master's crew card for the totem name. Masters with no totem by design should have `totem='-'`.

4. **Crew card linking** — New Masters need `crew_card_name` set. This should be the name of their crew card in the `crew_cards` table.

5. **Trigger suits** — Occasionally the API misses trigger suits. Check:
   ```sql
   SELECT t.name, a.name, m.name FROM triggers t
   JOIN actions a ON t.action_id = a.id
   JOIN models m ON a.model_id = m.id
   WHERE t.suit IS NULL OR t.suit = '';
   ```

6. **Stat outliers** — Review any new warnings in the audit for stats outside normal ranges. If legitimate, mark with `parse_status='verified'`.

## M4E Data Model Notes

### Stations

Valid stations in M4E 4th Edition (there is no "Enforcer" — that was 3rd Edition):

| Station | Source | Cost |
|---------|--------|------|
| Master | Characteristic on card | Always `-` |
| Henchman | Characteristic on card | Numeric |
| Minion | Characteristic with model limit, e.g., "Minion (3)" | Numeric |
| Peon | Characteristic with model limit, e.g., "Peon (6)" | Numeric |
| Totem | Characteristic on card | Usually `-`, except Effigies (cost=2) |
| NULL | No station characteristic | Numeric or `-` (summoned models) |

### Keywords vs Characteristics

Keywords define which crew a model belongs to (e.g., "Big Hat", "Redchapel", "Foundry"). Characteristics are inherent traits (e.g., "Living", "Undead", "Versatile", "Minion (3)"). The `model_keywords` and `model_characteristics` tables are separate — don't mix them.

**Versatile** is always a characteristic, never a keyword. Versatile models can be hired into any crew of their faction without penalty.

### Faction Assignment

Each model belongs to exactly **one** faction, determined by the faction folder in its source PDF path (`source_pdfs/{Faction}/{Keyword}/`). There are no dual-faction models in M4E — models that can be hired into other factions' crews do so through keyword access, not faction membership. The `model_factions` table has exactly one entry per model matching `models.faction`.

### Symbols and Notation

The schema uses parenthesized symbols throughout:

| Symbol | Meaning |
|--------|---------|
| `(r)` | Ram suit |
| `(c)` | Crow suit |
| `(m)` | Mask suit |
| `(t)` | Tome suit |
| `(melee)` | Melee range |
| `(gun)` | Missile/gun range |
| `(magic)` | Magic range |
| `(aura)` | Aura range |
| `(pulse)` | Pulse range |
| `act` / `sig` | Action / Signature action |
| `(soulstone)` | Soulstone cost |

## Validation Tiers

### Hard Rules (auto-reject)
- Attack actions must have a resist stat
- Tactical actions must NOT have resist or action_type
- Trigger timings must be valid enum values
- Station/model_limit must be consistent

### Soft Rules (flag for review)
- Unusual soulstone-on-death values
- Unexpected cost for station type
- Cards with zero abilities or zero actions
- Unusual base sizes

### Hallucination Detection
- WP/SP swap (WP >> SP is suspicious)
- Health outliers for non-Master/Henchman
- Excessive triggers on a single action (>5)
- Duplicate ability or action names
- Front/back name or title mismatches
- "Enforcer" station (3rd Edition holdover — not valid in M4E)
- Masters with numeric cost (real Masters always have `cost='-'`)

## Known Edge Cases

1. **Bayou Gremlin layout exception**: Attack actions listed under "Tactical Actions" header due to special rules. The validator auto-reclassifies these based on the presence of a resist stat.

2. **Alt-art variants**: PDFs with _A, _B, _C suffixes are art variants with identical game data. The pipeline deduplicates, only processing the primary variant.

3. **Variable range actions**: Some actions let you choose melee or missile at declaration. Stored as `action_type: "variable"`.

4. **Summoned models with cost='-'**: Some non-Master models have `cost='-'` because they can only be summoned (e.g., Scales of Justice). These correctly have `station=NULL`.

5. **Nexus has no totem**: Represented as `totem='-'` in the database.

6. **Control-effect attacks**: 211+ attack actions have no damage value — these are lures, pushes, and other control effects. This is correct and expected.

7. **Effigy totems with numeric cost**: Effigies are Totems but have `cost=2`. The audit excludes them from the Master/Totem cost check.

## Audit

Run the comprehensive audit anytime:

```bash
python final_audit.py           # Summary view
python final_audit.py --verbose  # Full details
python final_audit.py --export report.json  # Export to JSON
```

The audit checks 7 categories: structural integrity, statistical outliers, consistency, completeness, duplicates, upgrade cards, and cross-table references.

## Troubleshooting

**"JSON parse error"**: The vision model occasionally wraps output in markdown fences. The extractor strips these automatically, but malformed JSON will retry up to 3 times.

**"Name mismatch front/back"**: Usually means OCR read the name differently (e.g., apostrophe variants). Check the merged JSON and fix manually if needed.

**"Attack action missing resist"**: Either a genuine layout exception (see edge case #1) or the vision model missed the resist column. Re-extract or manually verify.

**Rate limiting**: The pipeline has a configurable delay between API calls (default 1s). Increase with `--delay 3` if hitting rate limits.

**Duplicate models after re-run**: If re-running a keyword that already has models loaded, the pipeline should skip existing models. If duplicates appear (usually with different casing), delete the higher-ID duplicates and keep the originals.

## Cost

Using Claude Sonnet 4.5 for extraction:
- ~2 API calls per stat card (front + back)
- ~1 API call per crew card
- Total project cost for 780 models + 124 crew cards + 70 upgrades: approximately $20-30 in API costs
