PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    notify_email INTEGER NOT NULL DEFAULT 0,
    notify_telegram INTEGER NOT NULL DEFAULT 0,
    telegram_chat_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS search_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_search_categories_user_id ON search_categories(user_id);

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category_id INTEGER REFERENCES search_categories(id) ON DELETE SET NULL,
    title_keywords TEXT NOT NULL,
    content_keywords TEXT,
    min_price REAL,
    max_price REAL,
    latitude REAL,
    longitude REAL,
    radius_km REAL,
    excluded_words TEXT,
    shipping_filter TEXT NOT NULL DEFAULT 'any' CHECK (shipping_filter IN ('any', 'shipping', 'inperson')),
    search_wallapop INTEGER NOT NULL DEFAULT 1,
    search_cashconverters INTEGER NOT NULL DEFAULT 0,
    search_cex INTEGER NOT NULL DEFAULT 0,
    search_milanuncios INTEGER NOT NULL DEFAULT 0,
    scan_interval_minutes INTEGER NOT NULL DEFAULT 60 CHECK (scan_interval_minutes >= 5),
    is_active INTEGER NOT NULL DEFAULT 1,
    notify_enabled INTEGER NOT NULL DEFAULT 1,
    last_scan_at TEXT,
    last_scan_status TEXT,
    last_scan_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_searches_user_id ON searches(user_id);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    platform TEXT NOT NULL DEFAULT 'wallapop' CHECK (platform IN ('wallapop', 'cashconverters', 'cex', 'milanuncios')),
    item_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    price REAL,
    previous_price REAL,
    currency TEXT,
    url TEXT NOT NULL,
    image_url TEXT,
    location TEXT,
    latitude REAL,
    longitude REAL,
    shipping_allowed INTEGER NOT NULL DEFAULT 0,
    published_at TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_checked_at TEXT,
    is_unseen INTEGER NOT NULL DEFAULT 1,
    is_sold INTEGER NOT NULL DEFAULT 0,
    is_reserved INTEGER NOT NULL DEFAULT 0,
    discarded INTEGER NOT NULL DEFAULT 0,
    discarded_at TEXT,
    UNIQUE(search_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_results_search_id ON results(search_id);
CREATE INDEX IF NOT EXISTS idx_results_search_active
    ON results(search_id, discarded, is_sold);
