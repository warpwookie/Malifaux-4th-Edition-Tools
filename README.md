# M4E Card Parsing Pipeline

Automated extraction pipeline for Malifaux 4th Edition stat cards. Takes PDF card files as input and produces a structured SQLite database of all game data.

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
│ (Claude API)    │     Uses vision prompts from /prompts/
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
m4e_pipeline/
├── README.md               ← You are here
├── prompts/
│   ├── front_prompt.txt    ← Vision prompt for card fronts
│   ├── back_prompt.txt     ← Vision prompt for card backs
│   └── crew_card_prompt.txt← Vision prompt for crew cards
├── scripts/
│   ├── pipeline.py         ← Main orchestrator (run this)
│   ├── pdf_splitter.py     ← PDF → PNG extraction
│   ├── card_extractor.py   ← PNG → JSON via Claude API
│   ├── merger.py           ← Front+Back JSON → unified JSON
│   ├── validator.py        ← Rule checking + hallucination detection
│   └── db_loader.py        ← JSON → SQLite insertion
├── reference/
│   └── reference_data.json ← Known factions, tokens, validation enums
└── db/
    ├── schema.sql          ← Database DDL (auto-applied on first run)
    └── m4e_seed.db         ← Seed database with 31 verified Bayou models
```

## Quick Start

### Prerequisites

```bash
pip install anthropic PyMuPDF
export ANTHROPIC_API_KEY="your-key-here"
```

### Process a single card

```bash
cd scripts/
python pipeline.py single ../path/to/M4E_Stat_Guild_SomeModel.pdf --db ../db/m4e.db
```

### Process an entire folder of PDFs

```bash
python pipeline.py batch ../path/to/pdf_folder/ --db ../db/m4e.db
```

### Dry run (extract + validate, don't touch DB)

```bash
python pipeline.py batch ../pdfs/ --db ../db/m4e.db --dry-run
```

### Skip already-processed cards

```bash
python pipeline.py batch ../pdfs/ --db ../db/m4e.db --skip-existing
```

### Replace existing entries

```bash
python pipeline.py batch ../pdfs/ --db ../db/m4e.db --replace
```

## Usage: Individual Scripts

Each script works standalone if you want to run steps manually:

```bash
# Extract images from a PDF
python pdf_splitter.py card.pdf -o ./images/

# Extract data from images via API
python card_extractor.py front.png back.png -o extracted.json

# Merge front + back
python merger.py extracted.json -o merged.json

# Validate
python validator.py merged.json

# Load to database
python db_loader.py merged.json --db m4e.db
```

## Validation Tiers

### Hard Rules (auto-reject)
- Attack actions must have a resist stat
- Tactical actions must NOT have resist or action_type
- Trigger timings must be valid enum values
- Station/model_limit must be consistent
- Masters must have crew_card_name and totem

### Soft Rules (flag for review)
- Unusual soulstone-on-death values
- Unexpected cost for station type
- Cards with zero abilities or zero actions
- Unusual base sizes

### Hallucination Detection
- WP/SP swap (WP >> SP is suspicious)
- Health outliers for non-Master/Henchman
- Excessive triggers on a single action
- Duplicate ability or action names
- Front/back name or title mismatches

## Known Edge Cases

These are documented from the Bayou parsing pilot (34+ cards):

1. **Bayou Gremlin layout exception**: Attack actions listed under "Tactical Actions" header. The validator auto-reclassifies these based on the presence of a resist stat.

2. **Alt-art variants**: PDFs with _A, _B, _C suffixes are art variants with identical game data. The splitter auto-deduplicates, only processing the primary variant.

3. **Variable range actions**: Some actions let you choose melee or missile at declaration (e.g., "Ol' Thunder"). Stored as action_type: "variable".

4. **Built-in suit + fate modifier**: A skill can have both (e.g., "5c+" = skill 5, built-in Crow, positive fate). No examples seen yet, but schema supports it.

5. **Crew-specific tokens**: Tokens like "Drift" or "Aura (Staggered)" are defined on crew cards, not in the global token list. The crew card schema captures these.

## Seed Database

The `db/m4e_seed.db` contains 31 verified Bayou faction models parsed from actual card images and cross-checked against source PDFs. This serves as:

- Ground truth for validating the extraction pipeline
- Baseline for regression testing
- Starting point so you don't re-process already-verified cards

Models included: Som'er (2 titles), Lenny Jones, Georgy and Olaf, Skeeter, Bayou Gremlin, Good Ol' Boy, Gremlin Crier, Spit Hog, Gluttony, Spawn Mother, Stuffed Piglet, Drumstick, Toast, Lucky Fate (Emissary + Effigy), Silurid, McTavish, Taxidermist, Barrelby, Ruffles, Fluffernutter, Habber-Dasher, Jebediah Jones, Bashe, Gupps, Bayou Smuggler, Squish and Squash, Bo Peep, Bayou Gator, Stumpy.

## Scaling Plan

1. **Pilot complete** ✓ — Bayou faction (Big Hat, Infamous, Angler, Versatile)
2. **Remaining Bayou keywords** — Kin, Sooey, Tri-Chi, Wizz-Bang, Swampfiend
3. **Other factions** — Guild, Arcanists, Neverborn, Outcasts, Resurrectionists, Ten Thunders, Explorer's Society
4. **Crew cards** — One per Master title
5. **Upgrade cards** — Loot tokens and faction upgrades

Estimated total: ~800-1000 unique models across all factions.

## Cost Estimate

Using Claude Sonnet 4.5 for extraction:
- ~2 API calls per stat card (front + back)
- ~1 API call per crew card
- Estimated input: ~1500 tokens/image, output: ~2000 tokens/card
- At ~1000 cards: roughly $15-25 in API costs

## Troubleshooting

**"JSON parse error"**: The vision model occasionally wraps output in markdown fences. The extractor strips these automatically, but malformed JSON will retry up to 3 times.

**"Name mismatch front/back"**: Usually means OCR read the name differently (e.g., apostrophe variants). Check the merged JSON and fix manually if needed.

**"Attack action missing resist"**: Either a genuine layout exception (see edge case #1) or the vision model missed the resist column. Re-extract or manually verify.

**Rate limiting**: The pipeline has a configurable delay between API calls (default 1s). Increase with `--delay 3` if hitting rate limits.
