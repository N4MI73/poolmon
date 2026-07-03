-- =============================================================================
-- Pool Chemistry Tracker & Recovery Dashboard
-- Database Schema v4 (SQLite)
-- =============================================================================
--
-- CHANGE LOG FROM v3:
--   - NEW TABLE: chemical_products
--       A reference catalog of products you've actually purchased and used,
--       keyed by brand + product name + chemical type. Stores the default
--       available-chlorine percentage from the label so you pick from a list
--       rather than retyping "HTH Super Shock 73%" every time.
--       Strength can still be overridden at the point of logging a dose
--       (see chemical_additions.strength_pct_used) in case a new batch
--       comes in at a different concentration.
--
--   - chemical_additions: added product_id and strength_pct_used
--       product_id links to chemical_products (the brand/product used)
--       strength_pct_used is the actual % applied to the calculation,
--       recorded at the time of the addition so the stored recommendation
--       always reflects what was really used, not just what the label
--       usually says. Both are nullable - existing additions logged before
--       this feature existed remain valid.
--
-- NO CHANGES TO:
--   seasons, pool_config, chemistry_readings, chemical_inventory,
--   maintenance_log, water_level_events, equipment_incidents,
--   recovery_sessions, operational_status_history, photos,
--   notifications, assistant_notes, recommendations, daily_conditions
--
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- SEASONS
-- -----------------------------------------------------------------------------
CREATE TABLE seasons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label           TEXT NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT,
    is_current      INTEGER NOT NULL DEFAULT 0,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- POOL_CONFIG
-- -----------------------------------------------------------------------------
CREATE TABLE pool_config (
    id                           INTEGER PRIMARY KEY CHECK (id = 1),
    pool_type                    TEXT NOT NULL DEFAULT 'above_ground',
    shape                        TEXT NOT NULL DEFAULT 'round',
    diameter_ft                  REAL,
    length_ft                    REAL,
    width_ft                     REAL,
    avg_depth_ft                 REAL NOT NULL,
    volume_gallons               INTEGER NOT NULL,
    filter_type                  TEXT,
    filter_model                 TEXT,
    pump_model                   TEXT,
    sanitizer_type               TEXT NOT NULL DEFAULT 'liquid_chlorine',
    liquid_chlorine_strength_pct REAL DEFAULT 12.5,
    clean_filter_pressure_psi    REAL,
    test_kit_name                TEXT,
    current_mode                 TEXT NOT NULL DEFAULT 'maintenance',
    active_recovery_session_id   INTEGER,
    current_operational_status   TEXT NOT NULL DEFAULT 'swimming_ready',
    updated_at                   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- CHEMICAL_PRODUCTS  (NEW)
-- A user-built catalog of products they've actually purchased, keyed by
-- brand + product name + chemical type. One row per distinct product.
--
-- WHY THIS DESIGN (not just a free-text field on chemical_additions):
--   - Once "HTH Super Shock 73%" is entered once, it's selectable from a
--     dropdown on all future additions - no retyping, no typos, consistent
--     history.
--   - The stored strength_pct_default is what pre-fills the dose calculator,
--     but chemical_additions.strength_pct_used records what was actually
--     applied, so the math audit trail is always complete.
--   - is_active lets you retire a product you no longer buy without deleting
--     the history of additions that used it.
--   - Multiple products can share a chemical_type (e.g. two different brands
--     of Cal-Hypo at different strengths) - they're just different rows.
--
-- CHEMICAL TYPES (chemical_type column):
--   'liquid_chlorine'      - sodium hypochlorite solution (10-12.5%)
--   'cal_hypo'             - calcium hypochlorite granular shock (47-73%)
--   'trichlor_tablet'      - trichlor 3" tablets (~90%)
--   'stabilizer'           - cyanuric acid granules (~100%)
--   'muriatic_acid'        - hydrochloric acid solution (typically 31.45%)
--   'calcium_chloride'     - calcium hardness increaser (~77-80%)
--   'baking_soda'          - sodium bicarbonate (~100%)
--   'alkalinity_increaser' - usually also sodium bicarbonate, may be branded
--   'algaecide'            - various, no strength calculation needed
--   'other'                - anything else, no strength calculation needed
-- -----------------------------------------------------------------------------
CREATE TABLE chemical_products (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    chemical_type        TEXT NOT NULL,
                             -- see CHEMICAL TYPES above
    brand                TEXT NOT NULL,              -- e.g. 'HTH', 'In The Swim', 'Clorox', 'Pool Essentials'
    product_name         TEXT NOT NULL,              -- e.g. 'Super Shock', 'Ultimate Shock', 'Granular Shock'
    strength_pct_default REAL,                       -- available chlorine % from label; NULL for non-dosed products
    package_size         TEXT,                       -- e.g. '1 lb bag', '1 gallon', '50 lb pail' - for reference only
    notes                TEXT,                       -- e.g. 'bought at Tractor Supply', 'pool store brand'
    is_active            INTEGER NOT NULL DEFAULT 1, -- 0 = retired product, hide from picker but keep history
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (chemical_type, brand, product_name)      -- prevent accidental duplicates
);

CREATE INDEX idx_products_type ON chemical_products(chemical_type);
CREATE INDEX idx_products_active ON chemical_products(is_active);

-- -----------------------------------------------------------------------------
-- CHEMISTRY_READINGS
-- -----------------------------------------------------------------------------
CREATE TABLE chemistry_readings (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id            INTEGER NOT NULL REFERENCES seasons(id),
    reading_date         TEXT NOT NULL,
    reading_time         TEXT,
    free_chlorine        REAL,
    combined_chlorine    REAL,
    ph                   REAL,
    total_alkalinity     REAL,
    calcium_hardness     REAL,
    cyanuric_acid        REAL,
    water_temp_f         REAL,
    filter_pressure_psi  REAL,
    weather              TEXT,
    air_temp_f           REAL,
    notes                TEXT,
    is_recovery_entry    INTEGER NOT NULL DEFAULT 0,
    recovery_period      TEXT,
    recovery_session_id  INTEGER REFERENCES recovery_sessions(id),
    test_method          TEXT NOT NULL DEFAULT 'direct',
    dilution_factor      REAL,
    is_suspect_reading   INTEGER NOT NULL DEFAULT 0,
    suspect_reason       TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_readings_date ON chemistry_readings(reading_date);
CREATE INDEX idx_readings_season ON chemistry_readings(season_id);
CREATE INDEX idx_readings_recovery ON chemistry_readings(recovery_session_id);

-- -----------------------------------------------------------------------------
-- DAILY_CONDITIONS
-- -----------------------------------------------------------------------------
CREATE TABLE daily_conditions (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id                 INTEGER NOT NULL REFERENCES seasons(id),
    condition_date            TEXT NOT NULL,
    reading_id                INTEGER REFERENCES chemistry_readings(id),
    air_temp_f                REAL,
    water_temp_f              REAL,
    sky_condition             TEXT,
    rainfall_inches           REAL,
    wind_condition            TEXT,
    swimmer_count             INTEGER,
    swim_duration_minutes     INTEGER,
    cover_installed_overnight INTEGER,
    cover_removed_during_day  INTEGER,
    debris_level              TEXT,
    debris_notes              TEXT,
    walls_brushed             INTEGER NOT NULL DEFAULT 0,
    floor_brushed             INTEGER NOT NULL DEFAULT 0,
    robot_cleaner_run         INTEGER NOT NULL DEFAULT 0,
    vacuumed_manually         INTEGER NOT NULL DEFAULT 0,
    skimmer_emptied           INTEGER NOT NULL DEFAULT 0,
    pump_basket_cleaned       INTEGER NOT NULL DEFAULT 0,
    notes                     TEXT,
    created_at                TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_daily_conditions_date ON daily_conditions(condition_date);
CREATE INDEX idx_daily_conditions_reading ON daily_conditions(reading_id);

-- -----------------------------------------------------------------------------
-- CHEMICAL_INVENTORY
-- -----------------------------------------------------------------------------
CREATE TABLE chemical_inventory (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chemical_name       TEXT NOT NULL UNIQUE,
    display_name        TEXT NOT NULL,
    unit                TEXT NOT NULL,
    current_quantity    REAL NOT NULL DEFAULT 0,
    low_stock_threshold REAL,
    notes               TEXT,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- CHEMICAL_ADDITIONS
-- Added: product_id (which product was used) and strength_pct_used (the
-- actual strength applied to the dose calculation at the time of logging).
--
-- WHY TWO FIELDS instead of just storing the product's default strength:
--   Labels say "up to 73%" or the bottle on the shelf is a different batch.
--   strength_pct_used is what the calculator actually used, frozen at the
--   time of the addition. If you pull up a dose from three months ago and
--   ask "Why?", the answer is always based on exactly what you entered then,
--   not whatever the product's current default happens to be.
-- -----------------------------------------------------------------------------
CREATE TABLE chemical_additions (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id                INTEGER NOT NULL REFERENCES seasons(id),
    inventory_id             INTEGER REFERENCES chemical_inventory(id),
    product_id               INTEGER REFERENCES chemical_products(id),  -- NEW: which product was used
    addition_date            TEXT NOT NULL,
    addition_time            TEXT,
    chemical_name            TEXT NOT NULL,
    quantity_added           REAL NOT NULL,
    unit                     TEXT NOT NULL,
    strength_pct_used        REAL,        -- NEW: actual % used in the dose calc, overrides product default if different
    reason                   TEXT,        -- 'scheduled_dose' | 'slam' | 'shock' | 'manual_adjustment' | etc.
    application_method       TEXT,        -- 'direct' | 'skimmer' | 'sock' | 'split' | 'floater' | NULL
    expected_stable_date     TEXT,
    backwash_hold_until_date TEXT,
    notes                    TEXT,
    created_at               TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_additions_date ON chemical_additions(addition_date);
CREATE INDEX idx_additions_backwash_hold ON chemical_additions(backwash_hold_until_date);
CREATE INDEX idx_additions_product ON chemical_additions(product_id);

-- -----------------------------------------------------------------------------
-- MAINTENANCE_LOG
-- -----------------------------------------------------------------------------
CREATE TABLE maintenance_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id           INTEGER NOT NULL REFERENCES seasons(id),
    event_date          TEXT NOT NULL,
    event_time          TEXT,
    event_type          TEXT NOT NULL,
    pressure_before_psi REAL,
    pressure_after_psi  REAL,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_maint_date ON maintenance_log(event_date);
CREATE INDEX idx_maint_type ON maintenance_log(event_type);

-- -----------------------------------------------------------------------------
-- WATER_LEVEL_EVENTS
-- -----------------------------------------------------------------------------
CREATE TABLE water_level_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id         INTEGER NOT NULL REFERENCES seasons(id),
    event_date        TEXT NOT NULL,
    reason            TEXT,
    estimated_gallons REAL,
    notes             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_waterlevel_date ON water_level_events(event_date);

-- -----------------------------------------------------------------------------
-- EQUIPMENT_INCIDENTS
-- -----------------------------------------------------------------------------
CREATE TABLE equipment_incidents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id        INTEGER NOT NULL REFERENCES seasons(id),
    incident_date    TEXT NOT NULL,
    incident_time    TEXT,
    component        TEXT NOT NULL,
    description      TEXT NOT NULL,
    cause_identified TEXT,
    resolution       TEXT,
    resolved_date    TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_equip_incidents_date ON equipment_incidents(incident_date);
CREATE INDEX idx_equip_incidents_component ON equipment_incidents(component);

-- -----------------------------------------------------------------------------
-- RECOVERY_SESSIONS
-- -----------------------------------------------------------------------------
CREATE TABLE recovery_sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id        INTEGER NOT NULL REFERENCES seasons(id),
    start_date       TEXT NOT NULL,
    end_date         TEXT,
    starting_cya     REAL,
    trigger_reason   TEXT,
    status           TEXT NOT NULL DEFAULT 'active',
    completion_notes TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- OPERATIONAL_STATUS_HISTORY
-- -----------------------------------------------------------------------------
CREATE TABLE operational_status_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id           INTEGER NOT NULL REFERENCES seasons(id),
    status              TEXT NOT NULL,
    status_date         TEXT NOT NULL,
    status_time         TEXT,
    reason              TEXT,
    recovery_session_id INTEGER REFERENCES recovery_sessions(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_status_history_date ON operational_status_history(status_date);
CREATE INDEX idx_status_history_season ON operational_status_history(season_id);

-- -----------------------------------------------------------------------------
-- PHOTOS
-- -----------------------------------------------------------------------------
CREATE TABLE photos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id           INTEGER NOT NULL REFERENCES seasons(id),
    recovery_session_id INTEGER REFERENCES recovery_sessions(id),
    photo_date          TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    caption             TEXT,
    tag                 TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_photos_date ON photos(photo_date);
CREATE INDEX idx_photos_recovery ON photos(recovery_session_id);

-- -----------------------------------------------------------------------------
-- NOTIFICATIONS
-- -----------------------------------------------------------------------------
CREATE TABLE notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_date TEXT NOT NULL DEFAULT (date('now')),
    category     TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'info',
    message      TEXT NOT NULL,
    is_dismissed INTEGER NOT NULL DEFAULT 0,
    dismissed_at TEXT
);

CREATE INDEX idx_notif_dismissed ON notifications(is_dismissed);

-- -----------------------------------------------------------------------------
-- ASSISTANT_NOTES
-- -----------------------------------------------------------------------------
CREATE TABLE assistant_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    note_date  TEXT NOT NULL,
    reading_id INTEGER REFERENCES chemistry_readings(id),
    note_text  TEXT NOT NULL,
    note_type  TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_assistant_notes_date ON assistant_notes(note_date);

-- -----------------------------------------------------------------------------
-- RECOMMENDATIONS
-- -----------------------------------------------------------------------------
CREATE TABLE recommendations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id           INTEGER NOT NULL REFERENCES seasons(id),
    recovery_session_id INTEGER REFERENCES recovery_sessions(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    recommendation_type TEXT NOT NULL,
    summary             TEXT NOT NULL,
    inputs_json         TEXT,
    was_followed        INTEGER,
    chemical_addition_id INTEGER REFERENCES chemical_additions(id)
);

CREATE INDEX idx_recommendations_date ON recommendations(created_at);

-- =============================================================================
-- SEED DATA
-- =============================================================================

INSERT INTO pool_config (
    id, pool_type, shape, diameter_ft, avg_depth_ft, volume_gallons,
    filter_type, filter_model, pump_model, sanitizer_type,
    liquid_chlorine_strength_pct, test_kit_name,
    current_mode, current_operational_status
) VALUES (
    1, 'above_ground', 'round', 24.5, 3.5, 12350,
    'sand', 'Hayward Vari-Flo XL Valve', 'Hayward SP1580X15',
    'liquid_chlorine', 12.5, 'Taylor K-1005',
    'maintenance', 'swimming_ready'
);

INSERT INTO chemical_inventory
    (chemical_name, display_name, unit, current_quantity, low_stock_threshold)
VALUES
    ('liquid_chlorine',      'Liquid Chlorine',           'gallons', 0, 2),
    ('cal_hypo',             'Cal-Hypo Granular Shock',   'lbs',     0, 2),
    ('trichlor_tablet',      'Trichlor 3" Tablets',       'count',   0, 6),
    ('stabilizer',           'Stabilizer (CYA)',           'lbs',     0, 2),
    ('muriatic_acid',        'Muriatic Acid',              'gallons', 0, 1),
    ('calcium_chloride',     'Calcium Hardness Increaser', 'lbs',     0, 2),
    ('baking_soda',          'Baking Soda / Alk Increaser','lbs',     0, 2);

-- Starter product catalog: a handful of well-known products covering the
-- three strength-critical chemicals. The user will add their own as they
-- log additions; these are just there so the picker isn't empty on first use.
INSERT INTO chemical_products
    (chemical_type, brand, product_name, strength_pct_default, package_size, notes)
VALUES
    -- Liquid chlorine
    ('liquid_chlorine', 'Pool Essentials',  'Chlorinating Liquid',    10.0,  '1 gallon',   'Common big-box store brand'),
    ('liquid_chlorine', 'In The Swim',      'Chlorine Liquid',        12.5,  '1 gallon',   'Pool supply / online'),
    ('liquid_chlorine', 'Clorox',           'Pool & Spa Shock',       10.0,  '1 gallon',   'Available at most hardware stores'),
    ('liquid_chlorine', 'Generic / Store',  'Liquid Chlorine 12.5%',  12.5,  '1 gallon',   'Any 12.5% label'),
    ('liquid_chlorine', 'Generic / Store',  'Liquid Chlorine 10%',    10.0,  '1 gallon',   'Any 10% label'),
    -- Cal-Hypo granular shock
    ('cal_hypo', 'HTH',         'Super Shock',           73.0, '1 lb bag',  'Orange bag, common at hardware stores'),
    ('cal_hypo', 'HTH',         'Granular Shock',        65.0, '1 lb bag',  'Standard HTH shock'),
    ('cal_hypo', 'Clorox',      'Pool & Spa XtraBlue',   56.0, '1 lb bag',  'Lower-strength, widely available'),
    ('cal_hypo', 'In The Swim', 'Calcium Hypochlorite',  73.0, '1 lb bag',  'Pool supply brand'),
    ('cal_hypo', 'BioGuard',    'Burn Out 73',           73.0, '1 lb bag',  'Pool store brand'),
    ('cal_hypo', 'Generic',     'Cal-Hypo 65%',          65.0, '1 lb bag',  'Any 65% label'),
    ('cal_hypo', 'Generic',     'Cal-Hypo 73%',          73.0, '1 lb bag',  'Any 73% label'),
    -- Trichlor tablets (strength is fixed at ~90%, brand doesn't affect math much)
    ('trichlor_tablet', 'HTH',         '3" Chlorinating Tablets', 90.0, '5 lb bucket', NULL),
    ('trichlor_tablet', 'In The Swim', 'Trichlor Tablets 3"',     90.0, '50 lb bucket', 'Bulk pool supply'),
    ('trichlor_tablet', 'Clorox',      'Pool & Spa XtraBlue 3"',  90.0, '5 lb bucket', NULL),
    ('trichlor_tablet', 'Generic',     'Trichlor 3" Tablets 90%', 90.0, '5 lb bucket', 'Any 90% trichlor'),
    -- Stabilizer (strength doesn't affect dosing math directly - 100% CYA)
    ('stabilizer', 'HTH',         'Stabilizer & Conditioner', NULL, '4 lb bag', NULL),
    ('stabilizer', 'In The Swim', 'Cyanuric Acid',            NULL, '4 lb bag', NULL),
    ('stabilizer', 'Generic',     'Granular Stabilizer',       NULL, '4 lb bag', NULL),
    -- Muriatic acid (always 31.45% in the US, but tracking brand is still useful)
    ('muriatic_acid', 'Klean Strip', 'Green Muriatic Acid',     31.45, '1 gallon', 'Widely available, lower fumes formula'),
    ('muriatic_acid', 'HTH',         'Muriatic Acid',           31.45, '1 gallon', NULL),
    ('muriatic_acid', 'Generic',     'Muriatic Acid 31.45%',    31.45, '1 gallon', 'Standard pool/hardware store acid');

INSERT INTO seasons (label, start_date, is_current)
VALUES ('2026 Season', '2026-01-01', 1);

INSERT INTO operational_status_history (season_id, status, status_date, reason)
VALUES (1, 'swimming_ready', '2026-01-01', 'Initial season setup');
