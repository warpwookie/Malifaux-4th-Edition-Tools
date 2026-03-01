-- ============================================================
-- M4E Card Database Schema v2
-- Supports all factions, keywords, card types
-- ============================================================

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ============================================================
-- CORE TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS models (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    title           TEXT,                               -- e.g., "Bayou Boss", "Loot Monger"
    faction         TEXT NOT NULL,                       -- Guild, Arcanists, Neverborn, Bayou, Outcasts, Resurrectionists, Ten Thunders, Explorer's Society
    station         TEXT,                                -- Master, Henchman, Minion, Totem, Peon, or NULL
    model_limit     INTEGER DEFAULT 1,                  -- 1 for Unique, N for Minion(N)/Peon(N)
    cost            TEXT,                                -- Hiring cost. "-" for leaders/totems. Numeric string otherwise.
    df              INTEGER NOT NULL,
    wp              INTEGER NOT NULL,
    sz              INTEGER NOT NULL,
    sp              INTEGER NOT NULL,
    health          INTEGER NOT NULL,
    soulstone_cache INTEGER,                            -- Starting soulstone cache (Masters only, usually)
    shields         INTEGER DEFAULT 0,                  -- Starting Shielded tokens
    base_size       TEXT,                                -- "30mm", "40mm", "50mm"
    infuses_soulstone_on_death BOOLEAN DEFAULT 1,       -- Soulstone icon in health bar
    crew_card_name  TEXT,                                -- Master only: associated crew card
    totem           TEXT,                                -- Master only: associated totem
    source_pdf      TEXT,                                -- Original PDF filename for traceability
    parse_date      TEXT,                                -- ISO date when parsed
    parse_status    TEXT DEFAULT 'auto',                 -- auto, human_reviewed, flagged
    UNIQUE(name, title, faction)
);

CREATE TABLE IF NOT EXISTS model_keywords (
    model_id    INTEGER NOT NULL,
    keyword     TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE,
    UNIQUE(model_id, keyword)
);

CREATE TABLE IF NOT EXISTS model_characteristics (
    model_id        INTEGER NOT NULL,
    characteristic  TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE,
    UNIQUE(model_id, characteristic)
);

CREATE TABLE IF NOT EXISTS model_factions (
    model_id    INTEGER NOT NULL,
    faction     TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE,
    UNIQUE(model_id, faction)
);

CREATE TABLE IF NOT EXISTS abilities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id        INTEGER NOT NULL,
    name            TEXT NOT NULL,
    defensive_type  TEXT,                                -- "fortitude", "warding", "unusual_defense", or NULL
    text            TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS actions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id                INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    category                TEXT NOT NULL,               -- "attack_actions" or "tactical_actions"
    action_type             TEXT,                         -- "melee", "missile", "magic", "variable" (attacks only; NULL for tacticals)
    range                   TEXT,                         -- e.g., '(melee)2"', '(gun)10"', '(aura)4"', '8"', NULL
    skill_value             INTEGER,                     -- Skl number; NULL if "-"
    skill_built_in_suit     TEXT,                         -- Built-in suit: "r","m","t","c" or NULL
    skill_fate_modifier     TEXT,                         -- "+" or "-" or NULL
    resist                  TEXT,                         -- "Df","Wp","Sz","Sp","Mv" or NULL (tacticals)
    tn                      INTEGER,                     -- Target Number or NULL
    damage                  TEXT,                         -- Damage value as string (can be "2", "X", etc.) or NULL
    is_signature            BOOLEAN DEFAULT 0,
    soulstone_cost          INTEGER DEFAULT 0,           -- 0, 1, or 2
    effects                 TEXT,                         -- Resolution effect text (non-italic body text)
    action_cost             TEXT,                         -- Italic preamble: additional costs (e.g., "Discard a card.")
    restrictions            TEXT,                         -- Italic preamble: usage limits (e.g., "Ally only. Once per turn.")
    special_conditions      TEXT,                         -- Italic preamble: other conditions (e.g., "This action ignores range and LoS.")
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS triggers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id       INTEGER NOT NULL,
    name            TEXT NOT NULL,
    suit            TEXT,                                -- e.g., "(r)", "(m)(m)", "(c)(c)", "(t)"
    timing          TEXT,                                -- See ENUM below
    text            TEXT NOT NULL,
    is_mandatory    BOOLEAN DEFAULT 0,
    soulstone_cost  INTEGER DEFAULT 0,                   -- 0, 1, or 2
    FOREIGN KEY (action_id) REFERENCES actions(id) ON DELETE CASCADE
);
-- timing ENUM: "when_resolving", "after_succeeding", "after_failing", 
--              "after_damaging", "when_declaring", "after_resolving"

-- ============================================================
-- CREW CARDS (Master-associated keyword grants)
-- ============================================================

CREATE TABLE IF NOT EXISTS crew_cards (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    associated_master   TEXT NOT NULL,
    associated_title    TEXT NOT NULL,
    faction             TEXT NOT NULL,
    crew_tracker        TEXT,                         -- Crew-specific tracker/bar name (e.g., "Research Bar", "Scandal Bar", "Fieldwork Objectives")
    source_pdf          TEXT,
    parse_date          TEXT,
    parse_status        TEXT DEFAULT 'auto'
);

CREATE TABLE IF NOT EXISTS crew_keyword_abilities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_card_id    INTEGER NOT NULL,
    granted_to      TEXT NOT NULL,                       -- e.g., "Friendly Angler models"
    name            TEXT NOT NULL,
    defensive_type  TEXT,
    text            TEXT NOT NULL,
    FOREIGN KEY (crew_card_id) REFERENCES crew_cards(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crew_keyword_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_card_id    INTEGER NOT NULL,
    granted_to      TEXT NOT NULL,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    action_type     TEXT,
    range           TEXT,
    skill_value     INTEGER,
    skill_built_in_suit TEXT,
    resist          TEXT,
    tn              INTEGER,
    damage          TEXT,
    is_signature    BOOLEAN DEFAULT 0,
    soulstone_cost  INTEGER DEFAULT 0,
    effects             TEXT,
    action_cost         TEXT,
    restrictions        TEXT,
    special_conditions  TEXT,
    FOREIGN KEY (crew_card_id) REFERENCES crew_cards(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crew_keyword_action_triggers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_action_id  INTEGER NOT NULL,
    name            TEXT NOT NULL,
    suit            TEXT,
    timing          TEXT,
    text            TEXT NOT NULL,
    is_mandatory    BOOLEAN DEFAULT 0,
    soulstone_cost  INTEGER DEFAULT 0,
    FOREIGN KEY (crew_action_id) REFERENCES crew_keyword_actions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crew_markers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_card_id    INTEGER NOT NULL,
    name            TEXT NOT NULL,
    size            TEXT,
    height          TEXT,
    text            TEXT,
    FOREIGN KEY (crew_card_id) REFERENCES crew_cards(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crew_marker_terrain_traits (
    marker_id   INTEGER NOT NULL,
    trait        TEXT NOT NULL,
    FOREIGN KEY (marker_id) REFERENCES crew_markers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crew_tokens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    crew_card_id    INTEGER NOT NULL,
    name            TEXT NOT NULL,
    text            TEXT NOT NULL,
    FOREIGN KEY (crew_card_id) REFERENCES crew_cards(id) ON DELETE CASCADE
);

-- ============================================================
-- TOKEN REFERENCE (global registry)
-- ============================================================

CREATE TABLE IF NOT EXISTS tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    type        TEXT,                                    -- "buff", "debuff", "penalty", "damage"
    timing      TEXT,                                    -- "end_activation", "end_phase", "on_use", "permanent", etc.
    rules_text  TEXT,                                    -- Canonical rules text from rulebook
    cancels     TEXT                                     -- Name of token this cancels (e.g., Slow cancels Fast)
);

CREATE TABLE IF NOT EXISTS token_model_sources (
    token_id    INTEGER NOT NULL,
    model_id    INTEGER NOT NULL,
    source_type TEXT NOT NULL,                           -- "ability", "action_effect", "trigger", "demise"
    source_name TEXT NOT NULL,                           -- Name of the ability/action/trigger
    applies_or_references TEXT DEFAULT 'applies',        -- "applies", "removes", "references"
    FOREIGN KEY (token_id) REFERENCES tokens(id) ON DELETE CASCADE,
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);

-- ============================================================
-- MARKER REFERENCE (global registry)
-- ============================================================

CREATE TABLE IF NOT EXISTS markers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,                    -- "Ice Pillar", "Scheme", "Piano"
    category        TEXT NOT NULL,                           -- "universal" or "keyword_specific"
    subcategory     TEXT,                                    -- "scheme"/"remains"/"strategy" (universal only)
    default_size    TEXT DEFAULT '30mm',                     -- "30mm", "40mm", "50mm"
    default_height  TEXT DEFAULT 'Ht 0',                    -- "Ht 0", "Ht 3", etc.
    terrain_traits_csv TEXT,                                 -- Denormalized quick-ref: "blocking, impassable"
    rules_text      TEXT,                                    -- Canonical marker rules/effects
    keyword         TEXT                                     -- Owning keyword (null for universal)
);

CREATE TABLE IF NOT EXISTS marker_terrain_traits (
    marker_id   INTEGER NOT NULL,
    trait        TEXT NOT NULL,                              -- "blocking", "concealing", "destructible", etc.
    FOREIGN KEY (marker_id) REFERENCES markers(id) ON DELETE CASCADE,
    UNIQUE(marker_id, trait)
);

CREATE TABLE IF NOT EXISTS marker_crew_sources (
    marker_id       INTEGER NOT NULL,
    crew_card_id    INTEGER NOT NULL,
    FOREIGN KEY (marker_id) REFERENCES markers(id) ON DELETE CASCADE,
    FOREIGN KEY (crew_card_id) REFERENCES crew_cards(id) ON DELETE CASCADE,
    UNIQUE(marker_id, crew_card_id)
);

CREATE TABLE IF NOT EXISTS marker_model_sources (
    marker_id       INTEGER NOT NULL,
    model_id        INTEGER NOT NULL,
    source_type     TEXT NOT NULL,                           -- "ability", "action_effect", "trigger"
    source_name     TEXT NOT NULL,                           -- Name of the ability/action/trigger
    relationship    TEXT DEFAULT 'references',               -- "creates", "removes", "references"
    FOREIGN KEY (marker_id) REFERENCES markers(id) ON DELETE CASCADE,
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);

-- ============================================================
-- PARSE AUDIT LOG
-- ============================================================

CREATE TABLE IF NOT EXISTS parse_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pdf  TEXT NOT NULL,
    model_name  TEXT,
    timestamp   TEXT NOT NULL,                           -- ISO datetime
    status      TEXT NOT NULL,                           -- "success", "validation_failed", "human_review", "error"
    hard_rule_violations TEXT,                           -- JSON array of violations
    soft_rule_flags TEXT,                                -- JSON array of flags
    hallucination_flags TEXT,                            -- JSON array of suspected hallucinations
    notes       TEXT
);

-- ============================================================
-- UPGRADE CARDS (keyword-based attachable upgrades)
-- ============================================================

CREATE TABLE IF NOT EXISTS upgrades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    upgrade_type    TEXT,                                -- "Equipment", "Training", "Loot", etc.
    keyword         TEXT,                                -- Associated keyword (e.g., "Freikorps")
    faction         TEXT NOT NULL,                       -- Home faction
    limitations     TEXT,                                -- "Plentiful (2)", "Restricted: Freikorps", etc.
    description     TEXT,                                -- Introductory text
    source_pdf      TEXT,
    parse_date      TEXT,
    parse_status    TEXT DEFAULT 'auto'
);

CREATE TABLE IF NOT EXISTS upgrade_abilities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upgrade_id      INTEGER NOT NULL,
    name            TEXT NOT NULL,
    defensive_type  TEXT,                                -- "fortitude", "warding", "unusual_defense", or NULL
    text            TEXT NOT NULL,
    FOREIGN KEY (upgrade_id) REFERENCES upgrades(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS upgrade_actions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    upgrade_id              INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    category                TEXT NOT NULL,               -- "attack_actions" or "tactical_actions"
    action_type             TEXT,                         -- "melee", "missile", "magic", "variable" or NULL
    range                   TEXT,
    skill_value             INTEGER,
    skill_built_in_suit     TEXT,
    skill_fate_modifier     TEXT,
    resist                  TEXT,
    tn                      INTEGER,
    damage                  TEXT,
    is_signature            BOOLEAN DEFAULT 0,
    soulstone_cost          INTEGER DEFAULT 0,
    effects                 TEXT,
    action_cost             TEXT,
    restrictions            TEXT,
    special_conditions      TEXT,
    FOREIGN KEY (upgrade_id) REFERENCES upgrades(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS upgrade_action_triggers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id       INTEGER NOT NULL,
    name            TEXT NOT NULL,
    suit            TEXT,
    timing          TEXT,
    text            TEXT NOT NULL,
    is_mandatory    BOOLEAN DEFAULT 0,
    soulstone_cost  INTEGER DEFAULT 0,
    FOREIGN KEY (action_id) REFERENCES upgrade_actions(id) ON DELETE CASCADE
);

-- Universal triggers: granted to ALL attack actions (e.g., Bestial Form)
CREATE TABLE IF NOT EXISTS upgrade_universal_triggers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    upgrade_id      INTEGER NOT NULL,
    name            TEXT NOT NULL,
    suit            TEXT,
    timing          TEXT,
    text            TEXT NOT NULL,
    is_mandatory    BOOLEAN DEFAULT 0,
    soulstone_cost  INTEGER DEFAULT 0,
    FOREIGN KEY (upgrade_id) REFERENCES upgrades(id) ON DELETE CASCADE
);

-- ============================================================
-- RULES, FAQ, AND GAINING GROUNDS
-- ============================================================

CREATE TABLE IF NOT EXISTS rules_sections (
    id          TEXT PRIMARY KEY,                            -- e.g., "glossary", "stat_cards"
    title       TEXT NOT NULL,
    pages       TEXT,                                        -- JSON array of page refs, e.g., '["2-3"]'
    content     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS faq_entries (
    id              TEXT PRIMARY KEY,                        -- e.g., "1.1", "2.3"
    section         TEXT NOT NULL,                           -- e.g., "GENERAL", "ABILITIES"
    section_number  INTEGER NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategies (
    id              TEXT PRIMARY KEY,                        -- e.g., "strategy_boundary_dispute"
    name            TEXT NOT NULL,
    suit            TEXT,                                    -- "(r)", "(m)", "(t)", "(c)"
    max_vp          INTEGER NOT NULL,
    setup           TEXT,
    rules           TEXT,
    scoring         TEXT,
    additional_vp   TEXT
);

CREATE TABLE IF NOT EXISTS schemes (
    id                      TEXT PRIMARY KEY,                -- e.g., "scheme_assassinate"
    name                    TEXT NOT NULL,
    max_vp                  INTEGER NOT NULL,
    selection               TEXT,                            -- NULL if no selection step
    reveal                  TEXT,
    scoring                 TEXT,
    additional_vp           TEXT,
    next_available_schemes  TEXT                             -- JSON array of scheme names
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_models_faction ON models(faction);
CREATE INDEX IF NOT EXISTS idx_models_name ON models(name);
CREATE INDEX IF NOT EXISTS idx_model_keywords_keyword ON model_keywords(keyword);
CREATE INDEX IF NOT EXISTS idx_actions_model ON actions(model_id);
CREATE INDEX IF NOT EXISTS idx_triggers_action ON triggers(action_id);
CREATE INDEX IF NOT EXISTS idx_abilities_model ON abilities(model_id);
CREATE INDEX IF NOT EXISTS idx_model_factions_faction ON model_factions(faction);
CREATE INDEX IF NOT EXISTS idx_parse_log_status ON parse_log(status);
CREATE INDEX IF NOT EXISTS idx_upgrades_faction ON upgrades(faction);
CREATE INDEX IF NOT EXISTS idx_upgrades_keyword ON upgrades(keyword);
CREATE INDEX IF NOT EXISTS idx_upgrade_actions_upgrade ON upgrade_actions(upgrade_id);
CREATE INDEX IF NOT EXISTS idx_upgrade_action_triggers_action ON upgrade_action_triggers(action_id);
CREATE INDEX IF NOT EXISTS idx_markers_name ON markers(name);
CREATE INDEX IF NOT EXISTS idx_markers_keyword ON markers(keyword);
CREATE INDEX IF NOT EXISTS idx_marker_crew_sources_marker ON marker_crew_sources(marker_id);
CREATE INDEX IF NOT EXISTS idx_marker_model_sources_marker ON marker_model_sources(marker_id);
CREATE INDEX IF NOT EXISTS idx_marker_model_sources_model ON marker_model_sources(model_id);
CREATE INDEX IF NOT EXISTS idx_faq_section ON faq_entries(section);
CREATE INDEX IF NOT EXISTS idx_schemes_name ON schemes(name);
