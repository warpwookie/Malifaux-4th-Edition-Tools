# M4E Database Reference

SQLite database containing all Malifaux 4th Edition stat card data.

**File:** `m4e.db`
**Models:** 778 | **Crew Cards:** 124 | **Upgrades:** 70

## Quick Start

```python
import sqlite3
conn = sqlite3.connect("db/m4e.db")
conn.row_factory = sqlite3.Row  # access columns by name
c = conn.cursor()
```

## Tables

### Core Model Data

**`models`** — One row per unique model (name + title combination).

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER | Primary key |
| name | TEXT | Model name |
| title | TEXT | Title variant, e.g., "Bayou Boss". NULL if no title |
| faction | TEXT | Exactly one of the 8 factions |
| station | TEXT | Master, Henchman, Minion, Totem, Peon, or NULL |
| model_limit | INTEGER | 1 for Unique, N for Minion(N)/Peon(N) |
| cost | TEXT | Hiring cost. "-" for Masters/Totems. Numeric string otherwise |
| df, wp, sz, sp | INTEGER | Defense, Willpower, Size, Speed |
| health | INTEGER | Health points |
| soulstone_cache | INTEGER | Starting soulstones (Masters only) |
| shields | INTEGER | Starting Shielded tokens |
| base_size | TEXT | "30mm", "40mm", or "50mm" |
| crew_card_name | TEXT | Masters only: name of their crew card |
| totem | TEXT | Masters only: name of their totem. "-" means no totem |
| source_pdf | TEXT | Path to source PDF for traceability |
| parse_status | TEXT | "auto", "verified", or "flagged" |

**`model_keywords`** — Keywords for each model (e.g., "Big Hat", "Redchapel"). Versatile models have no keywords.

**`model_characteristics`** — Characteristics (e.g., "Living", "Undead", "Versatile", "Minion (3)").

**`model_factions`** — One entry per model. Matches `models.faction` (no dual-faction in M4E).

### Abilities & Actions

**`abilities`** — Passive abilities on stat cards.

| Column | Type | Notes |
|--------|------|-------|
| model_id | INTEGER | FK to models |
| name | TEXT | Ability name |
| defensive_type | TEXT | "fortitude", "warding", "unusual_defense", or NULL |
| text | TEXT | Full rules text |

**`actions`** — Attack and tactical actions.

| Column | Type | Notes |
|--------|------|-------|
| model_id | INTEGER | FK to models |
| name | TEXT | Action name |
| category | TEXT | "attack_actions" or "tactical_actions" |
| action_type | TEXT | "melee", "missile", "magic", "variable" (attacks only) |
| range | TEXT | e.g., '(melee)2"', '(gun)10"', '(aura)4"' |
| skill_value | INTEGER | Skill number |
| skill_built_in_suit | TEXT | "r", "m", "t", "c", or NULL |
| resist | TEXT | "Df", "Wp", "Sz", "Sp", "Mv" (attacks only) |
| damage | TEXT | Damage value. NULL for control effects |
| is_signature | BOOLEAN | Signature action flag |
| soulstone_cost | INTEGER | 0, 1, or 2 |
| effects | TEXT | Resolution effect text |

**`triggers`** — Triggers attached to actions.

| Column | Type | Notes |
|--------|------|-------|
| action_id | INTEGER | FK to actions |
| name | TEXT | Trigger name |
| suit | TEXT | Required suit(s), e.g., "(r)", "(c)(m)" |
| timing | TEXT | when_resolving, after_succeeding, after_failing, after_damaging, when_declaring, after_resolving |
| text | TEXT | Trigger effect text |
| is_mandatory | BOOLEAN | Mandatory trigger flag |

### Crew Cards

**`crew_cards`** — Master/Henchman crew cards that grant keyword abilities.

| Column | Type | Notes |
|--------|------|-------|
| name | TEXT | Crew card name, e.g., "Snatch 'N Run" |
| associated_master | TEXT | Master name |
| associated_title | TEXT | Master title |
| faction | TEXT | Faction |

**`crew_keyword_abilities`** — Abilities granted to keyword models by crew cards.

**`crew_keyword_actions`** — Actions granted to keyword models by crew cards.

**`crew_keyword_action_triggers`** — Triggers on crew-granted actions.

**`crew_markers`** — Markers defined on crew cards (with `crew_marker_terrain_traits`).

**`crew_tokens`** — Crew-specific tokens defined on crew cards.

### Upgrade Cards

**`upgrades`** — Upgrade cards that can be attached to models.

**`upgrade_abilities`** — Abilities granted by upgrades.

**`upgrade_actions`** — Actions granted by upgrades.

**`upgrade_action_triggers`** — Triggers on upgrade-granted actions.

**`upgrade_granted_triggers`** — Triggers granted to existing actions by upgrades.

### Reference Tables

**`tokens`** — Global token registry (Focused, Stunned, etc.)

**`token_model_sources`** — Which models apply/remove which tokens.

**`parse_log`** — Extraction audit trail.

## Useful Queries

**All models in a faction:**
```sql
SELECT name, title, station, cost, health
FROM models WHERE faction = 'Bayou'
ORDER BY station, name;
```

**A model's full stat line:**
```sql
SELECT name, title, df, wp, sz, sp, health, cost, station, base_size
FROM models WHERE name = 'Lenny Jones';
```

**All actions and triggers for a model:**
```sql
SELECT a.name as action, a.category, a.action_type, a.damage,
       t.name as trigger, t.suit, t.timing, t.text
FROM actions a
LEFT JOIN triggers t ON t.action_id = a.id
WHERE a.model_id = (SELECT id FROM models WHERE name = 'Lenny Jones')
ORDER BY a.category, a.name, t.name;
```

**All abilities for a model:**
```sql
SELECT name, defensive_type, text
FROM abilities WHERE model_id = (SELECT id FROM models WHERE name = 'Lenny Jones');
```

**Find models by keyword:**
```sql
SELECT m.name, m.title, m.station, m.cost
FROM models m
JOIN model_keywords mk ON m.id = mk.model_id
WHERE mk.keyword = 'Big Hat'
ORDER BY m.station, m.name;
```

**Find a Master's crew card abilities:**
```sql
SELECT cka.granted_to, cka.name, cka.text
FROM crew_keyword_abilities cka
JOIN crew_cards cc ON cka.crew_card_id = cc.id
WHERE cc.associated_master = 'Som''er Teeth Jones'
  AND cc.associated_title = 'Bayou Boss';
```

**Models by station across factions:**
```sql
SELECT faction, station, COUNT(*) as count
FROM models
GROUP BY faction, station
ORDER BY faction, station;
```

**Versatile models in a faction:**
```sql
SELECT m.name, m.title, m.cost, m.health
FROM models m
JOIN model_characteristics mc ON m.id = mc.model_id
WHERE mc.characteristic = 'Versatile'
  AND m.faction = 'Bayou';
```

## Symbols Reference

| Symbol | Meaning |
|--------|---------|
| `(r)` | Ram |
| `(c)` | Crow |
| `(m)` | Mask |
| `(t)` | Tome |
| `(melee)` | Melee range |
| `(gun)` | Missile range |
| `(magic)` | Magic range |
| `(aura)` | Aura range |
| `(pulse)` | Pulse range |

## Validation

Run `python final_audit.py` from the repo root to check data integrity.
