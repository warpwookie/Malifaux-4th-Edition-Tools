# M4E Data Inventory Report
**Generated: February 23, 2026**

---

## Database Status

| Source | Status |
|--------|--------|
| `m4e.db` (SQLite) | ⚠️ **CORRUPTED** — file has SQLite header but binary content has been mangled (bytes replaced with Unicode replacement characters). Not readable. |
| JSON files (8 faction + crew + tokens + faction summary + upgrade) | ✅ All readable and intact |

**The JSON files are the authoritative data source.** The database will need to be rebuilt from them.

---

## Model (Stat) Cards — 790 Total

| Faction | Cards |
|---------|------:|
| Arcanists | 95 |
| Bayou | 100 |
| Explorer's Society | 100 |
| Guild | 99 |
| Neverborn | 97 |
| Outcasts | 104 |
| Resurrectionists | 107 |
| Ten Thunders | 88 |
| **Total** | **790** |

### Field Coverage

| Field | Present | % | Notes |
|-------|--------:|--:|-------|
| `name` | 790 | 100% | |
| `faction` | 790 | 100% | |
| `characteristics` | 790 | 100% | |
| `cost` | 790 | 100% | |
| `df` (Defense) | 790 | 100% | |
| `wp` (Willpower) | 790 | 100% | |
| `sp` (Speed) | 790 | 100% | |
| `sz` (Size) | 790 | 100% | |
| `health` | 789 | 100% | 1 card missing |
| `abilities` | 790 | 100% | |
| `attack_actions` | 786 | 99% | 4 cards missing |
| `tactical_actions` | 758 | 96% | 32 cards missing (many are valid — not all models have tactical actions) |
| `keywords` | 736 | 93% | **54 cards missing** — see below |
| `base_size` | varies | — | Present when applicable |

### 54 Models Missing Keywords

These are all **Versatile** models (Effigies/Emissaries, Riders, cross-faction models). They have no keyword because they belong to no specific keyword crew — this is likely *correct by design* since Versatile models aren't keyword-locked. The 54 includes:

- 8 Fate Effigy/Emissary pairs (16 cards — one Effigy + one Emissary per faction)
- 4 Mechanical Riders (one per original faction)
- Master title variants that gain Versatile
- Cross-faction models (e.g., Silurid, Spawn Mother, Gupps in Bayou)

### 78 Duplicate Name+Faction Entries (Expected)

These represent master title variants (base + title version of the same master) and Effigy/Emissary dual cards. Examples: `Som'er Teeth Jones (x2)`, `Arcane Fate (x2)`, `Lucas McCabe (x3)`. All expected and correct.

---

## Crew Cards — 126 Total

### Faction Assignment Issues

The crew cards have **inconsistent faction tagging** — some are tagged with their proper faction, some with a keyword name, and 18 are tagged `Unknown`/`unknown`.

| Category | Count | Examples |
|----------|------:|---------|
| Properly assigned to faction | 92 | Guild: 24, Bayou: 15, Ten Thunders: 14, etc. |
| Tagged with keyword instead of faction | 12 | `M&SU`, `Mercenary`, `Tri-Chi`, `Fae`, `Frontier`, `Savage`, `Syndicate`, `Wildfire`, `Redchapel`, `Transmortis` |
| Tagged `Unknown` / `unknown` | 18 | Adaptive Evolution (Marcus), Antique Dealer (McCabe), Clear Mind (Kastore), etc. |
| `Outcast` vs `Outcasts` inconsistency | 3 | Bounty Hunt, Shadow of the Noose, The Barrows Gang |

**Action needed:** 33 crew cards need faction field corrected.

### Crew Card Schema

Fields present: `name`, `faction`, `associated_master`, `associated_title`, `keyword_actions`

---

## Tokens — 77 Total

Schema is minimal — each token has only a `name` field. No descriptions, effects, or rules text.

---

## Faction Summary — 8 Factions

| Faction | Keywords Listed |
|---------|----------------:|
| Arcanists | 17 |
| Bayou | 13 |
| Explorer's Society | 13 |
| Guild | 20 |
| Neverborn | 28 |
| Outcasts | 13 |
| Resurrectionists | 27 |
| Ten Thunders | 22 |

### Keyword Cross-Reference Mismatches

The faction summary lists some keywords that don't appear in any model card's `keywords` field, and vice versa. Most "summary only" entries are **specific model names** (totems, unique models) rather than proper keywords.

| Faction | In Summary Only (not in model keywords) | In Models Only (not in summary) |
|---------|----------------------------------------|-------------------------------|
| Arcanists | Banasuva, Mouse | — |
| Bayou | — | Angler |
| Explorer's Society | Luna, Oro Boro | — |
| Guild | Disease Containment Unit, Mechanical Attendant, The Scribe | — |
| Neverborn | Abyssal Anchor, Blood Hunter, Erymanthian Boar, Jackalope, Lord Chompy Bits, Marathine, Primordial Magic, Razorspine Rattler, Urchin | — |
| Outcasts | Soul Battery | — |
| Resurrectionists | Corpse Curator, Noxious Nephilim, Soul Porter, Temperance, Zombie Chihuahua | — |
| Ten Thunders | Ama No Zako, Amanjaku, Aspiring Student, Forgeling, Mu Long, Paper Tiger, Shang | — |

**Interpretation:** The faction summary appears to include totem/unique model names as "keywords" — these are model names, not crew keywords. The summary data conflates the two concepts.

---

## Other Data

| File | Contents |
|------|----------|
| `m4e_upgrade_angler_white_whale.json` | Single upgrade card with `name`, `faction`, `keyword`, `limitations`, `abilities` |

---

## Priority Issues to Address

1. **🔴 Database corrupted** — `m4e.db` needs full rebuild from JSON sources
2. **🟡 33 crew cards have wrong/missing faction** — 12 tagged with keyword name, 18 unknown, 3 with `Outcast` vs `Outcasts` typo
3. **🟡 Faction summary mixes model names with keywords** — may cause confusion in downstream tools
4. **🟢 54 models missing keywords** — likely correct (Versatile models), but worth confirming
5. **🟢 Token data is name-only** — may want to enrich with effect descriptions later
